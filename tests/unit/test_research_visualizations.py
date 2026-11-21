from market_intelligence.orchestration.visualizations import (
    build_research_visualizations,
)


def test_builds_monthly_sales_chart():
    internal_data = {
        "monthly_sales_analysis": {
            "monthly_trend": [
                {
                    "month": "2025-01",
                    "month_label": "Jan 2025",
                    "net_line_value": "1200.50",
                    "is_complete_month": True,
                    "mom_change_pct": "10.5",
                    "yoy_change_pct": None,
                },
                {
                    "month": "2025-02",
                    "month_label": "Feb 2025",
                    "net_line_value": "1500.00",
                    "is_complete_month": True,
                    "mom_change_pct": "25.0",
                    "yoy_change_pct": "15.0",
                },
            ],
        },
    }

    result = build_research_visualizations(internal_data)

    chart = next(
        chart
        for chart in result["charts"]
        if chart["id"] == "monthly-sales-trend"
    )

    assert chart["chart_type"] == "line"
    assert chart["series"][0]["data"][0]["y"] == 1200.50
    assert chart["series"][1:] == []


def test_builds_top_products_chart():
    internal_data = {
        "top_products": [
            {
                "stock_code": "A100",
                "description": "Product A",
                "net_line_value": "500.00",
                "positive_line_value_share_pct": "2.5",
            },
            {
                "stock_code": "B200",
                "description": "Product B",
                "net_line_value": "300.00",
                "positive_line_value_share_pct": "1.5",
            },
        ],
    }

    result = build_research_visualizations(internal_data)

    chart = next(
        chart
        for chart in result["charts"]
        if chart["id"] == "top-products"
    )

    assert chart["chart_type"] == "bar"
    assert len(chart["series"][0]["data"]) == 2
    assert chart["series"][0]["data"][0]["y"] == 500.0


def test_builds_seasonality_and_anomaly_charts():
    internal_data = {
        "monthly_sales_analysis": {
            "seasonality": [
                {
                    "calendar_month": "January",
                    "seasonal_index_pct": "110.5",
                    "months_observed": 3,
                }
            ],
            "anomaly_analysis": {
                "anomalies": [
                    {
                        "month_label": "Feb 2025",
                        "net_line_value": "2500.00",
                        "direction": "high",
                        "modified_z_score": "3.2",
                    }
                ]
            },
        }
    }

    result = build_research_visualizations(internal_data)

    chart_ids = {
        chart["id"]
        for chart in result["charts"]
    }

    assert "sales-seasonality" in chart_ids
    assert "monthly-sales-anomalies" in chart_ids


def test_handles_missing_analytics():
    result = build_research_visualizations({})

    assert result["schema_version"] == 1
    assert result["charts"] == []
    assert result["warnings"] == []


def test_omits_invalid_numeric_points():
    internal_data = {
        "top_products": [
            {
                "stock_code": "A100",
                "description": "Invalid product",
                "net_line_value": "not-a-number",
            }
        ]
    }

    result = build_research_visualizations(internal_data)

    assert result["charts"] == []
    assert len(result["warnings"]) == 1


def test_keeps_missing_growth_values_as_gaps():
    internal_data = {
        "monthly_sales_analysis": {
            "monthly_trend": [
                {
                    "month_label": "Jan 2025",
                    "mom_change_pct": None,
                    "yoy_change_pct": "12.5",
                }
            ]
        }
    }

    result = build_research_visualizations(internal_data)

    chart = next(
        chart
        for chart in result["charts"]
        if chart["id"] == "monthly-growth-trends"
    )

    assert chart["series"][0]["data"][0]["y"] is None
    assert chart["series"][1]["data"][0]["y"] == 12.5