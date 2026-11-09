"""Internal Analytics MCP server.

Exposes controlled, read-only analytical tools over PostgreSQL.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, cast

import asyncpg
from fastmcp import Context, FastMCP

from market_intelligence.core.config import Settings
from market_intelligence.db.pool import create_database_pool


@asynccontextmanager
async def app_lifespan(
    _server: FastMCP,
) -> AsyncIterator[dict[str, Any]]:
    """Create shared resources at startup and release them at shutdown."""

    settings = Settings()
    pool = await create_database_pool(settings)

    try:
        async with pool.acquire() as connection:
            await connection.fetchval("SELECT 1")

        yield {
            "pool": pool,
            "settings": settings,
        }
    finally:
        await pool.close()


mcp = FastMCP(
    name="Market Intelligence Internal Analytics",
    lifespan=app_lifespan,
    instructions=(
        "Provides controlled analytical access to the internal retail "
        "transactions dataset. Use these tools for calculations over "
        "the local PostgreSQL dataset. Do not assume correlation implies causation."
    ),
)


def get_pool(ctx: Context) -> asyncpg.Pool:
    """Retrieve the application-wide pool from the MCP lifespan context."""

    return cast(asyncpg.Pool, ctx.lifespan_context["pool"])


def validate_date_range(
    start_date: date | None,
    end_date: date | None,
) -> None:
    """Validate optional inclusive date boundaries."""

    if start_date is not None and end_date is not None:
        if start_date > end_date:
            raise ValueError("start_date cannot be later than end_date")


@mcp.tool
async def database_health(ctx: Context) -> dict[str, str | int]:
    """Check PostgreSQL connectivity and report database server information."""

    pool = get_pool(ctx)

    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT
                current_database() AS database,
                current_user AS database_user,
                inet_server_port() AS port,
                current_setting('server_version') AS postgres_version
            """
        )

    if row is None:
        raise RuntimeError("PostgreSQL health check returned no result.")

    return {
        "status": "healthy",
        "database": row["database"],
        "database_user": row["database_user"],
        "port": row["port"],
        "postgres_version": row["postgres_version"],
    }


@mcp.tool
async def get_dataset_overview(ctx: Context) -> dict[str, Any]:
    """Return core record counts, data-quality indicators, and date coverage."""

    pool = get_pool(ctx)

    query = """
        SELECT
            COUNT(*)::BIGINT AS total_records,
            COUNT(DISTINCT invoice_no)::BIGINT AS unique_invoices,
            COUNT(DISTINCT stock_code)::BIGINT AS unique_products,
            COUNT(DISTINCT customer_id)::BIGINT AS unique_customers,
            COUNT(DISTINCT country)::BIGINT AS unique_countries,
            COUNT(*) FILTER (
                WHERE customer_id IS NULL
            )::BIGINT AS missing_customer_ids,
            COUNT(*) FILTER (
                WHERE quantity < 0
            )::BIGINT AS negative_quantity_rows,
            COUNT(*) FILTER (
                WHERE unit_price < 0
            )::BIGINT AS negative_price_rows,
            COALESCE(SUM(line_total), 0)::TEXT AS total_line_value,
            MIN(invoice_date) AS first_transaction,
            MAX(invoice_date) AS last_transaction
        FROM analytics.retail_transactions
    """

    async with pool.acquire() as connection:
        row = await connection.fetchrow(query)

    if row is None:
        raise RuntimeError("Dataset overview query returned no result.")

    result = dict(row)

    for field in ("first_transaction", "last_transaction"):
        value = result[field]
        result[field] = value.isoformat(sep=" ") if value else None

    return result


@mcp.tool
async def get_sales_summary(
    ctx: Context,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Calculate line-value metrics for an optional inclusive date range.

    Positive line values represent positive transaction lines.
    Negative line values represent returns or other negative adjustments.
    Net line value includes both. These are dataset calculations, not
    independently verified accounting revenue.
    """

    validate_date_range(start_date, end_date)
    pool = get_pool(ctx)

    query = """
        SELECT
            COUNT(*)::BIGINT AS transaction_lines,
            COALESCE(SUM(quantity), 0)::BIGINT AS net_quantity,
            COALESCE(
                SUM(line_total) FILTER (WHERE line_total > 0),
                0
            )::TEXT AS positive_line_value,
            COALESCE(
                SUM(line_total) FILTER (WHERE line_total < 0),
                0
            )::TEXT AS negative_adjustment_value,
            COALESCE(SUM(line_total), 0)::TEXT AS net_line_value
        FROM analytics.retail_transactions
        WHERE ($1::DATE IS NULL OR invoice_date >= $1::DATE)
          AND ($2::DATE IS NULL OR invoice_date < ($2::DATE + 1))
    """

    async with pool.acquire() as connection:
        row = await connection.fetchrow(query, start_date, end_date)

    if row is None:
        raise RuntimeError("Sales summary query returned no result.")

    return {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        **dict(row),
    }


@mcp.tool
async def get_top_products(
    ctx: Context,
    limit: int = 10,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """Rank products by net line value, optionally restricted by date.

    The limit is restricted to 1–50. Net line value includes negative
    return and adjustment lines.
    """

    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50.")

    validate_date_range(start_date, end_date)
    pool = get_pool(ctx)

    query = """
        SELECT
            stock_code,
            mode() WITHIN GROUP (ORDER BY description)
                FILTER (WHERE description IS NOT NULL) AS description,
            COUNT(*)::BIGINT AS transaction_lines,
            SUM(quantity)::BIGINT AS net_quantity,
            COALESCE(SUM(line_total), 0)::TEXT AS net_line_value,
            COALESCE(
                SUM(line_total) FILTER (WHERE line_total > 0),
                0
            )::TEXT AS positive_line_value,
            COALESCE(
                SUM(line_total) FILTER (WHERE line_total < 0),
                0
            )::TEXT AS negative_adjustment_value
        FROM analytics.retail_transactions
        WHERE ($1::DATE IS NULL OR invoice_date >= $1::DATE)
          AND ($2::DATE IS NULL OR invoice_date < ($2::DATE + 1))
        GROUP BY stock_code
        ORDER BY SUM(line_total) DESC, stock_code
        LIMIT $3
    """

    async with pool.acquire() as connection:
        rows = await connection.fetch(
            query,
            start_date,
            end_date,
            limit,
        )

    return [dict(row) for row in rows]


def main() -> None:
    """Run the Internal Analytics MCP server over stdio."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
