import json
from typing import Any
from uuid import UUID

import asyncpg

CREATE_RESEARCH_OUTBOX_TABLE = """
CREATE TABLE IF NOT EXISTS research_outbox (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id UUID NOT NULL UNIQUE
        REFERENCES research_jobs(id) ON DELETE CASCADE,

    payload JSONB NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ,

    attempts INTEGER NOT NULL DEFAULT 0,

    lock_token UUID,
    locked_until TIMESTAMPTZ,

    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_outbox_pending
ON research_outbox (available_at, id)
WHERE published_at IS NULL;
"""


BACKFILL_QUEUED_RESEARCH_JOBS = """
INSERT INTO research_outbox (job_id, payload)
SELECT id, request_payload
FROM research_jobs
WHERE status = 'queued'
ON CONFLICT (job_id) DO NOTHING;
"""


async def initialize_research_outbox(pool: asyncpg.Pool) -> None:
    """Create outbox storage and backfill previously queued jobs."""

    await pool.execute(CREATE_RESEARCH_OUTBOX_TABLE)
    await pool.execute(BACKFILL_QUEUED_RESEARCH_JOBS)


async def insert_research_outbox_record(
    connection: asyncpg.Connection,
    job_id: UUID,
    payload: dict[str, Any],
) -> None:
    """Insert an outbox record using the caller's active transaction."""

    await connection.execute(
        """
        INSERT INTO research_outbox (job_id, payload)
        VALUES ($1, $2::jsonb)
        ON CONFLICT (job_id) DO NOTHING
        """,
        job_id,
        json.dumps(payload, ensure_ascii=False, default=str),
    )


async def claim_pending_outbox_records(
    pool: asyncpg.Pool,
    lock_token: UUID,
    batch_size: int = 10,
    lease_duration_seconds: int = 60,
) -> list[asyncpg.Record]:
    """Atomically claim due outbox records across concurrent publishers."""

    if batch_size <= 0:
        raise ValueError("Batch size must be greater than zero.")

    if lease_duration_seconds <= 0:
        raise ValueError("Outbox lease duration must be greater than zero.")

    return await pool.fetch(
        """
        WITH candidates AS (
            SELECT id
            FROM research_outbox
            WHERE published_at IS NULL
              AND available_at <= NOW()
              AND (
                  locked_until IS NULL
                  OR locked_until <= NOW()
              )
            ORDER BY available_at, id
            LIMIT $1
            FOR UPDATE SKIP LOCKED
        )
        UPDATE research_outbox AS outbox
        SET lock_token = $2,
            locked_until = NOW()
                + ($3::double precision * INTERVAL '1 second'),
            attempts = outbox.attempts + 1
        FROM candidates
        WHERE outbox.id = candidates.id
        RETURNING
            outbox.id,
            outbox.job_id,
            outbox.payload,
            outbox.attempts,
            outbox.lock_token
        """,
        batch_size,
        lock_token,
        lease_duration_seconds,
    )


async def mark_outbox_record_published(
    pool: asyncpg.Pool,
    outbox_id: int,
    lock_token: UUID,
) -> bool:
    """Mark a record published only when the caller still owns its lease."""

    result = await pool.fetchval(
        """
        UPDATE research_outbox
        SET published_at = NOW(),
            lock_token = NULL,
            locked_until = NULL,
            last_error = NULL
        WHERE id = $1
          AND lock_token = $2
          AND published_at IS NULL
        RETURNING TRUE
        """,
        outbox_id,
        lock_token,
    )

    return result is True


async def reschedule_outbox_record(
    pool: asyncpg.Pool,
    outbox_id: int,
    lock_token: UUID,
    error: str,
    retry_delay_seconds: int,
) -> bool:
    """Release a failed publication for retry after a bounded delay."""

    if retry_delay_seconds < 1:
        raise ValueError("Retry delay must be at least one second.")

    result = await pool.fetchval(
        """
        UPDATE research_outbox
        SET available_at = NOW()
                + ($4::double precision * INTERVAL '1 second'),
            lock_token = NULL,
            locked_until = NULL,
            last_error = $3
        WHERE id = $1
          AND lock_token = $2
          AND published_at IS NULL
        RETURNING TRUE
        """,
        outbox_id,
        lock_token,
        error[:2000],
        retry_delay_seconds,
    )

    return result is True
