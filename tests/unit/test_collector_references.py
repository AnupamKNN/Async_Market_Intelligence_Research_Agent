import pytest

from market_intelligence.orchestration.collector import (
    _normalize_and_validate_evidence_references,
)
from market_intelligence.schemas.collector import (
    CollectorFindings,
    ObjectiveAssessment,
)


def make_findings(evidence_ids: list[str]) -> CollectorFindings:
    return CollectorFindings(
        retrieved_sources=["internal"],
        objective_assessments=[
            ObjectiveAssessment(
                objective="Analyze monthly retail sales",
                status="partially_fulfilled",
                evidence_ids=evidence_ids,
                internal_sources=[],
                explanation="Monthly observations were retrieved.",
            )
        ],
    )


def test_month_labels_are_recovered_as_internal_references():
    findings = make_findings(["2010-01", "2010-02"])

    internal_data = {
        "monthly_sales_analysis": {
            "monthly_trend": [
                {"month": "2010-01"},
                {"month": "2010-02"},
            ]
        }
    }

    _normalize_and_validate_evidence_references(
        findings,
        internal_data,
        [],
    )

    assessment = findings.objective_assessments[0]

    assert assessment.evidence_ids == []
    assert assessment.internal_sources == ["monthly_sales_analysis"]


def test_valid_external_evidence_ids_are_preserved():
    findings = make_findings(["fred_123"])

    _normalize_and_validate_evidence_references(
        findings,
        {"sales_summary": {"net_line_value": "1000"}},
        [{"evidence_id": "fred_123"}],
    )

    assert findings.objective_assessments[0].evidence_ids == ["fred_123"]


def test_unknown_external_evidence_ids_are_rejected():
    findings = make_findings(["invented_evidence_id"])

    with pytest.raises(ValueError, match="unknown external evidence IDs"):
        _normalize_and_validate_evidence_references(
            findings,
            {"sales_summary": {"net_line_value": "1000"}},
            [],
        )
