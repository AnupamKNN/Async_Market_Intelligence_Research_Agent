"""Build deterministic chart specifications from research analytics."""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any

from market_intelligence.schemas.visualizations import (
    ChartDataPoint,
    ChartSeries,
    ResearchChart,
    ResearchVisualizations,
)


def _to_plot_number(value: Any) -> float | None:
    """Convert a numeric source value to a finite Plotly-compatible number."""

    if value is None:
        return None

    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None

    if not number.is_finite():
        return None

    converted = float(number)

    if not math.isfinite(converted):
        return None

    return converted


def _unwrap_result(value: Any) -> Any:
    """Unwrap an MCP result envelope when present."""

    if isinstance(value, dict) and set(value) == {"result"}:
        return value["result"]

    return value


def build_research_visualizations(
    internal_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Build validated chart specifications from retrieved analytics.

    The function does not calculate business metrics. It only converts
    already-retrieved analytical results into chart-ready data.
    """

    charts: list[ResearchChart] = []
    warnings: list[str] = []

    # ---------------------------------------------------------
    # 1. Monthly net sales trend
    # ---------------------------------------------------------

    monthly = _unwrap_result(
        internal_data.get("monthly_sales_analysis", {})
    )

    if not isinstance(monthly, dict):
        monthly = {}

    trend = monthly.get("monthly_trend", [])

    if isinstance(trend, list) and trend:
        points = []

        for item in trend:
            if not isinstance(item, dict):
                continue

            month = item.get("month_label") or item.get("month")
            value = _to_plot_number(item.get("net_line_value"))

            if not month or value is None:
                warnings.append(
                    "A monthly sales observation was omitted because "
                    "its label or numeric value was invalid."
                )
                continue

            points.append(
                ChartDataPoint(
                    x=str(month),
                    y=value,
                    metadata={
                        "is_complete_month": bool(
                            item.get("is_complete_month", False)
                        ),
                    },
                )
            )

        if points:
            charts.append(
                ResearchChart(
                    id="monthly-sales-trend",
                    title="Monthly Net Sales",
                    description=(
                        "Net line value includes positive transactions "
                        "and negative returns or adjustments. "
                        "Incomplete months are identified in point metadata."
                    ),
                    chart_type="line",
                    x_axis_title="Month",
                    y_axis_title="Net line value",
                    series=[
                        ChartSeries(
                            name="Net line value",
                            render_as="line",
                            data=points,
                        )
                    ],
                )
            )

    # ---------------------------------------------------------
    # 2. Monthly growth trends
    # ---------------------------------------------------------

    if isinstance(trend, list) and trend:
        mom_points = []
        yoy_points = []

        for item in trend:
            if not isinstance(item, dict):
                continue

            month = item.get("month_label") or item.get("month")

            if not month:
                continue

            mom_points.append(
                ChartDataPoint(
                    x=str(month),
                    y=_to_plot_number(item.get("mom_change_pct")),
                )
            )

            yoy_points.append(
                ChartDataPoint(
                    x=str(month),
                    y=_to_plot_number(item.get("yoy_change_pct")),
                )
            )

        has_growth_data = any(
            point.y is not None
            for point in mom_points + yoy_points
        )

        if has_growth_data:
            charts.append(
                ResearchChart(
                    id="monthly-growth-trends",
                    title="Monthly Sales Growth",
                    description=(
                        "Growth values are omitted when the source "
                        "does not have a valid comparison period."
                    ),
                    chart_type="line",
                    x_axis_title="Month",
                    y_axis_title="Growth (%)",
                    series=[
                        ChartSeries(
                            name="Month-over-month",
                            data=mom_points,
                        ),
                        ChartSeries(
                            name="Year-over-year",
                            data=yoy_points,
                        ),
                    ],
                )
            )

    # ---------------------------------------------------------
    # 3. Top products by net line value
    # ---------------------------------------------------------

    products = _unwrap_result(
        internal_data.get("top_products", [])
    )

    if isinstance(products, list) and products:
        product_points = []

        for product in products:
            if not isinstance(product, dict):
                continue

            value = _to_plot_number(
                product.get("net_line_value")
            )

            if value is None:
                warnings.append(
                    "A product was omitted because its net line value "
                    "was invalid."
                )
                continue

            stock_code = str(
                product.get("stock_code") or "Unknown"
            )

            description = str(
                product.get("description") or stock_code
            )

            label = f"{description} ({stock_code})"

            product_points.append(
                ChartDataPoint(
                    x=label[:200],
                    y=value,
                    metadata={
                        "stock_code": stock_code,
                        "positive_line_value_share_pct": (
                            _to_plot_number(
                                product.get(
                                    "positive_line_value_share_pct"
                                )
                            )
                        ),
                    },
                )
            )

        if product_points:
            charts.append(
                ResearchChart(
                    id="top-products",
                    title="Top Products by Net Sales Value",
                    description=(
                        "Displays only the products returned by the "
                        "top-products retrieval, not the entire catalog."
                    ),
                    chart_type="bar",
                    x_axis_title="Product",
                    y_axis_title="Net line value",
                    series=[
                        ChartSeries(
                            name="Net line value",
                            render_as="bar",
                            data=product_points,
                        )
                    ],
                )
            )

    # ---------------------------------------------------------
    # 4. Seasonal sales patterns
    # ---------------------------------------------------------

    seasonality = monthly.get("seasonality", [])

    if isinstance(seasonality, list) and seasonality:
        seasonal_points = []

        for item in seasonality:
            if not isinstance(item, dict):
                continue

            month = item.get("calendar_month")
            value = _to_plot_number(
                item.get("seasonal_index_pct")
            )

            if not month or value is None:
                continue

            seasonal_points.append(
                ChartDataPoint(
                    x=str(month),
                    y=value,
                    metadata={
                        "months_observed": int(
                            item.get("months_observed", 0)
                        ),
                    },
                )
            )

        if seasonal_points:
            charts.append(
                ResearchChart(
                    id="sales-seasonality",
                    title="Seasonal Sales Patterns",
                    description=(
                        "Seasonal index is expressed relative to the "
                        "average net line value of complete observed months."
                    ),
                    chart_type="bar",
                    x_axis_title="Calendar month",
                    y_axis_title="Seasonal index (%)",
                    series=[
                        ChartSeries(
                            name="Seasonal index",
                            render_as="bar",
                            data=seasonal_points,
                        )
                    ],
                )
            )

    # ---------------------------------------------------------
    # 5. Monthly sales anomalies
    # ---------------------------------------------------------

    anomaly_analysis = monthly.get(
        "anomaly_analysis",
        {},
    )

    if isinstance(anomaly_analysis, dict):
        anomalies = anomaly_analysis.get("anomalies", [])

        if isinstance(anomalies, list) and anomalies:
            anomaly_points = []

            for item in anomalies:
                if not isinstance(item, dict):
                    continue

                month = item.get("month_label")
                value = _to_plot_number(
                    item.get("net_line_value")
                )

                if not month or value is None:
                    continue

                anomaly_points.append(
                    ChartDataPoint(
                        x=str(month),
                        y=value,
                        metadata={
                            "direction": str(
                                item.get("direction", "unknown")
                            ),
                            "modified_z_score": (
                                _to_plot_number(
                                    item.get("modified_z_score")
                                )
                            ),
                        },
                    )
                )

            if anomaly_points:
                charts.append(
                    ResearchChart(
                        id="monthly-sales-anomalies",
                        title="Detected Monthly Sales Anomalies",
                        description=(
                            "Only months flagged by the backend's "
                            "deterministic anomaly detection are shown."
                        ),
                        chart_type="bar",
                        x_axis_title="Month",
                        y_axis_title="Net line value",
                        series=[
                            ChartSeries(
                                name="Detected anomalies",
                                render_as="bar",
                                data=anomaly_points,
                            )
                        ],
                    )
                )

    payload = ResearchVisualizations(
        charts=charts,
        warnings=warnings,
    )

    return payload.model_dump(mode="json")