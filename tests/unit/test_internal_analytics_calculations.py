from datetime import date

from market_intelligence.mcp.internal_analytics.server import (
    _build_monthly_sales_analysis,
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
