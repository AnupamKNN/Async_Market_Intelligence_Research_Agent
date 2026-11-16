"""Internal Analytics MCP server.

Exposes controlled, read-only analytical tools over PostgreSQL.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from statistics import median
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


def _next_month_start(value: date) -> date:
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


def _previous_month_start(value: date) -> date:
    return (value - timedelta(days=1)).replace(day=1)


def _month_end(value: date) -> date:
    return date(
        value.year,
        value.month,
        monthrange(value.year, value.month)[1],
    )


def _to_decimal(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else "0"))


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _growth_percentage(
    current: Decimal,
    previous: Decimal | None,
) -> str | None:
    if previous is None or previous <= 0:
        return None

    return _decimal_text((current - previous) / previous * Decimal("100"))


def _percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
    """Calculate an interpolated percentile from sorted numeric values."""

    position = Decimal(len(values) - 1) * fraction
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(values) - 1)
    weight = position - lower_index

    return values[lower_index] * (Decimal("1") - weight) + values[upper_index] * weight


def _detect_monthly_anomalies(
    months: list[dict[str, Any]],
) -> dict[str, Any]:
    """Detect unusual monthly net sales using robust statistical thresholds."""

    values = sorted(_to_decimal(item["net_line_value"]) for item in months)

    if len(values) < 6:
        return {
            "status": "insufficient_history",
            "method": None,
            "months_evaluated": len(values),
            "anomalies": [],
            "note": "At least six complete months are required.",
        }

    center = median(values)
    deviations = sorted(abs(value - center) for value in values)
    mad = median(deviations)

    anomalies: list[dict[str, Any]] = []

    if mad > 0:
        method = "modified_z_score_mad"
        threshold = Decimal("3.5")

        for item in months:
            value = _to_decimal(item["net_line_value"])
            score = Decimal("0.6745") * (value - center) / mad

            if abs(score) >= threshold:
                anomalies.append(
                    {
                        "month": item["month"],
                        "month_label": item["month_label"],
                        "net_line_value": item["net_line_value"],
                        "direction": "high" if score > 0 else "low",
                        "modified_z_score": _decimal_text(score),
                    }
                )

    else:
        # Fallback for datasets where the median absolute deviation is zero.
        q1 = _percentile(values, Decimal("0.25"))
        q3 = _percentile(values, Decimal("0.75"))
        iqr = q3 - q1

        if iqr <= 0:
            return {
                "status": "not_detectable",
                "method": "iqr_fallback",
                "months_evaluated": len(values),
                "anomalies": [],
                "note": "There is insufficient dispersion to establish outlier bounds.",
            }

        method = "iqr_fallback"
        lower_bound = q1 - Decimal("1.5") * iqr
        upper_bound = q3 + Decimal("1.5") * iqr

        for item in months:
            value = _to_decimal(item["net_line_value"])

            if value < lower_bound or value > upper_bound:
                anomalies.append(
                    {
                        "month": item["month"],
                        "month_label": item["month_label"],
                        "net_line_value": item["net_line_value"],
                        "direction": "low" if value < lower_bound else "high",
                        "modified_z_score": None,
                    }
                )

    return {
        "status": "evaluated",
        "method": method,
        "months_evaluated": len(values),
        "median_net_line_value": _decimal_text(center),
        "mad": _decimal_text(mad),
        "anomalies": anomalies,
        "note": ("Anomalies are based on monthly net line values and are not seasonally adjusted."),
    }


def _build_monthly_sales_analysis(
    monthly_rows: list[Any],
    min_date: date,
    max_date: date,
    selected_start: date,
    selected_end: date,
) -> dict[str, Any]:
    """Build deterministic monthly trends, seasonality and anomaly results."""

    first_full_month = min_date.replace(day=1)
    if min_date.day > 1:
        first_full_month = _next_month_start(first_full_month)

    last_full_month = max_date.replace(day=1)
    if max_date.day < monthrange(max_date.year, max_date.month)[1]:
        last_full_month = _previous_month_start(last_full_month)

    first_selected_month = selected_start.replace(day=1)
    last_selected_month = selected_end.replace(day=1)

    records: dict[date, dict[str, Any]] = {}

    for row in monthly_rows:
        month_start = row["month_start"]

        if isinstance(month_start, datetime):
            month_start = month_start.date()

        source_complete = first_full_month <= month_start <= last_full_month
        selected_month = first_selected_month <= month_start <= last_selected_month
        selected_complete = selected_start <= month_start and selected_end >= _month_end(
            month_start
        )

        records[month_start] = {
            "month": month_start.strftime("%Y-%m"),
            "month_label": month_start.strftime("%b %Y"),
            "transaction_lines": int(row["transaction_lines"]),
            "unique_invoices": int(row["unique_invoices"]),
            "net_quantity": int(row["net_quantity"]),
            "positive_line_value": _decimal_text(_to_decimal(row["positive_line_value"])),
            "negative_adjustment_value": _decimal_text(
                _to_decimal(row["negative_adjustment_value"])
            ),
            "net_line_value": _decimal_text(_to_decimal(row["net_line_value"])),
            "is_complete_month": (source_complete and (not selected_month or selected_complete)),
        }

    monthly_trend: list[dict[str, Any]] = []
    complete_selected_months: list[dict[str, Any]] = []

    for month_start in sorted(records):
        current = records[month_start]

        if not first_selected_month <= month_start <= last_selected_month:
            continue

        current_value = _to_decimal(current["net_line_value"])

        previous_month = _previous_month_start(month_start)
        previous_year = date(month_start.year - 1, month_start.month, 1)

        previous_record = records.get(previous_month)
        previous_year_record = records.get(previous_year)

        mom_change = None
        yoy_change = None

        if current["is_complete_month"] and previous_record:
            if previous_record["is_complete_month"]:
                mom_change = _growth_percentage(
                    current_value,
                    _to_decimal(previous_record["net_line_value"]),
                )

        if current["is_complete_month"] and previous_year_record:
            if previous_year_record["is_complete_month"]:
                yoy_change = _growth_percentage(
                    current_value,
                    _to_decimal(previous_year_record["net_line_value"]),
                )

        result = {
            **current,
            "mom_change_pct": mom_change,
            "yoy_change_pct": yoy_change,
        }

        monthly_trend.append(result)

        if current["is_complete_month"]:
            complete_selected_months.append(result)

    # Calendar-month seasonality, using complete observed months only.
    overall_average = (
        sum(_to_decimal(item["net_line_value"]) for item in complete_selected_months)
        / len(complete_selected_months)
        if complete_selected_months
        else Decimal("0")
    )

    seasonality: list[dict[str, Any]] = []

    for calendar_month in range(1, 13):
        observations = [
            item for item in complete_selected_months if int(item["month"][5:7]) == calendar_month
        ]

        if not observations:
            continue

        average_value = sum(_to_decimal(item["net_line_value"]) for item in observations) / len(
            observations
        )

        seasonal_index = (
            average_value / overall_average * Decimal("100") if overall_average > 0 else None
        )

        seasonality.append(
            {
                "calendar_month": date(2000, calendar_month, 1).strftime("%B"),
                "average_net_line_value": _decimal_text(average_value),
                "seasonal_index_pct": (
                    _decimal_text(seasonal_index) if seasonal_index is not None else None
                ),
                "months_observed": len(observations),
                "years_observed": sorted({int(item["month"][:4]) for item in observations}),
            }
        )

    anomaly_analysis = _detect_monthly_anomalies(complete_selected_months)

    return {
        "start_date": selected_start.isoformat(),
        "end_date": selected_end.isoformat(),
        "monthly_trend": monthly_trend,
        "seasonality": seasonality,
        "anomaly_analysis": anomaly_analysis,
        "limitations": [
            "Growth percentages are suppressed when either comparison month "
            "is incomplete or the previous period has a non-positive net value.",
            "Seasonality and anomaly analysis use complete months only.",
            "Anomaly detection uses monthly net line values and is not seasonally adjusted.",
        ],
    }


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
        WITH filtered AS (
            SELECT
                stock_code,
                description,
                invoice_no,
                quantity,
                line_total
            FROM analytics.retail_transactions
            WHERE ($1::DATE IS NULL OR invoice_date >= $1::DATE)
              AND ($2::DATE IS NULL OR invoice_date < ($2::DATE + 1))
        ),
        product_totals AS (
            SELECT
                COALESCE(
                    SUM(line_total) FILTER (WHERE line_total > 0),
                    0
                ) AS total_positive_line_value
            FROM filtered
        ),
        product_summary AS (
            SELECT
                stock_code,
                mode() WITHIN GROUP (ORDER BY description)
                    FILTER (WHERE description IS NOT NULL) AS description,
                COUNT(*)::BIGINT AS transaction_lines,
                COALESCE(SUM(quantity), 0)::BIGINT AS net_quantity,
                COALESCE(SUM(line_total), 0) AS net_line_value,
                COALESCE(
                    SUM(line_total) FILTER (WHERE line_total > 0),
                    0
                ) AS positive_line_value,
                COALESCE(
                    SUM(line_total) FILTER (WHERE line_total < 0),
                    0
                ) AS negative_adjustment_value
            FROM filtered
            GROUP BY stock_code
        )
        SELECT
            p.stock_code,
            p.description,
            p.transaction_lines,
            p.net_quantity,
            p.net_line_value::TEXT AS net_line_value,
            p.positive_line_value::TEXT AS positive_line_value,
            p.negative_adjustment_value::TEXT AS negative_adjustment_value,
            t.total_positive_line_value::TEXT AS total_positive_line_value,
            ROUND(
                p.positive_line_value
                / NULLIF(t.total_positive_line_value, 0) * 100,
                4
            )::TEXT AS positive_line_value_share_pct
        FROM product_summary p
        CROSS JOIN product_totals t
        ORDER BY p.net_line_value DESC, p.stock_code
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


@mcp.tool
async def get_monthly_sales_analysis(
    ctx: Context,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Return monthly trends, MoM/YoY growth, seasonality and anomalies."""

    validate_date_range(start_date, end_date)
    pool = get_pool(ctx)

    async with pool.acquire() as connection:
        bounds = await connection.fetchrow(
            """
            SELECT
                MIN(invoice_date)::DATE AS min_invoice_date,
                MAX(invoice_date)::DATE AS max_invoice_date
            FROM analytics.retail_transactions
            """
        )

        if (
            bounds is None
            or bounds["min_invoice_date"] is None
            or bounds["max_invoice_date"] is None
        ):
            return {
                "start_date": None,
                "end_date": None,
                "monthly_trend": [],
                "seasonality": [],
                "anomaly_analysis": {
                    "status": "insufficient_history",
                    "method": None,
                    "months_evaluated": 0,
                    "anomalies": [],
                    "note": "The dataset contains no transaction dates.",
                },
                "limitations": ["No transaction dates are available."],
            }

        min_date = bounds["min_invoice_date"]
        max_date = bounds["max_invoice_date"]

        selected_start = max(start_date or min_date, min_date)
        selected_end = min(end_date or max_date, max_date)

        if selected_start > selected_end:
            raise ValueError("The requested date range does not overlap the dataset.")

        first_month = selected_start.replace(day=1)

        # Retain 12 months of history for YoY comparisons.
        history_start = date(
            first_month.year - 1,
            first_month.month,
            1,
        )
        history_start = max(history_start, min_date)

        query = """
            SELECT
                date_trunc('month', invoice_date)::DATE AS month_start,
                COUNT(*)::BIGINT AS transaction_lines,
                COUNT(DISTINCT invoice_no)::BIGINT AS unique_invoices,
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
            WHERE invoice_date >= $1::DATE
              AND invoice_date < ($3::DATE + 1)
              AND (
                    invoice_date < date_trunc('month', $2::DATE)::DATE
                    OR invoice_date >= $2::DATE
              )
            GROUP BY 1
            ORDER BY 1
        """

        rows = await connection.fetch(
            query,
            history_start,
            selected_start,
            selected_end,
        )

    return _build_monthly_sales_analysis(
        monthly_rows=rows,
        min_date=min_date,
        max_date=max_date,
        selected_start=selected_start,
        selected_end=selected_end,
    )


def main() -> None:
    """Run the Internal Analytics MCP server over stdio."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
