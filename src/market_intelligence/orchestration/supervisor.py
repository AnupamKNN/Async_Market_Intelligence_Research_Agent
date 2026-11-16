"""LLM-powered supervisor for market intelligence research."""

from langchain_core.messages import HumanMessage, SystemMessage

from market_intelligence.core.config import Settings
from market_intelligence.orchestration.state import ResearchState
from market_intelligence.schemas.supervisor import SupervisorPlan
from market_intelligence.services.llm_gateway import create_chat_model

SUPERVISOR_SYSTEM_PROMPT = """
You are the research supervisor of a market intelligence platform.

Your responsibility is to interpret the research question and create a
structured execution plan. You coordinate research; you do not perform
calculations or invent factual findings.

AVAILABLE DATA SOURCES

1. INTERNAL
   - UCI Online Retail transaction dataset.
   - Dataset coverage: December 2009 to December 2011.
   - Available analytics: dataset overview, sales summary, top products.
   - Use for retail sales, transactions, products and customer analytics.

2. EXTERNAL
   - FRED: economic indicators and historical observations.
   - GNews: market, industry, competitor and economic news.
   - Use for macroeconomic context, current developments and external
     comparisons.

RESEARCH PLANNING RULES

1. Select internal sources for questions about the available retail dataset.
2. Select external sources for macroeconomic and market research.
3. Select both when the question requires comparing internal retail
   performance with external economic or market conditions.
4. When the question is ambiguous, prefer internal analytics.
5. Respect explicitly requested sources. Never add an unrequested source.
6. Select FRED series only when relevant to the question.
7. Use a focused GNews query when news evidence is needed.
8. Do not select news retrieval merely because a question mentions retail.
9. Create clear, actionable analytical objectives.
10. Do not invent metrics, findings, formulas or external evidence.
11. If external research is selected, specify at least one FRED series
    or a news query.
12. Provide a concise rationale for your research strategy.

COMMON FRED SERIES
- UNRATE: Unemployment rate
- CPIAUCSL: Consumer Price Index
- GDP: Gross Domestic Product
- FEDFUNDS: Federal funds rate
- DGS10: 10-year Treasury yield
- RSAFS: Advance retail sales

Return only the structured output matching the supplied schema.
"""


def create_supervisor_node(settings: Settings):
    """Build an asynchronous LLM supervisor node."""

    model = create_chat_model(
        settings,
        provider=settings.supervisor_llm_provider,
        model=settings.supervisor_llm_model,
        temperature=settings.supervisor_llm_temperature,
    )

    structured_model = model.with_structured_output(
        SupervisorPlan,
        method="function_calling",
    )

    async def supervisor_node(state: ResearchState) -> dict:
        """Generate and validate a research execution plan."""

        question = state.get("question", "").strip()

        if not question:
            raise ValueError("A non-empty research question is required.")

        requested_sources = state.get("requested_sources")

        if requested_sources is not None:
            invalid_sources = set(requested_sources) - {"internal", "external"}

            if invalid_sources:
                raise ValueError(f"Unsupported requested_sources: {sorted(invalid_sources)}")

            if not requested_sources:
                raise ValueError("requested_sources cannot be empty.")

        context = {
            "question": question,
            "requested_sources": requested_sources,
            "start_date": state.get("start_date"),
            "end_date": state.get("end_date"),
            "fred_series_ids": state.get("fred_series_ids", []),
            "news_query": state.get("news_query"),
        }

        response = await structured_model.ainvoke(
            [
                SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
                HumanMessage(
                    content=f"Create the research execution plan for this request:\n{context}"
                ),
            ]
        )

        plan = (
            response
            if isinstance(response, SupervisorPlan)
            else SupervisorPlan.model_validate(response)
        )

        # Resolve explicit user retrieval targets first.
        planned_fred_series = (
            list(dict.fromkeys(state.get("fred_series_ids", [])))
            if state.get("fred_series_ids")
            else plan.fred_series_ids
        )

        planned_news_query = state.get("news_query") or plan.news_query

        # Explicit user source selection always takes precedence.
        if requested_sources is not None:
            resolved_sources = list(requested_sources)
        else:
            resolved_sources = list(plan.sources)

            # Deterministic fallback when the LLM omits sources.
            if not resolved_sources:
                resolved_sources = ["internal"]

                if planned_fred_series or planned_news_query:
                    resolved_sources.append("external")

        if not resolved_sources:
            raise ValueError("At least one research source must be selected.")

        include_internal = "internal" in resolved_sources
        include_external = "external" in resolved_sources

        if include_external and not (planned_fred_series or planned_news_query):
            raise ValueError("External research requires at least one retrieval target.")

        if not include_external:
            planned_fred_series = []
            planned_news_query = None

        scope_text = " ".join([question, *plan.analysis_objectives]).casefold()

        current_terms = (
            "current",
            "currently",
            "recent",
            "latest",
            "today",
            "present",
        )

        historical_terms = (
            "historical",
            "history",
            "dataset",
            "historic",
            "2009",
            "2010",
            "2011",
        )

        wants_current = any(term in scope_text for term in current_terms)
        wants_historical = any(term in scope_text for term in historical_terms) or bool(
            state.get("start_date") or state.get("end_date")
        )

        # Default to historical retrieval when no temporal scope is explicit.
        if not wants_current and not wants_historical:
            wants_historical = True

        planned_historical_fred_series = planned_fred_series if wants_historical else []

        planned_current_fred_series = planned_fred_series if wants_current else []

        # Supply a deterministic rationale if the LLM omitted it.
        rationale = plan.rationale.strip()[:500] or (
            "Research sources were resolved using the user's source constraints "
            "and the available retrieval targets."
        )

        # Provide safe default objectives if the LLM omitted them.
        objectives = list(plan.analysis_objectives)

        if not objectives:
            if include_internal:
                objectives.append(
                    "Analyze internal retail transactions, sales performance, and product activity."
                )

            if include_external:
                objectives.append(
                    "Assess relevant external economic indicators and current retail market news."
                )

        # Validate the completed execution plan.
        plan = SupervisorPlan.model_validate(
            {
                **plan.model_dump(mode="python"),
                "sources": resolved_sources,
                "fred_series_ids": planned_fred_series,
                "news_query": planned_news_query,
                "analysis_objectives": objectives,
                "rationale": rationale,
            }
        )

        if include_internal and include_external:
            retrieval_mode = "mixed"
        elif include_internal:
            retrieval_mode = "internal_only"
        else:
            retrieval_mode = "external_only"

        include_news = include_external and bool(planned_news_query)

        decision = plan.model_dump(mode="json")
        decision["sources"] = sorted(plan.sources)
        decision["fred_series_ids"] = planned_fred_series
        decision["news_query"] = planned_news_query
        decision["provider"] = settings.supervisor_llm_provider
        decision["model"] = settings.supervisor_llm_model
        decision["historical_fred_series_ids"] = planned_historical_fred_series
        decision["current_fred_series_ids"] = planned_current_fred_series

        return {
            "retrieval_mode": retrieval_mode,
            "include_internal": include_internal,
            "include_external": include_external,
            "include_news": include_news,
            "planned_fred_series": planned_fred_series,
            "planned_news_query": planned_news_query,
            "supervisor_decision": decision,
        }

    return supervisor_node
