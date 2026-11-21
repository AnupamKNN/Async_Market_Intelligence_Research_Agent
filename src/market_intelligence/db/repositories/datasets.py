"""Database operations for user-managed datasets."""

import asyncpg

CREATE_DATASET_TABLES = """
CREATE TABLE IF NOT EXISTS datasets (
    id UUID PRIMARY KEY,

    user_id UUID NOT NULL
        REFERENCES users(id) ON DELETE CASCADE,

    name TEXT NOT NULL,
    original_filename TEXT NOT NULL,

    storage_key TEXT NOT NULL UNIQUE,

    file_format TEXT NOT NULL
        CHECK (file_format IN ('csv', 'xlsx')),

    mime_type TEXT NOT NULL,

    file_size_bytes BIGINT NOT NULL
        CHECK (file_size_bytes > 0),

    checksum_sha256 CHAR(64) NOT NULL,

    status TEXT NOT NULL DEFAULT 'uploaded'
        CHECK (
            status IN (
                'uploaded',
                'validating',
                'ingesting',
                'ready',
                'failed'
            )
        ),

    row_count BIGINT
        CHECK (row_count IS NULL OR row_count >= 0),

    column_count INTEGER
        CHECK (column_count IS NULL OR column_count >= 0),

    schema_metadata JSONB NOT NULL DEFAULT '{}'::JSONB,

    error_message TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_datasets_user_created
    ON datasets (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_datasets_user_status
    ON datasets (user_id, status);


CREATE TABLE IF NOT EXISTS dataset_columns (
    id UUID PRIMARY KEY,

    dataset_id UUID NOT NULL
        REFERENCES datasets(id) ON DELETE CASCADE,

    ordinal_position INTEGER NOT NULL
        CHECK (ordinal_position >= 0),

    column_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    inferred_type TEXT NOT NULL,

    null_count BIGINT
        CHECK (null_count IS NULL OR null_count >= 0),

    distinct_count BIGINT
        CHECK (distinct_count IS NULL OR distinct_count >= 0),

    column_metadata JSONB NOT NULL DEFAULT '{}'::JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (dataset_id, normalized_name),
    UNIQUE (dataset_id, ordinal_position)
);

CREATE INDEX IF NOT EXISTS idx_dataset_columns_dataset
    ON dataset_columns (dataset_id, ordinal_position);
"""


async def initialize_dataset_tables(
    pool: asyncpg.Pool,
) -> None:
    """Initialize dataset registry and column metadata tables."""

    await pool.execute(CREATE_DATASET_TABLES)