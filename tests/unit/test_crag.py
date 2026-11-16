from market_intelligence.services.crag import (
    assess_crag_quality,
    build_corrective_news_query,
)


def test_crag_accepts_comparison_candidates():
    result = assess_crag_quality(
        {"comparison_candidates": 2, "records": []},
        include_external=True,
        include_news=True,
        planned_news_query="retail sales",
        attempts=0,
    )

    assert result["status"] == "sufficient"
    assert result["should_retry"] is False


def test_crag_accepts_relevant_context_without_date_alignment():
    result = assess_crag_quality(
        {
            "comparison_candidates": 0,
            "records": [
                {
                    "citation_valid": True,
                    "topical_relevance": {"status": "matched"},
                    "geographic_relevance": {"status": "not_requested"},
                }
            ],
        },
        include_external=True,
        include_news=True,
        planned_news_query="retail sales",
        attempts=0,
    )

    assert result["status"] == "context_only"
    assert result["should_retry"] is False


def test_crag_requests_retry_for_unsuitable_evidence():
    result = assess_crag_quality(
        {
            "comparison_candidates": 0,
            "records": [],
        },
        include_external=True,
        include_news=True,
        planned_news_query="retail sales",
        attempts=0,
    )

    assert result["status"] == "retry_required"
    assert result["should_retry"] is True


def test_crag_stops_after_maximum_retries():
    result = assess_crag_quality(
        {
            "comparison_candidates": 0,
            "records": [],
        },
        include_external=True,
        include_news=True,
        planned_news_query="retail sales",
        attempts=2,
    )

    assert result["status"] == "retry_exhausted"
    assert result["should_retry"] is False


def test_crag_skips_when_external_research_is_disabled():
    result = assess_crag_quality(
        {},
        include_external=False,
        include_news=False,
        planned_news_query=None,
        attempts=0,
    )

    assert result["status"] == "skipped"
    assert result["should_retry"] is False


def test_corrective_query_preserves_research_intent():
    query = build_corrective_news_query(
        question="Analyze retail market conditions",
        original_query="retail market conditions",
        target_geography="United States",
        attempt=1,
        reason="No topically relevant evidence was found.",
    )

    assert "retail market conditions" in query
    assert "United States" in query
    assert len(query) <= 200


def test_corrective_query_changes_between_attempts():
    first = build_corrective_news_query(
        question="Analyze retail market conditions",
        original_query="retail market conditions",
        target_geography="United States",
        attempt=1,
        reason="No suitable evidence was found.",
    )

    second = build_corrective_news_query(
        question="Analyze retail market conditions",
        original_query="retail market conditions",
        target_geography="United States",
        attempt=2,
        reason="No suitable evidence was found.",
    )

    assert first != second
