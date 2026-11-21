import json
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from market_intelligence.db.repositories.research_outbox import (
    initialize_research_outbox,
    insert_research_outbox_record,
)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_LEASE_DURATION_SECONDS = 120
RESEARCH_JOBS_MIGRATION_LOCK_ID = 2026111901


CREATE_RESEARCH_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS research_jobs (
    id UUID PRIMARY KEY,
    question TEXT NOT NULL,
    request_payload JSONB NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'completed', 'failed')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result JSONB,
    error TEXT,

    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,

    worker_id TEXT,
    lease_token UUID,
    heartbeat_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_research_jobs_created_at
ON research_jobs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_jobs_status
ON research_jobs (status);

"""


# Migration for databases created before worker leases were introduced.
MIGRATE_RESEARCH_JOBS_LEASES = """
ALTER TABLE research_jobs
ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE research_jobs
ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 3;

ALTER TABLE research_jobs
ADD COLUMN IF NOT EXISTS worker_id TEXT;

ALTER TABLE research_jobs
ADD COLUMN IF NOT EXISTS lease_token UUID;

ALTER TABLE research_jobs
ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;

ALTER TABLE research_jobs
ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_research_jobs_lease_expiry
ON research_jobs (lease_expires_at)
WHERE status = 'running';

UPDATE research_jobs
SET lease_expires_at = NOW()
WHERE status = 'running'
  AND lease_expires_at IS NULL;
"""

MIGRATE_RESEARCH_JOBS_CANCELLATION = """
DO $migration$
DECLARE
    existing_definition TEXT;
BEGIN
    SELECT pg_get_constraintdef(oid)
    INTO existing_definition
    FROM pg_constraint
    WHERE conrelid = 'research_jobs'::regclass
      AND conname = 'research_jobs_status_check';

    IF existing_definition IS NULL THEN
        ALTER TABLE research_jobs
        ADD CONSTRAINT research_jobs_status_check
        CHECK (
            status IN (
                'queued',
                'running',
                'completed',
                'failed',
                'cancelled'
            )
        );

    ELSIF existing_definition NOT ILIKE '%cancelled%' THEN
        ALTER TABLE research_jobs
        DROP CONSTRAINT research_jobs_status_check;

        ALTER TABLE research_jobs
        ADD CONSTRAINT research_jobs_status_check
        CHECK (
            status IN (
                'queued',
                'running',
                'completed',
                'failed',
                'cancelled'
            )
        );
    END IF;
END
$migration$;
"""

MIGRATE_RESEARCH_JOBS_REVISIONS = """
ALTER TABLE research_jobs
ADD COLUMN IF NOT EXISTS turn_id UUID;

ALTER TABLE research_jobs
ADD COLUMN IF NOT EXISTS revision_number INTEGER NOT NULL DEFAULT 1;

-- Existing jobs become independent conversational turns.
UPDATE research_jobs
SET turn_id = id
WHERE turn_id IS NULL;

ALTER TABLE research_jobs
ALTER COLUMN turn_id SET NOT NULL;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'research_jobs'::regclass
          AND conname = 'research_jobs_revision_number_check'
    ) THEN
        ALTER TABLE research_jobs
        ADD CONSTRAINT research_jobs_revision_number_check
        CHECK (revision_number > 0);
    END IF;
END
$migration$;

CREATE UNIQUE INDEX IF NOT EXISTS
idx_research_jobs_turn_revision
ON research_jobs (turn_id, revision_number);

CREATE INDEX IF NOT EXISTS
idx_research_jobs_conversation_turn
ON research_jobs (conversation_id, turn_id);
"""


async def initialize_research_jobs(pool: asyncpg.Pool) -> None:
    """Initialize research jobs storage and apply serialized migrations."""

    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock($1)",
                RESEARCH_JOBS_MIGRATION_LOCK_ID,
            )

            await connection.execute(CREATE_RESEARCH_JOBS_TABLE)
            await connection.execute(MIGRATE_RESEARCH_JOBS_LEASES)
            await connection.execute(MIGRATE_RESEARCH_JOBS_CANCELLATION)
            await connection.execute(MIGRATE_RESEARCH_JOBS_REVISIONS)

    await initialize_research_outbox(pool)


async def create_research_job(
    pool: asyncpg.Pool,
    job_id: UUID,
    payload: dict[str, Any],
    user_id: UUID,
    conversation_id: UUID | None = None,
    turn_id: UUID | None = None,
    revision_number: int = 1,
) -> None:
    """
    Atomically persist a research job and its Redis publication intent.

    A normal new question receives its own turn ID.
    Subsequent revisions reuse the original turn ID.
    """

    resolved_turn_id = turn_id or job_id

    if revision_number < 1:
        raise ValueError("Revision number must be positive.")

    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                """
                INSERT INTO research_jobs (
                    id,
                    user_id,
                    conversation_id,
                    question,
                    request_payload,
                    status,
                    max_attempts,
                    turn_id,
                    revision_number
                )
                VALUES (
                    $1, $2, $3, $4, $5::jsonb,
                    'queued', $6, $7, $8
                )
                """,
                job_id,
                user_id,
                conversation_id,
                payload["question"],
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    default=str,
                ),
                DEFAULT_MAX_ATTEMPTS,
                resolved_turn_id,
                revision_number,
            )

            await insert_research_outbox_record(
                connection,
                job_id,
                payload,
            )


class ResearchJobRevisionConflict(Exception):
    """Raised when a research job cannot be revised."""


async def create_research_job_revision(
    pool: asyncpg.Pool,
    new_job_id: UUID,
    original_job_id: UUID,
    question: str,
    user_id: UUID,
    product_limit: int,
) -> tuple[UUID, UUID, int] | None:
    """
    Create a new execution revision for an existing conversational turn.

    Returns:
        (conversation_id, turn_id, revision_number)

    Returns None when the original job does not belong to the user.

    The original execution remains unchanged. The new execution and its
    outbox publication intent are committed in one transaction.
    """

    async with pool.acquire() as connection:
        async with connection.transaction():
            original = await connection.fetchrow(
                """
                SELECT
                    id,
                    user_id,
                    conversation_id,
                    turn_id,
                    revision_number,
                    status,
                    request_payload
                FROM research_jobs
                WHERE id = $1
                  AND user_id = $2
                FOR UPDATE
                """,
                original_job_id,
                user_id,
            )

            if original is None:
                return None

            if original["status"] not in {
                "completed",
                "failed",
                "cancelled",
            }:
                raise ResearchJobRevisionConflict(
                    "Only completed, failed, or cancelled research requests can be edited."
                )

            conversation_id = original["conversation_id"]

            if conversation_id is None:
                raise ResearchJobRevisionConflict(
                    "This research request is not associated with a conversation."
                )

            # Prevent editing an obsolete revision.
            latest_revision = await connection.fetchval(
                """
                SELECT MAX(revision_number)
                FROM research_jobs
                WHERE turn_id = $1
                  AND user_id = $2
                """,
                original["turn_id"],
                user_id,
            )

            if latest_revision != original["revision_number"]:
                raise ResearchJobRevisionConflict(
                    "This message has already been revised. "
                    "Refresh the conversation before editing it again."
                )

            # Verify and lock the owning conversation.
            conversation = await connection.fetchrow(
                """
                SELECT id
                FROM research_conversations
                WHERE id = $1
                  AND user_id = $2
                FOR UPDATE
                """,
                conversation_id,
                user_id,
            )

            if conversation is None:
                raise ResearchJobRevisionConflict("The associated conversation no longer exists.")

            original_payload = original["request_payload"]

            if isinstance(original_payload, str):
                original_payload = json.loads(original_payload)

            # Preserve the original research configuration.
            revised_payload = dict(original_payload)
            revised_payload["question"] = question
            revised_payload["product_limit"] = product_limit

            next_revision = original["revision_number"] + 1

            await connection.execute(
                """
                INSERT INTO research_jobs (
                    id,
                    user_id,
                    conversation_id,
                    question,
                    request_payload,
                    status,
                    max_attempts,
                    turn_id,
                    revision_number
                )
                VALUES (
                    $1, $2, $3, $4, $5::jsonb,
                    'queued', $6, $7, $8
                )
                """,
                new_job_id,
                user_id,
                conversation_id,
                question,
                json.dumps(
                    revised_payload,
                    ensure_ascii=False,
                    default=str,
                ),
                DEFAULT_MAX_ATTEMPTS,
                original["turn_id"],
                next_revision,
            )

            await insert_research_outbox_record(
                connection,
                new_job_id,
                revised_payload,
            )

            await connection.execute(
                """
                UPDATE research_conversations
                SET updated_at = NOW()
                WHERE id = $1
                  AND user_id = $2
                """,
                conversation_id,
                user_id,
            )

            return (
                conversation_id,
                original["turn_id"],
                next_revision,
            )


async def mark_job_running(
    pool: asyncpg.Pool,
    job_id: UUID,
) -> bool:
    """
    Legacy status transition retained for compatibility.

    New worker implementations should use claim_research_job()
    so that execution has an explicit lease owner.
    """

    result = await pool.fetchval(
        """
        UPDATE research_jobs
        SET status = 'running',
            started_at = COALESCE(started_at, NOW()),
            error = NULL
        WHERE id = $1
          AND status = 'queued'
        RETURNING TRUE
        """,
        job_id,
    )

    return result is True


async def claim_research_job(
    pool: asyncpg.Pool,
    job_id: UUID,
    worker_id: str,
    lease_duration_seconds: int = DEFAULT_LEASE_DURATION_SECONDS,
) -> UUID | None:
    """
    Atomically claim a queued job or recover a job with an expired lease.

    Returns a unique lease token when the claim succeeds.
    Returns None when another worker owns the job or the job is terminal.
    """

    if lease_duration_seconds <= 0:
        raise ValueError("Lease duration must be greater than zero.")

    # An expired job that has exhausted its attempts must become terminal.
    await pool.execute(
        """
        UPDATE research_jobs
        SET status = 'failed',
            error = 'Worker lease expired and maximum execution attempts were exhausted.',
            completed_at = NOW(),
            worker_id = NULL,
            lease_token = NULL,
            heartbeat_at = NULL,
            lease_expires_at = NULL
        WHERE id = $1
          AND attempt_count >= max_attempts
          AND (
              status = 'queued'
              OR (
                  status = 'running'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= NOW()
              )
          )
        """,
        job_id,
    )

    lease_token = uuid4()

    row = await pool.fetchrow(
        """
        UPDATE research_jobs
        SET status = 'running',
            attempt_count = attempt_count + 1,
            started_at = COALESCE(started_at, NOW()),
            worker_id = $2,
            lease_token = $3,
            heartbeat_at = NOW(),
            lease_expires_at = NOW() + ($4::double precision * INTERVAL '1 second'),
            error = NULL
        WHERE id = $1
          AND attempt_count < max_attempts
          AND (
              status = 'queued'
              OR (
                  status = 'running'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= NOW()
              )
          )
        RETURNING lease_token
        """,
        job_id,
        worker_id,
        lease_token,
        lease_duration_seconds,
    )

    if row is None:
        return None

    return row["lease_token"]


async def heartbeat_research_job(
    pool: asyncpg.Pool,
    job_id: UUID,
    lease_token: UUID,
    lease_duration_seconds: int = DEFAULT_LEASE_DURATION_SECONDS,
) -> bool:
    """
    Renew a running job's lease.

    The renewal succeeds only when the supplied token still owns the job.
    """

    if lease_duration_seconds <= 0:
        raise ValueError("Lease duration must be greater than zero.")

    row = await pool.fetchrow(
        """
        UPDATE research_jobs
        SET heartbeat_at = NOW(),
            lease_expires_at = NOW() + ($3::double precision * INTERVAL '1 second')
        WHERE id = $1
          AND status = 'running'
          AND lease_token = $2
          AND lease_expires_at > NOW()
        RETURNING id
        """,
        job_id,
        lease_token,
        lease_duration_seconds,
    )

    return row is not None


async def complete_research_job(
    pool: asyncpg.Pool,
    job_id: UUID,
    result: dict[str, Any],
    lease_token: UUID | None = None,
) -> bool:
    """
    Persist a successful result.

    When a lease token is supplied, only its current owner can complete
    the job. The None case temporarily supports the existing worker.
    Terminal jobs cannot be completed again.
    """

    row = await pool.fetchrow(
        """
        UPDATE research_jobs
        SET status = 'completed',
            result = $2::jsonb,
            completed_at = NOW(),
            error = NULL,
            worker_id = NULL,
            lease_token = NULL,
            heartbeat_at = NULL,
            lease_expires_at = NULL
        WHERE id = $1
          AND status = 'running'
          AND lease_token IS NOT DISTINCT FROM $3
          AND ($3::uuid IS NULL OR lease_expires_at > NOW())
        RETURNING id
        """,
        job_id,
        json.dumps(result, default=str),
        lease_token,
    )

    return row is not None


async def retry_research_job(
    pool: asyncpg.Pool,
    job_id: UUID,
    error: str,
    lease_token: UUID,
) -> str | None:
    """
    Release a running job for another attempt or mark it failed
    when its maximum attempt count has been reached.

    Returns:
        "queued": Another attempt is allowed.
        "failed": No attempts remain.
        None: Lease ownership was lost or the job is no longer running.
    """

    row = await pool.fetchrow(
        """
        UPDATE research_jobs
        SET status = CASE
                WHEN attempt_count < max_attempts THEN 'queued'
                ELSE 'failed'
            END,
            error = $2,
            completed_at = CASE
                WHEN attempt_count < max_attempts THEN NULL
                ELSE NOW()
            END,
            worker_id = NULL,
            lease_token = NULL,
            heartbeat_at = NULL,
            lease_expires_at = NULL
        WHERE id = $1
          AND status = 'running'
          AND lease_token = $3
          AND lease_expires_at > NOW()
        RETURNING status
        """,
        job_id,
        error[:2000],
        lease_token,
    )

    if row is None:
        return None

    return row["status"]


async def fail_research_job(
    pool: asyncpg.Pool,
    job_id: UUID,
    error: str,
    lease_token: UUID | None = None,
) -> bool:
    """
    Mark a queued or running job as failed.

    With a lease token, only the current worker can fail a running job.
    Without a token, only a job without an assigned lease can be failed.
    This supports the API's enqueue-failure handling.

    Completed and already-failed jobs cannot be overwritten.
    """

    row = await pool.fetchrow(
        """
        UPDATE research_jobs
        SET status = 'failed',
            error = $2,
            completed_at = NOW(),
            worker_id = NULL,
            lease_token = NULL,
            heartbeat_at = NULL,
            lease_expires_at = NULL
        WHERE id = $1
          AND status IN ('queued', 'running')
          AND lease_token IS NOT DISTINCT FROM $3
          AND ($3::uuid IS NULL OR lease_expires_at > NOW())
        RETURNING id
        """,
        job_id,
        error[:2000],
        lease_token,
    )

    return row is not None


async def cancel_research_job_for_user(
    pool: asyncpg.Pool,
    job_id: UUID,
    user_id: UUID,
) -> tuple[str, bool] | None:
    """
    Cancel a queued or running job belonging to the specified user.

    Returns:
        (status, True): This call successfully cancelled the job.
        (status, False): The job already had a terminal status.
        None: The job does not belong to the specified user.
    """

    row = await pool.fetchrow(
        """
        UPDATE research_jobs
        SET status = 'cancelled',
            error = 'Cancelled by user.',
            completed_at = NOW(),
            worker_id = NULL,
            lease_token = NULL,
            heartbeat_at = NULL,
            lease_expires_at = NULL
        WHERE id = $1
          AND user_id = $2
          AND status IN ('queued', 'running')
        RETURNING status
        """,
        job_id,
        user_id,
    )

    if row is not None:
        return row["status"], True

    existing = await pool.fetchrow(
        """
        SELECT status
        FROM research_jobs
        WHERE id = $1
          AND user_id = $2
        """,
        job_id,
        user_id,
    )

    if existing is None:
        return None

    return existing["status"], False


async def get_research_job(
    pool: asyncpg.Pool,
    job_id: UUID,
) -> dict[str, Any] | None:
    """Retrieve a research job by ID."""

    row = await pool.fetchrow(
        """
        SELECT
            id,
            question,
            status,
            created_at,
            started_at,
            completed_at,
            result,
            error,
            attempt_count,
            max_attempts,
            worker_id,
            lease_token,
            heartbeat_at,
            lease_expires_at
        FROM research_jobs
        WHERE id = $1
        """,
        job_id,
    )

    if row is None:
        return None

    result = row["result"]

    if isinstance(result, str):
        result = json.loads(result)

    return {
        "job_id": row["id"],
        "question": row["question"],
        "status": row["status"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "result": result,
        "error": row["error"],
        "attempt_count": row["attempt_count"],
        "max_attempts": row["max_attempts"],
        "worker_id": row["worker_id"],
        "lease_token": row["lease_token"],
        "heartbeat_at": row["heartbeat_at"],
        "lease_expires_at": row["lease_expires_at"],
    }


async def get_research_job_for_user(
    pool: asyncpg.Pool,
    job_id: UUID,
    user_id: UUID,
) -> dict[str, Any] | None:
    """Retrieve a research job only when it belongs to the specified user."""

    row = await pool.fetchrow(
        """
        SELECT
            id,
            question,
            status,
            created_at,
            started_at,
            completed_at,
            result,
            error
        FROM research_jobs
        WHERE id = $1
          AND user_id = $2
        """,
        job_id,
        user_id,
    )

    if row is None:
        return None

    result = row["result"]

    if isinstance(result, str):
        result = json.loads(result)

    return {
        "job_id": row["id"],
        "question": row["question"],
        "status": row["status"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "result": result,
        "error": row["error"],
    }
