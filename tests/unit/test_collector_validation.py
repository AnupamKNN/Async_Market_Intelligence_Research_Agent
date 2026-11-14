import pytest

from market_intelligence.orchestration.collector import (
    _normalize_and_validate_evidence_references,
)
from market_intelligence.schemas.collector import (
    CollectorFindings,
    ObjectiveAssessment,
)


def make_findings(evidence_ids=None, internal_sources=None):
    return CollectorFindings(
        retrieved_sources=["internal", "gnews"],
        objective_assessments=[
            ObjectiveAssessment(
                objective="Analyze overall retail sales performance.",
                status="fulfilled",
                evidence_ids=evidence_ids or [],
                internal_sources=internal_sources or [],
                explanation="The retrieved evidence supports this objective.",
            )
        ],
        limitations=[],
        retrieval_warnings=[],
    )


def test_normalizes_internal_source_from_evidence_ids():
    findings = make_findings(evidence_ids=["sales_summary"])

    _normalize_and_validate_evidence_references(
        findings,
        {"sales_summary": {"net_line_value": "100"}},
        [],
    )

    assessment = findings.objective_assessments[0]

    assert assessment.evidence_ids == []
    assert assessment.internal_sources == ["sales_summary"]


def test_accepts_valid_internal_and_external_references():
    findings = make_findings(
        evidence_ids=["gnews-001"],
        internal_sources=["sales_summary"],
    )

    _normalize_and_validate_evidence_references(
        findings,
        {"sales_summary": {"net_line_value": "100"}},
        [{"evidence_id": "gnews-001"}],
    )

    assessment = findings.objective_assessments[0]

    assert assessment.evidence_ids == ["gnews-001"]
    assert assessment.internal_sources == ["sales_summary"]


def test_rejects_unknown_external_evidence_id():
    findings = make_findings(evidence_ids=["fabricated-id"])

    with pytest.raises(ValueError, match="unknown external evidence IDs"):
        _normalize_and_validate_evidence_references(
            findings,
            {},
            [],
        )


def test_rejects_unavailable_internal_source():
    findings = make_findings(internal_sources=["sales_summary"])

    with pytest.raises(ValueError, match="unavailable internal sources"):
        _normalize_and_validate_evidence_references(
            findings,
            {"dataset_overview": {}},
            [],
        )
