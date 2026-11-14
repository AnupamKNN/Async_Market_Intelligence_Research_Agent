import pytest

from market_intelligence.orchestration.analyst import (
    _validate_narrative_claims,
)
from market_intelligence.schemas.analyst import (
    AnalystFindings,
    AnalyticalFinding,
)


def make_findings(
    executive_summary="Sales performance shows consistent activity.",
    finding="The leading products contribute meaningfully to sales.",
    business_implication="Inventory planning should consider these products.",
):
    return AnalystFindings(
        executive_summary=executive_summary,
        findings=[
            AnalyticalFinding(
                objective="Identify the top 5 products by revenue.",
                status="supported",
                finding=finding,
                supporting_fields=["internal_data.top_products[0].net_line_value"],
                business_implication=business_implication,
                limitation=None,
            )
        ],
        recommendations=["Review product-level inventory allocation."],
        limitations=["Monthly aggregation is unavailable."],
        confidence="medium",
    )


def test_accepts_qualitative_narrative():
    findings = make_findings()

    _validate_narrative_claims(findings)


@pytest.mark.parametrize(
    "text",
    [
        "Revenue reached $1,200.",
        "Contribution was 8.4%.",
        "Sales increased by 53,628 units.",
        "The top five products dominate sales.",
        "Products generated one million dollars.",
    ],
)
def test_rejects_numerical_claims_in_executive_summary(text):
    findings = make_findings(executive_summary=text)

    with pytest.raises(ValueError, match="numerical claims"):
        _validate_narrative_claims(findings)


def test_rejects_numerical_claims_in_business_implication():
    findings = make_findings(business_implication="Focus on the five leading products.")

    with pytest.raises(ValueError, match="numerical claims"):
        _validate_narrative_claims(findings)


def test_rejects_numerical_claims_in_recommendations():
    findings = make_findings()
    findings.recommendations = ["Review the top five products."]

    with pytest.raises(ValueError, match="numerical claims"):
        _validate_narrative_claims(findings)


def test_allows_numbers_in_objectives_and_field_paths():
    findings = make_findings()

    _validate_narrative_claims(findings)
