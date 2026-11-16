import json
from typing import Any
from uuid import UUID

import asyncpg

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
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_jobs_created_at
ON research_jobs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_jobs_status
ON research_jobs (status);
"""


async def initialize_research_jobs(pool: asyncpg.Pool) -> None:
    await pool.execute(CREATE_RESEARCH_JOBS_TABLE)


async def create_research_job(
    pool: asyncpg.Pool,
    job_id: UUID,
    payload: dict[str, Any],
    user_id: UUID,
    conversation_id: UUID | None = None,
) -> None:
    await pool.execute(
        """
        INSERT INTO research_jobs (
            id,
            user_id,
            conversation_id,
            question,
            request_payload,
            status
        )
        VALUES ($1, $2, $3, $4, $5::jsonb, 'queued')
        """,
        job_id,
        user_id,
        conversation_id,
        payload["question"],
        json.dumps(payload),
    )


async def mark_job_running(pool: asyncpg.Pool, job_id: UUID) -> None:
    await pool.execute(
        """
        UPDATE research_jobs
        SET status = 'running', started_at = NOW(), error = NULL
        WHERE id = $1 AND status = 'queued'
        """,
        job_id,
    )


async def complete_research_job(
    pool: asyncpg.Pool,
    job_id: UUID,
    result: dict[str, Any],
) -> None:
    await pool.execute(
        """
        UPDATE research_jobs
        SET status = 'completed',
            result = $2::jsonb,
            completed_at = NOW()
        WHERE id = $1
        """,
        job_id,
        json.dumps(result, default=str),
    )


async def fail_research_job(
    pool: asyncpg.Pool,
    job_id: UUID,
    error: str,
) -> None:
    await pool.execute(
        """
        UPDATE research_jobs
        SET status = 'failed',
            error = $2,
            completed_at = NOW()
        WHERE id = $1
        """,
        job_id,
        error[:2000],
    )


async def get_research_job(
    pool: asyncpg.Pool,
    job_id: UUID,
) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        """
        SELECT id, question, status, created_at, started_at,
               completed_at, result, error
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
    }


async def get_research_job_for_user(
    pool: asyncpg.Pool,
    job_id: UUID,
    user_id: UUID,
) -> dict[str, Any] | None:
    """Retrieve a research job only when it belongs to the specified user."""

    row = await pool.fetchrow(
        """
        SELECT id, question, status, created_at, started_at,
               completed_at, result, error
        FROM research_jobs
        WHERE id = $1 AND user_id = $2
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
