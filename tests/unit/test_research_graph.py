"""Unit tests for deterministic research graph planning and utilities."""

import pytest

from market_intelligence.orchestration.graph import (
    _parse_tool_output,
    _plan_research,
)


def test_internal_only_research_plan():
    plan = _plan_research(
        {
            "question": "Analyze retail sales performance.",
            "requested_sources": ["internal"],
        }
    )

    assert plan["retrieval_mode"] == "internal_only"
    assert plan["include_internal"] is True
    assert plan["include_external"] is False
    assert plan["include_news"] is False
    assert plan["planned_fred_series"] == []


def test_external_inflation_plan_selects_cpi():
    plan = _plan_research(
        {
            "question": "Analyze inflation trends.",
            "requested_sources": ["external"],
        }
    )

    assert plan["retrieval_mode"] == "external_only"
    assert plan["include_external"] is True
    assert plan["planned_fred_series"] == ["CPIAUCSL"]
    assert plan["include_news"] is False


def test_mixed_research_plan_selects_internal_and_external_sources():
    plan = _plan_research(
        {
            "question": "Compare retail sales with inflation news.",
            "requested_sources": ["internal", "external"],
        }
    )

    assert plan["retrieval_mode"] == "mixed"
    assert plan["include_internal"] is True
    assert plan["include_external"] is True
    assert plan["include_news"] is True
    assert plan["planned_fred_series"] == ["CPIAUCSL", "RSAFS"]
    assert plan["planned_news_query"] == 'inflation OR "retail sales"'


def test_explicit_fred_series_are_deduplicated():
    plan = _plan_research(
        {
            "question": "Compare macroeconomic indicators.",
            "requested_sources": ["external"],
            "fred_series_ids": ["UNRATE", "UNRATE", "CPIAUCSL"],
            "news_query": "US labor market and inflation",
        }
    )

    assert plan["planned_fred_series"] == ["UNRATE", "CPIAUCSL"]
    assert plan["include_news"] is True
    assert plan["planned_news_query"] == "US labor market and inflation"


def test_ambiguous_question_defaults_to_internal_analytics():
    plan = _plan_research({"question": "Give me an overview."})

    assert plan["retrieval_mode"] == "internal_only"
    assert plan["include_internal"] is True
    assert plan["include_external"] is False


def test_empty_question_is_rejected():
    with pytest.raises(ValueError, match="non-empty research question"):
        _plan_research({"question": "   "})


def test_unsupported_source_is_rejected():
    with pytest.raises(ValueError, match="Unsupported requested_sources"):
        _plan_research(
            {
                "question": "Analyze retail performance.",
                "requested_sources": ["internal", "web"],
            }
        )


def test_empty_requested_sources_are_rejected():
    with pytest.raises(ValueError, match="cannot be empty"):
        _plan_research(
            {
                "question": "Analyze retail performance.",
                "requested_sources": [],
            }
        )


def test_invalid_date_range_is_rejected():
    with pytest.raises(ValueError, match="start_date cannot be later"):
        _plan_research(
            {
                "question": "Analyze retail performance.",
                "requested_sources": ["internal"],
                "start_date": "2011-01-01",
                "end_date": "2010-01-01",
            }
        )


def test_parse_tool_output_unwraps_mcp_result():
    result = _parse_tool_output('{"result": [{"stock_code": "22423"}]}')

    assert result == [{"stock_code": "22423"}]


def test_parse_tool_output_accepts_json_arrays():
    result = _parse_tool_output('[{"value": 10}]')

    assert result == [{"value": 10}]


def test_parse_tool_output_rejects_invalid_json():
    with pytest.raises(ValueError, match="invalid JSON"):
        _parse_tool_output("{invalid json}")


def test_parse_tool_output_rejects_unexpected_types():
    with pytest.raises(TypeError, match="Unexpected MCP tool result type"):
        _parse_tool_output(123)
