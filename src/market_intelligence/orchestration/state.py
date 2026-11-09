"""Shared state contract for the market intelligence research graph."""

import operator
from typing import Annotated, Any, TypedDict


class ResearchState(TypedDict, total=False):
    """State passed between LangGraph research nodes."""

    # User input
    question: str
    requested_sources: list[str]
    start_date: str | None
    end_date: str | None
    fred_series_ids: list[str]
    news_query: str | None
    max_articles: int
    product_limit: int

    # Research planning
    retrieval_mode: str
    include_internal: bool
    include_external: bool
    include_news: bool
    planned_fred_series: list[str]
    planned_news_query: str | None
    target_geography: str | None
    target_geography: str | None

    # Retrieval results
    dataset_overview: dict[str, Any]
    effective_start_date: str | None
    effective_end_date: str | None
    date_range_valid: bool
    dataset_overview: dict[str, Any]
    effective_start_date: str | None
    effective_end_date: str | None
    date_range_valid: bool
    internal_data: dict[str, Any]
    external_bundles: list[dict[str, Any]]
    external_evidence: list[dict[str, Any]]

    # Evidence and analytics
    evidence_grade: dict[str, Any]
    research_quality: dict[str, Any]
    research_quality: dict[str, Any]
    quantitative_analysis: dict[str, Any]

    # Final output
    report: str
    synthesis_mode: str

    # Parallel branches can both append errors.
    errors: Annotated[list[str], operator.add]
