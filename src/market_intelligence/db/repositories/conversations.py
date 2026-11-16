from typing import Any
from uuid import UUID

import asyncpg

CREATE_RESEARCH_CONVERSATIONS = """
CREATE TABLE IF NOT EXISTS research_conversations (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'New research',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE research_jobs
ADD COLUMN IF NOT EXISTS conversation_id UUID
REFERENCES research_conversations(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_research_conversations_user_updated
ON research_conversations(user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_jobs_conversation_created
ON research_jobs(conversation_id, created_at);
"""


async def initialize_research_conversations(
    pool: asyncpg.Pool,
) -> None:
    await pool.execute(CREATE_RESEARCH_CONVERSATIONS)


async def create_research_conversation(
    pool: asyncpg.Pool,
    conversation_id: UUID,
    user_id: UUID,
    title: str,
) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        INSERT INTO research_conversations (id, user_id, title)
        VALUES ($1, $2, $3)
        RETURNING id, user_id, title, created_at, updated_at
        """,
        conversation_id,
        user_id,
        title,
    )

    return dict(row)


async def touch_research_conversation(
    pool: asyncpg.Pool,
    conversation_id: UUID,
    user_id: UUID,
) -> None:
    await pool.execute(
        """
        UPDATE research_conversations
        SET updated_at = NOW()
        WHERE id = $1 AND user_id = $2
        """,
        conversation_id,
        user_id,
    )


async def get_research_conversation_for_user(
    pool: asyncpg.Pool,
    conversation_id: UUID,
    user_id: UUID,
) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        """
        SELECT
            c.id,
            c.title,
            c.created_at,
            c.updated_at,
            COUNT(j.id)::INTEGER AS job_count,
            MAX(j.created_at) AS last_message_at
        FROM research_conversations c
        LEFT JOIN research_jobs j
            ON j.conversation_id = c.id
            AND j.user_id = c.user_id
        WHERE c.id = $1 AND c.user_id = $2
        GROUP BY c.id
        """,
        conversation_id,
        user_id,
    )

    return dict(row) if row else None


async def list_research_conversations(
    pool: asyncpg.Pool,
    user_id: UUID,
) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT
            c.id,
            c.title,
            c.created_at,
            c.updated_at,
            COUNT(j.id)::INTEGER AS job_count,
            MAX(j.created_at) AS last_message_at
        FROM research_conversations c
        LEFT JOIN research_jobs j
            ON j.conversation_id = c.id
            AND j.user_id = c.user_id
        WHERE c.user_id = $1
        GROUP BY c.id
        ORDER BY COALESCE(MAX(j.created_at), c.updated_at) DESC
        """,
        user_id,
    )

    return [dict(row) for row in rows]


async def list_conversation_jobs(
    pool: asyncpg.Pool,
    conversation_id: UUID,
    user_id: UUID,
) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT
            id AS job_id,
            question,
            status,
            created_at,
            started_at,
            completed_at,
            result,
            error
        FROM research_jobs
        WHERE conversation_id = $1 AND user_id = $2
        ORDER BY created_at ASC
        """,
        conversation_id,
        user_id,
    )

    jobs = []

    for row in rows:
        job = dict(row)
        result = job["result"]

        if isinstance(result, str):
            import json

            result = json.loads(result)

        job["result"] = result
        jobs.append(job)

    return jobs
