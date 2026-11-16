from market_intelligence.schemas.research import ResearchRequest


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
