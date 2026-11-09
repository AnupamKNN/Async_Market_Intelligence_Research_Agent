"""Tests for FRED and GNews evidence normalization."""

import pytest
from pydantic import ValidationError

from market_intelligence.services.evidence_normalizer import (
    normalize_fred_response,
    normalize_gnews_response,
)


@pytest.fixture
def fred_response():
    return {
        "provider": "Federal Reserve Bank of St. Louis - FRED",
        "source_url": "https://fred.stlouisfed.org/series/UNRATE",
        "retrieved_at_utc": "2026-11-05T10:58:24+00:00",
        "series": {
            "id": "UNRATE",
            "title": "Unemployment Rate",
            "frequency": "Monthly",
            "units": "Percent",
            "seasonal_adjustment": "Seasonally Adjusted",
        },
        "requested_transformation": "lin",
        "observations": [
            {"date": "2026-09-01", "value": "4.2"},
            {"date": "2026-08-01", "value": "4.1"},
            {"date": "2026-07-01", "value": "4.1"},
        ],
    }


@pytest.fixture
def gnews_response():
    return {
        "provider": "GNews",
        "query": "Federal Reserve interest rates",
        "language": "en",
        "country_filter": None,
        "sort_by": "publishedAt",
        "retrieved_at_utc": "2026-11-05T10:58:24+00:00",
        "total_articles_available": 100,
        "articles": [
            {
                "title": "Central bank holds interest rates",
                "description": "A sample financial news summary.",
                "content_excerpt": "A sample news excerpt.",
                "url": "https://example.com/article-1",
                "published_at": "2026-11-04T22:56:21Z",
                "publisher": "Example Financial News",
                "publisher_url": "https://example.com",
            }
        ],
    }


def test_fred_normalizes_each_observation(fred_response):
    bundle = normalize_fred_response(fred_response)

    assert bundle.provider == "FRED"
    assert bundle.returned_count == 3
    assert bundle.items[0].title == "Unemployment Rate"
    assert bundle.items[0].data["value"] == "4.2"
    assert bundle.items[0].data["observation_date"] == "2026-09-01"
    assert bundle.items[0].published_at is None
    assert bundle.items[0].trust_boundary == "untrusted_external"


def test_fred_preserves_source_metadata(fred_response):
    bundle = normalize_fred_response(fred_response)
    record = bundle.items[0]

    assert record.publisher == "Federal Reserve Bank of St. Louis (FRED)"
    assert str(record.source_url) == ("https://fred.stlouisfed.org/series/UNRATE")
    assert record.data["frequency"] == "Monthly"
    assert record.data["source_units"] == "Percent"


def test_fred_evidence_ids_are_stable(fred_response):
    first = normalize_fred_response(fred_response)
    second = normalize_fred_response(fred_response)

    first_ids = [item.evidence_id for item in first.items]
    second_ids = [item.evidence_id for item in second.items]

    assert first_ids == second_ids
    assert len(set(first_ids)) == 3


def test_gnews_normalizes_article_and_citation(gnews_response):
    bundle = normalize_gnews_response(gnews_response)
    record = bundle.items[0]

    assert bundle.provider == "GNews"
    assert bundle.returned_count == 1
    assert bundle.total_available == 100

    assert record.title == "Central bank holds interest rates"
    assert record.publisher == "Example Financial News"
    assert str(record.source_url) == "https://example.com/article-1"
    assert record.published_at.isoformat() == ("2026-11-04T22:56:21+00:00")
    assert record.trust_boundary == "untrusted_external"

    citation = bundle.citation_index()[0]
    assert citation.evidence_id == record.evidence_id
    assert citation.publisher == record.publisher
    assert citation.source_url == record.source_url


def test_gnews_evidence_id_is_stable(gnews_response):
    first = normalize_gnews_response(gnews_response)
    second = normalize_gnews_response(gnews_response)

    assert first.items[0].evidence_id == second.items[0].evidence_id


def test_gnews_rejects_invalid_article_url(gnews_response):
    gnews_response["articles"][0]["url"] = "not-a-valid-url"

    with pytest.raises(ValidationError):
        normalize_gnews_response(gnews_response)


def test_gnews_rejects_naive_publication_timestamp(gnews_response):
    gnews_response["articles"][0]["published_at"] = "2026-11-04T22:56:21"

    with pytest.raises(ValueError, match="timezone"):
        normalize_gnews_response(gnews_response)


def test_fred_rejects_unexpected_provider(fred_response):
    fred_response["provider"] = "Unknown Provider"

    with pytest.raises(ValueError, match="provider"):
        normalize_fred_response(fred_response)


def test_gnews_rejects_unexpected_provider(gnews_response):
    gnews_response["provider"] = "Unknown Provider"

    with pytest.raises(ValueError, match="provider"):
        normalize_gnews_response(gnews_response)
