from market_intelligence.schemas.research import (
    ResearchJobRevisionRequest,
    ResearchRequest,
)


def test_research_request_defaults_to_internal_only():
    request = ResearchRequest(question="Analyze monthly retail sales trends.")

    assert request.requested_sources == ["internal"]


def test_research_request_preserves_explicit_external_sources():
    request = ResearchRequest(
        question="Compare retail performance with current economic trends.",
        requested_sources=["internal", "external"],
        fred_series_ids=["CPIAUCSL"],
    )

    assert request.requested_sources == ["internal", "external"]
    assert request.fred_series_ids == ["CPIAUCSL"]

def test_research_request_leaves_product_limit_unspecified_by_default():
    request = ResearchRequest(
        question="Analyze monthly retail sales trends."
    )

    assert request.product_limit is None


def test_research_request_accepts_explicit_product_limit():
    request = ResearchRequest(
        question="Analyze retail sales.",
        product_limit=20,
    )

    assert request.product_limit == 20

def test_revision_request_accepts_explicit_product_limit():
    request = ResearchJobRevisionRequest(
        question="Identify the top 20 products.",
        product_limit=20,
    )

    assert request.product_limit == 20