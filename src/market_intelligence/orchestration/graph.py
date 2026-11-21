"""LangGraph orchestration for asynchronous market intelligence research."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.graph import START, StateGraph

from market_intelligence.core.config import Settings
from market_intelligence.orchestration.analyst import create_analyst_node
from market_intelligence.orchestration.collector import create_collector_node
from market_intelligence.orchestration.state import ResearchState
from market_intelligence.orchestration.supervisor import create_supervisor_node
from market_intelligence.services.crag import (
    assess_crag_quality,
    build_corrective_news_query,
)
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
    "analytics__get_monthly_sales_analysis",
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


def calculate_quantitative_metrics(
    internal_data: dict[str, Any],
) -> dict[str, Any]:
    """Calculate and validate quantitative metrics deterministically."""

    def to_decimal(value: Any, field_name: str) -> Decimal:
        if value is None:
            raise ValueError(f"Missing numeric field: {field_name}")

        try:
            number = Decimal(str(value))
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise ValueError(f"Invalid numeric field: {field_name}") from exc

        if not number.is_finite():
            raise ValueError(f"Non-finite numeric field: {field_name}")

        return number

    sales = internal_data.get("sales_summary")
    overview = internal_data.get("dataset_overview", {})

    if not sales:
        return {
            "status": "not_available",
            "reason": "No internal sales summary was retrieved.",
        }

    positive = to_decimal(sales["positive_line_value"], "positive_line_value")
    negative = to_decimal(sales["negative_adjustment_value"], "negative_adjustment_value")
    net = to_decimal(sales["net_line_value"], "net_line_value")

    calculated_net = positive + negative
    reconciliation_passed = calculated_net == net

    # Normalize the top-products response.
    products = internal_data.get("top_products", [])

    if isinstance(products, dict) and set(products) == {"result"}:
        products = products["result"]

    if not isinstance(products, list):
        products = []

    products = [product for product in products if isinstance(product, dict)]

    product_values = [
        to_decimal(product.get("net_line_value"), "top_product.net_line_value")
        for product in products
    ]

    retrieved_products_total = sum(product_values, Decimal("0"))

    product_share = (
        (retrieved_products_total / net * Decimal("100")).quantize(Decimal("0.01"))
        if net != 0
        else None
    )

    products_sorted = all(
        product_values[index] >= product_values[index + 1]
        for index in range(len(product_values) - 1)
    )

    # Source metrics are preserved separately from derived metrics.
    source_metrics = {
        "net_quantity": (
            str(to_decimal(sales["net_quantity"], "net_quantity"))
            if sales.get("net_quantity") is not None
            else None
        ),
        "transaction_lines": sales.get("transaction_lines"),
        "unique_invoices": overview.get("unique_invoices"),
        "unique_products": overview.get("unique_products"),
        "unique_customers": overview.get("unique_customers"),
        "unique_countries": overview.get("unique_countries"),
    }

    derived_metrics = {
        "retrieved_products_count": len(products),
        "retrieved_products_net_line_value": str(retrieved_products_total),
        "retrieved_products_share_of_net_line_value_pct": (
            str(product_share) if product_share is not None else None
        ),
    }

    return {
        "status": "validated" if reconciliation_passed else "reconciliation_failed",
        "positive_line_value": str(positive),
        "negative_adjustment_value": str(negative),
        "calculated_net_line_value": str(calculated_net),
        "reported_net_line_value": str(net),
        "reconciliation_difference": str(calculated_net - net),
        "reconciliation_passed": reconciliation_passed,
        "source_metrics": source_metrics,
        "derived_metrics": derived_metrics,
        "validation_checks": {
            "net_value_reconciliation_passed": reconciliation_passed,
            "retrieved_products_sorted_by_net_line_value": products_sorted,
        },
        "metric_scope": (
            "Product contribution covers only the products returned "
            "by the top-products retrieval, not the entire product catalog."
        ),
        "interpretation": (
            "Net line value includes positive transactions and negative "
            "adjustments. It is not independently verified accounting revenue."
        ),
    }


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
    *,
    settings: Settings | None = None,
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

        product_limit = state.get("product_limit", 10)
        max_product_limit = settings.analytics_max_result_rows

        if not 1 <= product_limit <= max_product_limit:
            return {
                "internal_data": internal_data,
                "errors": [f"product_limit must be between 1 and {max_product_limit}."],
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
            "monthly_sales_analysis": (
                tool_map["analytics__get_monthly_sales_analysis"],
                date_arguments,
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

        historical_series_ids = state.get("planned_historical_fred_series")

        if historical_series_ids is None:
            historical_series_ids = state.get("planned_fred_series", [])

        current_series_ids = state.get("planned_current_fred_series", [])

        # Historical observations: align with the dataset window.
        if historical_series_ids:
            if (
                state.get("date_range_valid")
                and state.get("effective_start_date")
                and state.get("effective_end_date")
            ):
                historical_arguments = {
                    "observation_start": state["effective_start_date"],
                    "observation_end": state["effective_end_date"],
                    "limit": 1000,
                    "sort_order": "asc",
                }

                for series_id in historical_series_ids:
                    tasks.append(
                        (
                            f"FRED:HISTORICAL:{series_id}",
                            fetch_fred(series_id, historical_arguments),
                        )
                    )
            else:
                errors.append(
                    "Historical FRED retrieval skipped because "
                    "the dataset comparison window is unavailable."
                )

        # Current observations: independently retrieve the latest two years.
        if current_series_ids:
            current_end = date.today()
            current_start = current_end - timedelta(days=730)

            current_arguments = {
                "observation_start": current_start.isoformat(),
                "observation_end": current_end.isoformat(),
                "limit": 1000,
                "sort_order": "asc",
            }

            for series_id in current_series_ids:
                tasks.append(
                    (
                        f"FRED:CURRENT:{series_id}",
                        fetch_fred(series_id, current_arguments),
                    )
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
                    temporal_label = label.split(":")[1]

                    temporal_scope = (
                        "current_context"
                        if temporal_label == "CURRENT"
                        else "historical_comparison"
                    )

                    bundle = normalize_fred_response(
                        outcome,
                        temporal_scope=temporal_scope,
                    )
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
    # Node 4: Corrective RAG evaluation
    # ---------------------------------------------------------------

    def evaluate_crag(
        state: ResearchState,
    ) -> dict[str, Any]:
        """Evaluate retrieval quality and decide whether to retry."""

        decision = assess_crag_quality(
            state.get("research_quality", {}),
            include_external=state.get("include_external", False),
            include_news=state.get("include_news", False),
            planned_news_query=state.get("planned_news_query"),
            attempts=state.get("crag_attempts", 0),
        )

        updates: dict[str, Any] = {
            "crag_status": decision["status"],
            "crag_reason": decision["reason"],
        }

        if decision["should_retry"]:
            next_attempt = state.get("crag_attempts", 0) + 1

            updates["crag_corrected_news_query"] = build_corrective_news_query(
                question=state.get("question", ""),
                original_query=state.get("planned_news_query"),
                target_geography=state.get("target_geography"),
                attempt=next_attempt,
                reason=decision["reason"],
            )

        return updates

    def route_after_crag(state: ResearchState) -> str:
        """Select corrective retrieval or normal execution."""

        if state.get("crag_status") == "retry_required":
            return "retry"

        return "continue"

    # ---------------------------------------------------------------
    # Node 5: Corrective external retrieval
    # ---------------------------------------------------------------

    async def retrieve_corrective_external(
        state: ResearchState,
    ) -> dict[str, Any]:
        """Retrieve additional news using the corrected CRAG query."""

        query = state.get("crag_corrected_news_query", "")
        attempt = state.get("crag_attempts", 0) + 1

        if not query:
            return {
                "crag_attempts": attempt,
                "crag_status": "retry_failed",
                "errors": ["CRAG corrective retrieval skipped: corrected query is empty."],
            }

        try:
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

            parsed = _parse_tool_output(raw)
            bundle = normalize_gnews_response(parsed)

            new_bundle = bundle.model_dump(mode="json")
            new_evidence = [item.model_dump(mode="json") for item in bundle.items]

            # Preserve original evidence and append only new evidence.
            merged_bundles = list(state.get("external_bundles", []))
            existing_bundle_ids = {
                item.get("bundle_id") for item in merged_bundles if item.get("bundle_id")
            }

            new_bundle_id = new_bundle.get("bundle_id")

            if not new_bundle_id or new_bundle_id not in existing_bundle_ids:
                merged_bundles.append(new_bundle)

            merged_evidence = list(state.get("external_evidence", []))
            existing_evidence_ids = {
                item.get("evidence_id") for item in merged_evidence if item.get("evidence_id")
            }

            for item in new_evidence:
                evidence_id = item.get("evidence_id")

                if not evidence_id or evidence_id not in existing_evidence_ids:
                    merged_evidence.append(item)

                    if evidence_id:
                        existing_evidence_ids.add(evidence_id)

            return {
                "external_bundles": merged_bundles,
                "external_evidence": merged_evidence,
                "crag_attempts": attempt,
                "crag_status": "retrieval_completed",
            }

        except Exception as exc:
            return {
                "crag_attempts": attempt,
                "crag_status": "retry_failed",
                "errors": [
                    (f"CRAG corrective retrieval failed: {type(exc).__name__}: {str(exc)[:300]}")
                ],
            }

    # ---------------------------------------------------------------
    # Node 6: Deterministic quantitative analysis
    # ---------------------------------------------------------------

    def quantitative_analysis(
        state: ResearchState,
    ) -> dict[str, Any]:
        """Reconcile deterministic SQL outputs using Decimal."""

        return {
            "quantitative_analysis": calculate_quantitative_metrics(state.get("internal_data", {}))
        }

    # ---------------------------------------------------------------
    # Node 7: Research synthesis
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
                    "| Stock code | Product | Net line value | Positive sales contribution |"
                    "|---|---|---:|---:|",
                ]
            )

            for product in products:
                description = product.get("description") or "Description unavailable"
                description = description.replace("|", "\\|")
                share = product.get("positive_line_value_share_pct")

                sections.append(
                    f"| {product['stock_code']} | {description} "
                    f"| {product['net_line_value']} "
                    f"| {f'{share}%' if share is not None else 'N/A'} |"
                )

        monthly = internal.get("monthly_sales_analysis", {})

        if monthly:
            trend = monthly.get("monthly_trend", [])

            if trend:
                sections.extend(
                    [
                        "",
                        "### Monthly sales trends",
                        "",
                        "| Month | Net line value | MoM change | YoY change | Completeness |",
                        "|---|---:|---:|---:|---|",
                    ]
                )

                for item in trend:
                    mom = (
                        f"{item['mom_change_pct']}%"
                        if item.get("mom_change_pct") is not None
                        else "N/A"
                    )
                    yoy = (
                        f"{item['yoy_change_pct']}%"
                        if item.get("yoy_change_pct") is not None
                        else "N/A"
                    )
                    completeness = "Complete" if item["is_complete_month"] else "Partial"

                    sections.append(
                        f"| {item['month_label']} "
                        f"| {item['net_line_value']} "
                        f"| {mom} | {yoy} | {completeness} |"
                    )

            seasonality = monthly.get("seasonality", [])

            if seasonality:
                sections.extend(
                    [
                        "",
                        "### Seasonal sales patterns",
                        "",
                        "| Calendar month | Average net line value | Seasonal index | Observations |",
                        "|---|---:|---:|---:|",
                    ]
                )

                for item in seasonality:
                    index = (
                        f"{item['seasonal_index_pct']}%"
                        if item.get("seasonal_index_pct") is not None
                        else "N/A"
                    )

                    sections.append(
                        f"| {item['calendar_month']} "
                        f"| {item['average_net_line_value']} "
                        f"| {index} "
                        f"| {item['months_observed']} |"
                    )

            anomaly = monthly.get("anomaly_analysis", {})
            anomalies = anomaly.get("anomalies", [])

            sections.extend(
                [
                    "",
                    "### Monthly sales anomaly detection",
                    "",
                    f"- Method: {anomaly.get('method') or 'Not evaluated'}",
                    f"- Months evaluated: {anomaly.get('months_evaluated', 0)}",
                ]
            )

            if anomalies:
                sections.extend(
                    [
                        "",
                        "| Month | Net line value | Direction | Modified Z-score |",
                        "|---|---:|---|---:|",
                    ]
                )

                for item in anomalies:
                    score = (
                        item["modified_z_score"]
                        if item.get("modified_z_score") is not None
                        else "IQR threshold"
                    )

                    sections.append(
                        f"| {item['month_label']} "
                        f"| {item['net_line_value']} "
                        f"| {item['direction']} | {score} |"
                    )
            else:
                sections.append(
                    "- No monthly outliers were flagged, or there was "
                    "insufficient history to evaluate them."
                )

            for limitation in monthly.get("limitations", []):
                sections.append(f"- Limitation: {limitation}")

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

        collector_findings = state.get("collector_findings", {})

        if collector_findings:
            sections.extend(
                [
                    "",
                    "## 6. Research objective coverage",
                    "",
                ]
            )

            for assessment in collector_findings.get("objective_assessments", []):
                sections.extend(
                    [
                        f"### {assessment['objective']}",
                        f"- Status: {assessment['status']}",
                        f"- Assessment: {assessment['explanation']}",
                    ]
                )

                if assessment["evidence_ids"]:
                    sections.append(f"- Evidence IDs: {', '.join(assessment['evidence_ids'])}")

                sections.append("")

            limitations = collector_findings.get("limitations", [])

            if limitations:
                sections.append("### Collection limitations")
                sections.extend(f"- {item}" for item in limitations)

        analyst_findings = state.get("analyst_findings", {})

        if analyst_findings:
            sections.extend(
                [
                    "",
                    "## 7. Analytical interpretation",
                    "",
                    "### Executive summary",
                    "",
                    analyst_findings["executive_summary"],
                    "",
                    "### Analytical findings",
                    "",
                ]
            )

            for finding in analyst_findings.get("findings", []):
                sections.extend(
                    [
                        f"#### {finding['objective']}",
                        f"- Status: {finding['status']}",
                        f"- Finding: {finding['finding']}",
                        f"- Business implication: {finding['business_implication']}",
                    ]
                )

                if finding["supporting_fields"]:
                    sections.append(
                        f"- Supporting fields: {', '.join(finding['supporting_fields'])}"
                    )

                if finding["limitation"]:
                    sections.append(f"- Limitation: {finding['limitation']}")

                sections.append("")

            recommendations = analyst_findings.get("recommendations", [])

            if recommendations:
                sections.extend(["### Recommendations", ""])
                sections.extend(f"- {item}" for item in recommendations)

            limitations = analyst_findings.get("limitations", [])

            if limitations:
                sections.extend(["", "### Analytical limitations", ""])
                sections.extend(f"- {item}" for item in limitations)

            sections.extend(
                [
                    "",
                    f"**Analyst confidence:** {analyst_findings['confidence']}",
                ]
            )

        errors = state.get("errors", [])

        warning_section = 8 if analyst_findings else 7 if collector_findings else 6

        if errors:
            sections.extend(
                [
                    "",
                    f"## {warning_section}. Retrieval warnings",
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

    planner_node = create_supervisor_node(settings) if settings is not None else _plan_research

    collector_node = create_collector_node(settings) if settings is not None else None

    analyst_node = create_analyst_node(settings) if settings is not None else None

    builder = StateGraph(ResearchState)

    if collector_node is not None:
        builder.add_node("collector", collector_node)

    if analyst_node is not None:
        builder.add_node("analyst", analyst_node)
    builder.add_node("plan_research", planner_node)
    builder.add_node("load_dataset_context", load_dataset_context)
    builder.add_node("retrieve_internal", retrieve_internal)
    builder.add_node("evaluate_crag", evaluate_crag)
    builder.add_node(
        "retrieve_corrective_external",
        retrieve_corrective_external,
    )
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

    builder.add_edge("grade_evidence", "evaluate_crag")

    builder.add_conditional_edges(
        "evaluate_crag",
        route_after_crag,
        {
            "retry": "retrieve_corrective_external",
            "continue": "quantitative_analysis",
        },
    )

    builder.add_edge(
        "retrieve_corrective_external",
        "grade_evidence",
    )
    if collector_node is not None and analyst_node is not None:
        builder.add_edge("quantitative_analysis", "collector")
        builder.add_edge("collector", "analyst")
        builder.add_edge("analyst", "synthesize_report")
    else:
        builder.add_edge("quantitative_analysis", "synthesize_report")

    return builder.compile()
