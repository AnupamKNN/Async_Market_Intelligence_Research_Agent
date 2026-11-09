"""LangGraph orchestration for asynchronous market intelligence research."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from market_intelligence.orchestration.state import ResearchState
from market_intelligence.services.evidence_normalizer import (
    normalize_fred_response,
    normalize_gnews_response,
)
from market_intelligence.services.research_quality import (
    build_fred_date_arguments,
    grade_evidence_records,
    infer_target_geography,
)

REQUIRED_TOOLS = {
    "analytics__database_health",
    "analytics__get_dataset_overview",
    "analytics__get_sales_summary",
    "analytics__get_top_products",
    "research__get_fred_series_observations",
    "research__search_market_news",
}


INTERNAL_TERMS = {
    "retail",
    "sales",
    "product",
    "customer",
    "invoice",
    "transaction",
    "revenue",
    "order",
    "purchase",
    "dataset",
    "basket",
    "country",
    "quantity",
    "store",
}

EXTERNAL_TERMS = {
    "economy",
    "economic",
    "inflation",
    "unemployment",
    "gdp",
    "interest rate",
    "federal reserve",
    "fed funds",
    "treasury",
    "market",
    "news",
    "latest",
    "current",
    "today",
    "recent",
    "industry",
    "competitor",
    "sector",
    "outlook",
    "forecast",
}

NEWS_TERMS = {
    "news",
    "latest",
    "current",
    "today",
    "recent",
    "market",
    "company",
    "competitor",
    "industry",
    "sector",
    "outlook",
    "announcement",
    "earnings",
}

FRED_SERIES_RULES = (
    (("unemployment", "job market", "labor market"), "UNRATE"),
    (("inflation", "cpi", "consumer price"), "CPIAUCSL"),
    (("gdp", "gross domestic product", "economic growth"), "GDP"),
    (("interest rate", "federal funds", "fed funds"), "FEDFUNDS"),
    (("treasury", "bond yield", "10-year yield"), "DGS10"),
    (("retail sales", "consumer spending"), "RSAFS"),
)


def _contains_any(text: str, terms: set[str]) -> bool:
    """Check whether text contains any configured search term."""

    return any(term in text for term in terms)


def _parse_tool_output(result: Any) -> Any:
    """Decode JSON returned by the MCP-to-LangChain bridge.

    MCP structured content for list-returning tools may be wrapped
    in an object whose only key is ``result``.
    """

    if isinstance(result, (dict, list)):
        decoded = result
    elif isinstance(result, str):
        try:
            decoded = json.loads(result)
        except json.JSONDecodeError as exc:
            raise ValueError("MCP tool returned invalid JSON.") from exc
    else:
        raise TypeError(f"Unexpected MCP tool result type: {type(result).__name__}")

    if isinstance(decoded, dict) and set(decoded) == {"result"}:
        decoded = decoded["result"]

    if not isinstance(decoded, (dict, list)):
        raise ValueError("Expected a JSON object or array from the MCP tool.")

    return decoded


def _validate_date_inputs(state: ResearchState) -> None:
    """Validate optional date boundaries supplied by the user."""

    from datetime import date

    start = state.get("start_date")
    end = state.get("end_date")

    parsed_start = date.fromisoformat(start) if start else None
    parsed_end = date.fromisoformat(end) if end else None

    if parsed_start and parsed_end and parsed_start > parsed_end:
        raise ValueError("start_date cannot be later than end_date.")


def _infer_fred_series(question: str) -> list[str]:
    """Infer relevant FRED series from explicit macroeconomic topics."""

    series_ids: list[str] = []

    for terms, series_id in FRED_SERIES_RULES:
        if any(term in question for term in terms):
            series_ids.append(series_id)

    return series_ids


def _build_default_news_query(
    question: str,
    series_ids: list[str],
) -> str:
    """Build a concise GNews query from recognized research topics."""

    series_terms = {
        "UNRATE": "unemployment",
        "CPIAUCSL": "inflation",
        "GDP": "GDP",
        "FEDFUNDS": '"interest rates"',
        "DGS10": '"Treasury yields"',
        "RSAFS": '"retail sales"',
    }

    selected = [series_terms[series_id] for series_id in series_ids if series_id in series_terms]

    if selected:
        return " OR ".join(dict.fromkeys(selected))

    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "about",
        "by",
        "compare",
        "does",
        "for",
        "from",
        "how",
        "in",
        "is",
        "of",
        "our",
        "the",
        "to",
        "with",
        "what",
        "recent",
        "latest",
        "current",
        "today",
    }
    tokens = re.findall(r"[A-Za-z0-9]+", question)
    terms = [token for token in tokens if token.lower() not in stop_words]

    return " ".join(terms[:10]) or "business markets"


def _plan_research(state: ResearchState) -> dict[str, Any]:
    """Create a deterministic retrieval plan from the user question."""

    question = state.get("question", "").strip()

    if not question:
        raise ValueError("A non-empty research question is required.")

    normalized_question = question.lower()
    _validate_date_inputs(state)

    requested_sources = state.get("requested_sources")

    if requested_sources is not None:
        invalid_sources = set(requested_sources) - {
            "internal",
            "external",
        }

        if invalid_sources:
            raise ValueError(
                f"Unsupported requested_sources: {sorted(invalid_sources)}. "
                "Use 'internal' and/or 'external'."
            )

        if not requested_sources:
            raise ValueError("requested_sources cannot be empty.")

        include_internal = "internal" in requested_sources
        include_external = "external" in requested_sources

    else:
        include_internal = _contains_any(
            normalized_question,
            INTERNAL_TERMS,
        )
        include_external = _contains_any(
            normalized_question,
            EXTERNAL_TERMS,
        )

        # Default to internal analytics when the question is ambiguous.
        if not include_internal and not include_external:
            include_internal = True

    explicit_series = state.get("fred_series_ids", [])
    planned_fred_series = (
        list(dict.fromkeys(explicit_series))
        if explicit_series
        else (_infer_fred_series(normalized_question) if include_external else [])
    )

    include_news = include_external and (
        bool(state.get("news_query"))
        or _contains_any(normalized_question, NEWS_TERMS)
        or not planned_fred_series
    )

    news_query = state.get("news_query")

    if include_news and not news_query:
        news_query = _build_default_news_query(
            question,
            planned_fred_series,
        )

    if include_internal and include_external:
        retrieval_mode = "mixed"
    elif include_internal:
        retrieval_mode = "internal_only"
    else:
        retrieval_mode = "external_only"

    return {
        "retrieval_mode": retrieval_mode,
        "include_internal": include_internal,
        "include_external": include_external,
        "include_news": include_news,
        "planned_fred_series": planned_fred_series,
        "planned_news_query": news_query,
    }


def build_research_graph(
    tools: Sequence[StructuredTool],
):
    """Build and compile the market intelligence LangGraph workflow.

    The supplied MCP tools must remain connected for the graph's lifetime.
    Keep the MCPToolBridge context open while invoking this graph.
    """

    tool_map = {tool.name: tool for tool in tools}
    missing_tools = REQUIRED_TOOLS - set(tool_map)

    if missing_tools:
        raise ValueError(f"Required MCP tools are missing: {sorted(missing_tools)}")

    # ---------------------------------------------------------------
    # Node 0: Dataset temporal context
    # ---------------------------------------------------------------

    async def load_dataset_context(
        state: ResearchState,
    ) -> dict[str, Any]:
        """Load dataset coverage and calculate a valid research window."""

        if not (state.get("include_internal") or state.get("include_external")):
            return {
                "dataset_overview": {},
                "date_range_valid": False,
                "errors": [],
            }

        overview: dict[str, Any] = {}

        try:
            raw = await tool_map["analytics__get_dataset_overview"].ainvoke({})
            result = _parse_tool_output(raw)

            if not isinstance(result, dict):
                raise ValueError("Dataset overview did not return a JSON object.")

            overview = result

            effective_dates = build_fred_date_arguments(
                overview,
                requested_start=state.get("start_date"),
                requested_end=state.get("end_date"),
            )

            return {
                "dataset_overview": overview,
                "effective_start_date": effective_dates["observation_start"],
                "effective_end_date": effective_dates["observation_end"],
                "date_range_valid": True,
                "target_geography": infer_target_geography(state.get("question", "")),
                "errors": [],
            }

        except Exception as exc:
            return {
                "dataset_overview": overview,
                "effective_start_date": None,
                "effective_end_date": None,
                "date_range_valid": False,
                "target_geography": infer_target_geography(state.get("question", "")),
                "errors": [
                    "Dataset temporal context could not be established: "
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                ],
            }

    # ---------------------------------------------------------------
    # Node 1: Internal Analytics retrieval
    # ---------------------------------------------------------------

    async def retrieve_internal(
        state: ResearchState,
    ) -> dict[str, Any]:
        """Retrieve internal analytics using shared dataset context."""

        if not state.get("include_internal", False):
            return {"internal_data": {}, "errors": []}

        overview = state.get("dataset_overview", {})

        if not overview:
            return {
                "internal_data": {},
                "errors": ["Internal analytics skipped because dataset metadata is unavailable."],
            }

        internal_data: dict[str, Any] = {
            "dataset_overview": overview,
        }

        if not state.get("date_range_valid", False):
            return {"internal_data": internal_data, "errors": []}

        date_arguments = {
            "start_date": state["effective_start_date"],
            "end_date": state["effective_end_date"],
        }

        product_limit = state.get("product_limit", 5)

        if not 1 <= product_limit <= 50:
            return {
                "internal_data": internal_data,
                "errors": ["product_limit must be between 1 and 50."],
            }

        requests = {
            "sales_summary": (
                tool_map["analytics__get_sales_summary"],
                date_arguments,
            ),
            "top_products": (
                tool_map["analytics__get_top_products"],
                {
                    "limit": product_limit,
                    **date_arguments,
                },
            ),
        }

        async def call_one(
            name: str,
            tool: StructuredTool,
            arguments: dict[str, Any],
        ) -> tuple[str, Any]:
            try:
                raw_result = await tool.ainvoke(arguments)
                return name, _parse_tool_output(raw_result)
            except Exception as exc:
                return name, exc

        results = await asyncio.gather(
            *(call_one(name, tool, arguments) for name, (tool, arguments) in requests.items())
        )

        errors: list[str] = []

        for name, result in results:
            if isinstance(result, Exception):
                errors.append(
                    f"Internal analytics '{name}' failed: "
                    f"{type(result).__name__}: {str(result)[:300]}"
                )
            else:
                internal_data[name] = result

        return {
            "internal_data": internal_data,
            "errors": errors,
        }

    # ---------------------------------------------------------------
    # Node 2: External Research retrieval
    # ---------------------------------------------------------------

    async def retrieve_external(
        state: ResearchState,
    ) -> dict[str, Any]:
        """Retrieve date-aligned FRED data and contextual GNews articles."""

        if not state.get("include_external", False):
            return {
                "external_bundles": [],
                "external_evidence": [],
                "errors": [],
            }

        tasks: list[tuple[str, Any]] = []
        errors: list[str] = []

        async def fetch_fred(
            series_id: str,
            date_arguments: dict[str, Any],
        ) -> dict[str, Any]:
            arguments = {
                "series_id": series_id,
                **date_arguments,
                "units": "lin",
            }

            raw = await tool_map["research__get_fred_series_observations"].ainvoke(arguments)

            return _parse_tool_output(raw)

        async def fetch_news(query: str) -> dict[str, Any]:
            arguments = {
                "query": query[:200],
                "lang": "en",
                "max_articles": min(
                    max(state.get("max_articles", 5), 1),
                    10,
                ),
                "sort_by": "publishedAt",
            }

            raw = await tool_map["research__search_market_news"].ainvoke(arguments)

            return _parse_tool_output(raw)

        series_ids = state.get("planned_fred_series", [])

        if series_ids:
            if (
                state.get("date_range_valid")
                and state.get("effective_start_date")
                and state.get("effective_end_date")
            ):
                date_arguments = {
                    "observation_start": state["effective_start_date"],
                    "observation_end": state["effective_end_date"],
                    "limit": 1000,
                    "sort_order": "asc",
                }

                for series_id in series_ids:
                    tasks.append(
                        (
                            f"FRED:{series_id}",
                            fetch_fred(series_id, date_arguments),
                        )
                    )
            else:
                errors.append(
                    "FRED retrieval skipped because a valid dataset "
                    "comparison window is unavailable."
                )

        news_query = state.get("planned_news_query")

        if state.get("include_news") and news_query:
            tasks.append(("GNews", fetch_news(news_query)))

        if not tasks:
            if not errors:
                errors.append(
                    "External research was requested, but no retrieval "
                    "source was selected by the planner."
                )

            return {
                "external_bundles": [],
                "external_evidence": [],
                "errors": errors,
            }

        outcomes = await asyncio.gather(
            *(task for _, task in tasks),
            return_exceptions=True,
        )

        bundles: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []

        for (label, _), outcome in zip(tasks, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                errors.append(
                    f"External retrieval '{label}' failed: "
                    f"{type(outcome).__name__}: {str(outcome)[:300]}"
                )
                continue

            try:
                if label.startswith("FRED:"):
                    bundle = normalize_fred_response(outcome)
                else:
                    bundle = normalize_gnews_response(outcome)

                bundles.append(bundle.model_dump(mode="json"))
                evidence.extend(item.model_dump(mode="json") for item in bundle.items)

            except Exception as exc:
                errors.append(
                    f"Evidence normalization '{label}' failed: "
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                )

        return {
            "external_bundles": bundles,
            "external_evidence": evidence,
            "errors": errors,
        }

    # ---------------------------------------------------------------
    # Node 3: Evidence grading
    # ---------------------------------------------------------------

    def grade_evidence(
        state: ResearchState,
    ) -> dict[str, Any]:
        """Evaluate citation, topical, geographic, and temporal quality."""

        records = state.get("external_evidence", [])
        internal_data = state.get("internal_data", {})
        overview = state.get("dataset_overview") or None

        quality = grade_evidence_records(
            records=records,
            question=state.get("question", ""),
            dataset_overview=overview,
            target_geography=state.get("target_geography"),
        )

        providers = sorted({item.get("provider") for item in records if item.get("provider")})

        evidence_grade = {
            "status": quality["status"],
            "external_records_received": quality["total_records"],
            "valid_external_records": quality["citation_valid"],
            "providers": providers,
            "internal_data_available": bool(internal_data),
            "citation_coverage": quality["citation_coverage"],
            "topically_relevant": quality["topically_relevant"],
            "geographically_matched": quality["geographically_matched"],
            "temporally_aligned": quality["temporally_aligned"],
            "comparison_candidates": quality["comparison_candidates"],
            "context_only": quality["context_only"],
        }

        return {
            "research_quality": quality,
            "evidence_grade": evidence_grade,
        }

    # ---------------------------------------------------------------
    # Node 4: Deterministic quantitative analysis
    # ---------------------------------------------------------------

    def quantitative_analysis(
        state: ResearchState,
    ) -> dict[str, Any]:
        """Reconcile deterministic SQL outputs using Decimal."""

        sales = state.get("internal_data", {}).get("sales_summary")

        if not sales:
            return {
                "quantitative_analysis": {
                    "status": "not_available",
                    "reason": "No internal sales summary was retrieved.",
                }
            }

        positive = Decimal(sales["positive_line_value"])
        negative = Decimal(sales["negative_adjustment_value"])
        net = Decimal(sales["net_line_value"])

        calculated_net = positive + negative

        return {
            "quantitative_analysis": {
                "status": ("validated" if calculated_net == net else "reconciliation_failed"),
                "positive_line_value": str(positive),
                "negative_adjustment_value": str(negative),
                "calculated_net_line_value": str(calculated_net),
                "reported_net_line_value": str(net),
                "reconciliation_difference": str(calculated_net - net),
                "reconciliation_passed": calculated_net == net,
                "interpretation": (
                    "Net line value includes positive transactions "
                    "and negative adjustments. It is not independently "
                    "verified accounting revenue."
                ),
            }
        }

    # ---------------------------------------------------------------
    # Node 5: Research synthesis
    # ---------------------------------------------------------------

    def synthesize_report(
        state: ResearchState,
    ) -> dict[str, Any]:
        """Create a traceable deterministic research report."""

        question = state.get("question", "")
        internal = state.get("internal_data", {})
        evidence = state.get("external_evidence", [])
        grade = state.get("evidence_grade", {})
        analysis = state.get("quantitative_analysis", {})

        sections = [
            "# Market Intelligence Research Report",
            "",
            f"**Research question:** {question}",
            f"**Retrieval mode:** {state.get('retrieval_mode', 'unknown')}",
            "",
            "## 1. Internal analytics",
            "",
        ]

        overview = internal.get("dataset_overview")

        if overview:
            sections.extend(
                [
                    f"- Transaction records: {overview['total_records']:,}",
                    f"- Unique invoices: {overview['unique_invoices']:,}",
                    f"- Unique products: {overview['unique_products']:,}",
                    f"- Unique customers: {overview['unique_customers']:,}",
                    f"- Countries: {overview['unique_countries']:,}",
                    (
                        f"- Dataset coverage: "
                        f"{overview['first_transaction']} to "
                        f"{overview['last_transaction']}"
                    ),
                ]
            )

        sales = internal.get("sales_summary")

        if sales:
            sections.extend(
                [
                    "",
                    "### Transaction value",
                    "",
                    f"- Positive line value: {sales['positive_line_value']}",
                    (f"- Negative adjustments: {sales['negative_adjustment_value']}"),
                    f"- Net line value: {sales['net_line_value']}",
                    (f"- Transaction lines: {sales['transaction_lines']:,}"),
                ]
            )

        products = internal.get("top_products", [])

        if isinstance(products, dict) and set(products) == {"result"}:
            products = products["result"]

        if not isinstance(products, list):
            products = []

        products = [product for product in products if isinstance(product, dict)]

        if products:
            sections.extend(
                [
                    "",
                    "### Top products by net line value",
                    "",
                    "| Stock code | Product | Net line value |",
                    "|---|---|---:|",
                ]
            )

            for product in products:
                description = product.get("description") or "Description unavailable"
                description = description.replace("|", "\\|")
                sections.append(
                    f"| {product['stock_code']} | {description} | {product['net_line_value']} |"
                )

        if not internal:
            sections.append("No internal analytics were requested or retrieved.")

        sections.extend(
            [
                "",
                "## 2. External research",
                "",
            ]
        )

        if evidence:
            for index, record in enumerate(evidence, start=1):
                sections.extend(
                    [
                        f"### {index}. {record['title']}",
                        "",
                        f"- Provider: {record['provider']}",
                        f"- Publisher: {record['publisher']}",
                    ]
                )

                if record.get("published_at"):
                    sections.append(f"- Published: {record['published_at']}")

                if record.get("observation_start"):
                    sections.append(f"- Observation date: {record['observation_start']}")

                excerpt = record.get("excerpt")

                if excerpt:
                    sections.append(f"- Excerpt: {excerpt[:400]}")

                data = record.get("data", {})

                if data.get("series_id"):
                    sections.append(f"- Series: {data['series_id']}")
                    sections.append(f"- Value: {data.get('value')}")
                    sections.append(f"- Units: {data.get('source_units')}")

                sections.append(f"- Evidence ID: `{record['evidence_id']}`")
                sections.append(f"- Source: {record['source_url']}")
                sections.append("")

        else:
            sections.append("No external evidence was retrieved.")

        sections.extend(
            [
                "## 3. Evidence quality",
                "",
                f"- Status: {grade.get('status', 'unknown')}",
                (f"- Valid external evidence records: {grade.get('valid_external_records', 0)}"),
                (f"- Citation coverage: {grade.get('citation_coverage', 0.0):.0%}"),
                (f"- Internal data available: {grade.get('internal_data_available', False)}"),
                "",
                "## 4. Quantitative validation",
                "",
                (f"- Calculation status: {analysis.get('status', 'not_available')}"),
                (
                    f"- Net-value reconciliation passed: "
                    f"{analysis.get('reconciliation_passed', 'N/A')}"
                ),
            ]
        )

        if analysis.get("reconciliation_difference") is not None:
            sections.append(f"- Reconciliation difference: {analysis['reconciliation_difference']}")

        sections.extend(
            [
                "",
                "## 5. Limitations and interpretation",
                "",
                "- External sources are untrusted evidence, not verified facts.",
                "- FRED observation dates are not necessarily publication dates.",
                "- Economic observations may be revised by their publisher.",
                "- News excerpts may be incomplete; consult the original article.",
                ("- Transaction line value is not independently verified accounting revenue."),
                (
                    "- Correlation between economic indicators and retail "
                    "performance does not establish causation."
                ),
                "- No generated or retrieved code is executed.",
            ]
        )

        errors = state.get("errors", [])

        if errors:
            sections.extend(
                [
                    "",
                    "## 6. Retrieval warnings",
                    "",
                ]
            )
            sections.extend(f"- {error}" for error in errors)

        return {
            "report": "\n".join(sections),
            "synthesis_mode": "deterministic",
        }

    # ---------------------------------------------------------------
    # Build the graph
    # ---------------------------------------------------------------

    builder = StateGraph(ResearchState)

    builder.add_node("plan_research", _plan_research)
    builder.add_node("load_dataset_context", load_dataset_context)
    builder.add_node("retrieve_internal", retrieve_internal)
    builder.add_node("retrieve_external", retrieve_external)
    builder.add_node("grade_evidence", grade_evidence)
    builder.add_node("quantitative_analysis", quantitative_analysis)
    builder.add_node("synthesize_report", synthesize_report)

    builder.add_edge(START, "plan_research")

    # Establish dataset coverage before starting parallel retrieval.
    builder.add_edge("plan_research", "load_dataset_context")

    # Both retrieval branches now share the same validated date window.
    builder.add_edge("load_dataset_context", "retrieve_internal")
    builder.add_edge("load_dataset_context", "retrieve_external")

    # Synchronization barrier: wait for both retrieval branches.
    builder.add_edge(
        ["retrieve_internal", "retrieve_external"],
        "grade_evidence",
    )

    builder.add_edge("grade_evidence", "quantitative_analysis")
    builder.add_edge("quantitative_analysis", "synthesize_report")
    builder.add_edge("synthesize_report", END)

    return builder.compile()
