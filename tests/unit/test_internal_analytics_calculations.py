from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from market_intelligence.core.config import Settings
from market_intelligence.mcp.internal_analytics import server as analytics_server
from market_intelligence.mcp.internal_analytics.server import (
    _build_monthly_sales_analysis,
    get_top_products,
)


def make_month(year: int, month: int, value: int):
    return {
        "month_start": date(year, month, 1),
        "transaction_lines": 100,
        "unique_invoices": 50,
        "net_quantity": 100,
        "positive_line_value": str(value),
        "negative_adjustment_value": "0",
        "net_line_value": str(value),
    }


def test_monthly_growth_seasonality_and_anomaly_detection():
    rows = []

    for month in range(1, 13):
        rows.append(make_month(2023, month, 100 + month * 2))

    for month in range(1, 7):
        value = 100 + month * 2 + 10

        if month == 6:
            value = 10000

        rows.append(make_month(2024, month, value))

    result = _build_monthly_sales_analysis(
        monthly_rows=rows,
        min_date=date(2023, 1, 1),
        max_date=date(2024, 6, 30),
        selected_start=date(2023, 1, 1),
        selected_end=date(2024, 6, 30),
    )

    trend = {item["month"]: item for item in result["monthly_trend"]}

    assert trend["2024-01"]["yoy_change_pct"] == "9.80"
    assert trend["2024-02"]["mom_change_pct"] == "1.79"
    assert trend["2024-02"]["yoy_change_pct"] == "9.62"

    january = next(item for item in result["seasonality"] if item["calendar_month"] == "January")
    assert january["months_observed"] == 2

    anomalies = result["anomaly_analysis"]["anomalies"]
    assert any(item["month"] == "2024-06" for item in anomalies)


def test_partial_month_is_excluded_from_growth_seasonality_and_anomalies():
    rows = [make_month(2023, month, 100 + month * 2) for month in range(1, 13)]

    rows.extend(make_month(2024, month, 110 + month * 2) for month in range(1, 7))

    result = _build_monthly_sales_analysis(
        monthly_rows=rows,
        min_date=date(2023, 1, 1),
        max_date=date(2024, 6, 30),
        selected_start=date(2024, 1, 1),
        selected_end=date(2024, 6, 15),
    )

    june = next(item for item in result["monthly_trend"] if item["month"] == "2024-06")

    assert june["is_complete_month"] is False
    assert june["mom_change_pct"] is None
    assert june["yoy_change_pct"] is None
    assert all(item["calendar_month"] != "June" for item in result["seasonality"])


async def test_get_top_products_accepts_dynamic_limit(monkeypatch):
    connection = SimpleNamespace(fetch=AsyncMock(return_value=[{"stock_code": "P001"}]))

    @asynccontextmanager
    async def acquire_connection():
        yield connection

    pool = SimpleNamespace(acquire=acquire_connection)

    monkeypatch.setattr(
        analytics_server,
        "get_pool",
        lambda _ctx: pool,
    )

    ctx = SimpleNamespace(
        lifespan_context={
            "settings": Settings(),
        }
    )

    result = await get_top_products(ctx, limit=200)

    assert result == [{"stock_code": "P001"}]

    fetch_arguments = connection.fetch.await_args.args

    assert "LIMIT $3" in fetch_arguments[0]
    assert fetch_arguments[3] == 200


@pytest.mark.parametrize("limit", [0, -1, 101])
async def test_get_top_products_rejects_invalid_limits(limit):
    ctx = SimpleNamespace(
        lifespan_context={
            "settings": Settings(
                analytics_max_result_rows=100,
            ),
        }
    )

    with pytest.raises(ValueError, match="between 1 and 100"):
        await get_top_products(ctx, limit=limit)
