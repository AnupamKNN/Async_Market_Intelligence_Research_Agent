"""Execution tests for the compiled market research graph."""

import asyncio

from langchain_core.tools import StructuredTool

from market_intelligence.orchestration.graph import build_research_graph


def build_mock_tools(news_responses=None, news_queries=None):
    calls_started = set()
    both_started = asyncio.Event()
    pending_news_responses = list(news_responses or [])
    captured_news_queries = news_queries if news_queries is not None else []

    async def wait_for_parallel_peer(name: str) -> None:
        calls_started.add(name)

        if len(calls_started) == 3:
            both_started.set()

        await asyncio.wait_for(both_started.wait(), timeout=2)

    async def database_health():
        return {"status": "healthy"}

    async def dataset_overview():
        return {
            "total_records": 1044848,
            "unique_invoices": 53628,
            "unique_products": 5304,
            "unique_customers": 5942,
            "unique_countries": 43,
            "first_transaction": "2009-12-01",
            "last_transaction": "2011-12-09",
        }

    async def sales_summary(start_date: str, end_date: str):
        await wait_for_parallel_peer("sales")
        return {
            "positive_line_value": "1000.00",
            "negative_adjustment_value": "-100.00",
            "net_line_value": "900.00",
            "transaction_lines": 100,
        }

    async def top_products(limit: int, start_date: str, end_date: str):
        await wait_for_parallel_peer("products")
        return [
            {
                "stock_code": "22423",
                "description": "Product A",
                "net_line_value": "100.00",
                "positive_line_value": "100.00",
                "negative_adjustment_value": "0.00",
                "total_positive_line_value": "1000.00",
                "positive_line_value_share_pct": "10.00",
            }
        ][:limit]

    async def monthly_sales_analysis(start_date: str, end_date: str):
        await wait_for_parallel_peer("monthly")
        return {
            "start_date": start_date,
            "end_date": end_date,
            "monthly_trend": [
                {
                    "month": "2011-01",
                    "month_label": "Jan 2011",
                    "net_line_value": "900.00",
                    "mom_change_pct": "10.00",
                    "yoy_change_pct": "20.00",
                    "is_complete_month": True,
                }
            ],
            "seasonality": [
                {
                    "calendar_month": "January",
                    "average_net_line_value": "900.00",
                    "seasonal_index_pct": "100.00",
                    "months_observed": 2,
                }
            ],
            "anomaly_analysis": {
                "status": "evaluated",
                "method": "modified_z_score_mad",
                "months_evaluated": 12,
                "anomalies": [],
                "note": "No outliers detected.",
            },
            "limitations": [],
        }

    async def fred_observations(
        series_id: str,
        observation_start: str,
        observation_end: str,
        limit: int,
        sort_order: str,
        units: str,
    ):
        return {"observations": []}

    async def market_news(
        query: str,
        lang: str,
        max_articles: int,
        sort_by: str,
    ):
        captured_news_queries.append(query)

        if pending_news_responses:
            response = pending_news_responses.pop(0)
            return {**response, "query": query}

        return {
            "provider": "GNews",
            "query": query,
            "retrieved_at_utc": "2026-11-10T10:00:00+00:00",
            "articles": [],
        }

    definitions = [
        ("analytics__database_health", database_health),
        ("analytics__get_dataset_overview", dataset_overview),
        ("analytics__get_sales_summary", sales_summary),
        ("analytics__get_top_products", top_products),
        ("analytics__get_monthly_sales_analysis", monthly_sales_analysis),
        ("research__get_fred_series_observations", fred_observations),
        ("research__search_market_news", market_news),
    ]

    return [
        StructuredTool.from_function(
            coroutine=function,
            name=name,
            description=f"Mock tool: {name}",
        )
        for name, function in definitions
    ], calls_started


def make_gnews_response(
    *,
    title: str,
    description: str,
    url: str,
):
    return {
        "provider": "GNews",
        "retrieved_at_utc": "2026-11-10T10:00:00+00:00",
        "total_articles_available": 1,
        "articles": [
            {
                "title": title,
                "description": description,
                "url": url,
                "published_at": "2010-06-15T09:00:00Z",
                "publisher": "Example Research Journal",
                "publisher_url": "https://example.com",
            }
        ],
    }


async def test_internal_research_graph_execution():
    tools, calls_started = build_mock_tools()
    graph = build_research_graph(tools)

    result = await graph.ainvoke(
        {
            "question": ("Analyze retail sales performance and identify the top products."),
            "requested_sources": ["internal"],
            "product_limit": 5,
        }
    )

    from collections import Counter

    print("\nPLANNED NEWS QUERY:", result.get("planned_news_query"))
    print("PLANNED FRED SERIES:", result.get("planned_fred_series"))

    print(
        "EVIDENCE BY PROVIDER:",
        Counter(item.get("provider") for item in result.get("external_evidence", [])),
    )

    print(
        "RETRIEVAL DIAGNOSTICS:",
        {
            key: value
            for key, value in result.items()
            if any(term in key.lower() for term in ("error", "failure"))
        },
    )

    # Both internal analytics tools must execute concurrently.
    assert calls_started == {"sales", "products", "monthly"}

    # Retrieval results.
    assert result["retrieval_mode"] == "internal_only"
    assert result["internal_data"]["sales_summary"]["net_line_value"] == "900.00"
    assert result["internal_data"]["top_products"][0]["description"] == "Product A"

    # Deterministic reconciliation.
    assert result["quantitative_analysis"]["status"] == "validated"
    assert result["quantitative_analysis"]["reconciliation_passed"] is True
    assert result["quantitative_analysis"]["reconciliation_difference"] == "0.00"

    # Final report.
    assert result["synthesis_mode"] == "deterministic"
    assert "Product A" in result["report"]
    assert "900.00" in result["report"]
    assert result["errors"] == []

    assert result["internal_data"]["monthly_sales_analysis"]["monthly_trend"]
    assert "Monthly sales trends" in result["report"]
    assert "Seasonal sales patterns" in result["report"]
    assert "10.00%" in result["report"]


async def test_crag_retries_and_accepts_corrected_evidence():
    news_queries = []

    tools, calls_started = build_mock_tools(
        news_responses=[
            make_gnews_response(
                title="Weather outlook warns of coastal storms",
                description="Meteorologists forecast rainfall and strong winds.",
                url="https://example.com/weather-1",
            ),
            make_gnews_response(
                title="Retail purchasing patterns shift across stores",
                description=(
                    "Retail purchasing patterns reveal changing consumer buying behavior."
                ),
                url="https://example.com/retail-1",
            ),
        ],
        news_queries=news_queries,
    )

    graph = build_research_graph(tools)

    result = await graph.ainvoke(
        {
            "question": "Analyze retail purchasing patterns in the dataset.",
            "requested_sources": ["internal", "external"],
            "news_query": "retail purchasing patterns",
            "product_limit": 5,
        }
    )

    # Internal retrieval remains operational.
    assert calls_started == {"sales", "products", "monthly"}
    assert result["internal_data"]["sales_summary"]["net_line_value"] == "900.00"

    # Initial retrieval plus exactly one corrective retrieval.
    assert len(news_queries) == 2
    assert news_queries[0] == "retail purchasing patterns"
    assert news_queries[1] != news_queries[0]

    # The corrected evidence is graded successfully.
    assert result["crag_attempts"] == 1
    assert result["crag_status"] == "sufficient"
    assert result["research_quality"]["comparison_candidates"] == 1

    # The initial and corrective evidence are both retained.
    assert len(result["external_evidence"]) == 2
    assert len(result["external_bundles"]) == 2
    assert result["errors"] == []


async def test_crag_stops_after_two_retries_and_deduplicates_evidence():
    news_queries = []

    repeated_irrelevant_article = make_gnews_response(
        title="Weather outlook warns of coastal storms",
        description="Meteorologists forecast rainfall and strong winds.",
        url="https://example.com/weather-repeated",
    )

    tools, _ = build_mock_tools(
        news_responses=[
            repeated_irrelevant_article,
            repeated_irrelevant_article,
            repeated_irrelevant_article,
        ],
        news_queries=news_queries,
    )

    graph = build_research_graph(tools)

    result = await graph.ainvoke(
        {
            "question": "Analyze retail purchasing patterns in the dataset.",
            "requested_sources": ["internal", "external"],
            "news_query": "retail purchasing patterns",
            "product_limit": 5,
        }
    )

    # One initial retrieval and two corrective retrievals.
    assert len(news_queries) == 3
    assert len(set(news_queries)) == 3

    assert result["crag_attempts"] == 2
    assert result["crag_status"] == "retry_exhausted"

    # Repeated article IDs must not accumulate.
    assert len(result["external_evidence"]) == 1

    # Internal analytics still complete despite weak external evidence.
    assert result["internal_data"]["sales_summary"]["net_line_value"] == "900.00"
    assert result["quantitative_analysis"]["status"] == "validated"
    assert result["errors"] == []
