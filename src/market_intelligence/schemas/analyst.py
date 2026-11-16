"""Structured output schema for the quantitative analyst agent."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AnalyticalFinding(BaseModel):
    """An evidence-backed analytical finding."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    objective: str = Field(min_length=5, max_length=180)

    status: Literal[
        "supported",
        "partially_supported",
        "unsupported",
    ]

    finding: str = Field(min_length=1, max_length=700)

    supporting_fields: list[str] = Field(
        max_length=5,
        description=(
            "Return at most five distinct, exact source field paths "
            "that directly support this finding. "
            "Select only the most relevant fields. "
            "Never repeat a field path or enumerate every available field. "
            "Return an empty array [] when no supporting fields exist. "
            "Never return null. "
            "Do not modify field paths or invent references."
        ),
    )

    business_implication: str = Field(min_length=1, max_length=500)

    limitation: str | None = Field(
        ...,
        max_length=400,
        description=(
            "Limitation affecting this finding. Return null when no specific limitation applies."
        ),
    )


class AnalystFindings(BaseModel):
    """Consolidated analytical interpretation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    executive_summary: str = Field(min_length=1, max_length=1200)

    findings: list[AnalyticalFinding] = Field(
        min_length=1,
        max_length=8,
    )

    recommendations: list[str] = Field(
        max_length=8,
        description=(
            "Evidence-grounded business recommendations. "
            "Return [] when no recommendations are justified. "
            "Never return null."
        ),
    )

    limitations: list[str] = Field(
        max_length=10,
        description=(
            "Known research and analytical limitations. "
            "Return [] when there are no additional limitations. "
            "Never return null."
        ),
    )

    confidence: Literal["high", "medium", "low"]


class AnalystStructuredFinding(BaseModel):
    """Groq-compatible structured finding."""

    model_config = ConfigDict(extra="forbid")

    objective: str
    status: Literal["supported", "partially_supported", "unsupported"]
    finding: str
    business_implication: str
    limitation: str | None


class AnalystStructuredOutput(BaseModel):
    """Strict LLM response schema, validated again by AnalystFindings."""

    model_config = ConfigDict(extra="forbid")

    executive_summary: str
    findings: list[AnalystStructuredFinding]
    recommendations: list[str]
    limitations: list[str]
    confidence: Literal["high", "medium", "low"]
