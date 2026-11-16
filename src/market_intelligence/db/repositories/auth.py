"""Database operations for user authentication and sessions."""

from uuid import UUID

import asyncpg

CREATE_AUTH_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL,
    display_name TEXT NOT NULL,
    password_hash TEXT,
    email_verified_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower
ON users (LOWER(email));

CREATE TABLE IF NOT EXISTS auth_identities (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('google')),
    provider_subject TEXT NOT NULL,
    provider_email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, provider_subject)
);

CREATE INDEX IF NOT EXISTS idx_auth_identities_user_id
ON auth_identities(user_id);

CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    csrf_token_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id
ON user_sessions(user_id);

CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at
ON user_sessions(expires_at);

ALTER TABLE research_jobs
ADD COLUMN IF NOT EXISTS user_id UUID
REFERENCES users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_research_jobs_user_created_at
ON research_jobs(user_id, created_at DESC);
"""


async def initialize_auth_tables(pool: asyncpg.Pool) -> None:
    await pool.execute(CREATE_AUTH_TABLES)


async def create_email_user(
    pool: asyncpg.Pool,
    user_id: UUID,
    email: str,
    display_name: str,
    password_hash: str,
) -> asyncpg.Record:
    return await pool.fetchrow(
        """
        INSERT INTO users (id, email, display_name, password_hash)
        VALUES ($1, $2, $3, $4)
        RETURNING id, email, display_name, email_verified_at,
                  is_active, created_at
        """,
        user_id,
        email.lower(),
        display_name,
        password_hash,
    )


async def get_user_by_email(
    pool: asyncpg.Pool,
    email: str,
) -> asyncpg.Record | None:
    return await pool.fetchrow(
        """
        SELECT id, email, display_name, password_hash,
               email_verified_at, is_active, created_at
        FROM users
        WHERE LOWER(email) = $1
        """,
        email.lower(),
    )


async def create_user_session(
    pool: asyncpg.Pool,
    session_id: UUID,
    user_id: UUID,
    token_hash: str,
    csrf_token_hash: str,
    ttl_hours: int,
) -> None:
    await pool.execute(
        """
        INSERT INTO user_sessions (
            id, user_id, token_hash, csrf_token_hash, expires_at
        )
        VALUES (
            $1, $2, $3, $4,
            NOW() + make_interval(hours => $5)
        )
        """,
        session_id,
        user_id,
        token_hash,
        csrf_token_hash,
        ttl_hours,
    )


async def get_active_session(
    pool: asyncpg.Pool,
    token_hash: str,
) -> asyncpg.Record | None:
    return await pool.fetchrow(
        """
        SELECT
            s.id AS session_id,
            s.user_id,
            s.csrf_token_hash,
            u.email,
            u.display_name,
            u.email_verified_at,
            u.created_at AS user_created_at
        FROM user_sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = $1
          AND s.revoked_at IS NULL
          AND s.expires_at > NOW()
          AND u.is_active = TRUE
        """,
        token_hash,
    )


async def update_session_csrf(
    pool: asyncpg.Pool,
    session_id: UUID,
    csrf_token_hash: str,
) -> None:
    await pool.execute(
        """
        UPDATE user_sessions
        SET csrf_token_hash = $2, last_seen_at = NOW()
        WHERE id = $1 AND revoked_at IS NULL
        """,
        session_id,
        csrf_token_hash,
    )


async def revoke_user_session(
    pool: asyncpg.Pool,
    session_id: UUID,
) -> None:
    await pool.execute(
        """
        UPDATE user_sessions
        SET revoked_at = NOW()
        WHERE id = $1 AND revoked_at IS NULL
        """,
        session_id,
    )
