"""Tests for temporal and relevance-aware research evaluation."""

import pytest

from market_intelligence.services.research_quality import (
    assess_evidence_record,
    build_fred_date_arguments,
    derive_dataset_window,
    grade_evidence_records,
    infer_target_geography,
)


@pytest.fixture
def dataset_overview():
    return {
        "first_transaction": "2009-12-01 07:45:00",
        "last_transaction": "2011-12-09 12:50:00",
    }


@pytest.fixture
def fred_record():
    return {
        "evidence_id": "ev_1234567890abcdef12345678",
        "provider": "FRED",
        "evidence_type": "economic_series",
        "title": "Consumer Price Index",
        "publisher": "Federal Reserve Bank of St. Louis (FRED)",
        "source_url": "https://fred.stlouisfed.org/series/CPIAUCSL",
        "retrieved_at": "2026-11-05T10:00:00+00:00",
        "observation_start": "2010-01-01",
        "observation_end": "2010-01-01",
        "data": {
            "series_id": "CPIAUCSL",
            "observation_date": "2010-01-01",
            "value": "216.687",
            "source_units": "Index 1982-1984=100",
        },
        "trust_boundary": "untrusted_external",
    }


@pytest.fixture
def current_news_record():
    return {
        "evidence_id": "ev_abcdef1234567890abcdef12",
        "provider": "GNews",
        "evidence_type": "news_article",
        "title": "US inflation and consumer prices",
        "publisher": "Example Financial News",
        "source_url": "https://example.com/us-inflation",
        "retrieved_at": "2026-11-05T10:00:00+00:00",
        "published_at": "2026-11-04T10:00:00+00:00",
        "excerpt": "US inflation and consumer price trends.",
        "data": {},
        "trust_boundary": "untrusted_external",
    }


def test_dataset_window_from_database_metadata(dataset_overview):
    window = derive_dataset_window(dataset_overview)

    assert window.start_date.isoformat() == "2009-12-01"
    assert window.end_date.isoformat() == "2011-12-09"


def test_fred_arguments_align_to_dataset(dataset_overview):
    arguments = build_fred_date_arguments(dataset_overview)

    assert arguments["observation_start"] == "2009-12-01"
    assert arguments["observation_end"] == "2011-12-09"
    assert arguments["sort_order"] == "asc"
    assert arguments["limit"] == 1000


def test_fred_requested_window_is_intersected(dataset_overview):
    arguments = build_fred_date_arguments(
        dataset_overview,
        requested_start="2010-01-01",
        requested_end="2012-01-01",
    )

    assert arguments["observation_start"] == "2010-01-01"
    assert arguments["observation_end"] == "2011-12-09"


def test_rejects_non_overlapping_date_range(dataset_overview):
    with pytest.raises(ValueError, match="does not overlap"):
        build_fred_date_arguments(
            dataset_overview,
            requested_start="2026-01-01",
            requested_end="2026-12-31",
        )


def test_infers_us_geography():
    assert infer_target_geography("Compare US inflation with retail sales.") == "United States"


def test_fred_evidence_is_comparable(
    fred_record,
    dataset_overview,
):
    result = assess_evidence_record(
        fred_record,
        question="Compare US inflation with retail sales.",
        dataset_window=derive_dataset_window(dataset_overview),
        target_geography="United States",
    )

    assert result["citation_valid"] is True
    assert result["topical_relevance"]["status"] == "matched"
    assert result["geographic_relevance"]["status"] == "matched"
    assert result["temporal_alignment"]["status"] == "aligned"
    assert result["comparison_eligible"] is True


def test_recent_news_is_context_only(
    current_news_record,
    dataset_overview,
):
    result = assess_evidence_record(
        current_news_record,
        question="Compare US inflation with retail sales.",
        dataset_window=derive_dataset_window(dataset_overview),
        target_geography="United States",
    )

    assert result["citation_valid"] is True
    assert result["temporal_alignment"]["status"] == ("after_dataset_context_only")
    assert result["comparison_eligible"] is False
    assert result["recommended_usage"] == "context_only"


def test_grader_separates_citation_and_comparability(
    fred_record,
    current_news_record,
    dataset_overview,
):
    result = grade_evidence_records(
        [fred_record, current_news_record],
        question="Compare US inflation with retail sales.",
        dataset_overview=dataset_overview,
        target_geography="United States",
    )

    assert result["total_records"] == 2
    assert result["citation_valid"] == 2
    assert result["comparison_candidates"] == 1
    assert result["context_only"] == 1
    assert result["citation_coverage"] == 1.0


def test_rejects_invalid_source_scheme(
    fred_record,
    dataset_overview,
):
    fred_record["source_url"] = "javascript:alert(1)"

    result = assess_evidence_record(
        fred_record,
        question="US inflation",
        dataset_window=derive_dataset_window(dataset_overview),
        target_geography="United States",
    )

    assert result["citation_valid"] is False
    assert result["comparison_eligible"] is False
    assert result["recommended_usage"] == "rejected"
