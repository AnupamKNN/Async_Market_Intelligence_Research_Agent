"""Structured output schema for the research collector agent."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CollectorObjectiveResponse(BaseModel):
    """LLM-facing response; internal source attribution is deterministic."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    objective: str = Field(min_length=5, max_length=180)

    status: Literal[
        "fulfilled",
        "partially_fulfilled",
        "unsupported",
    ]

    evidence_ids: list[str] = Field(
        default_factory=list,
        description=(
            "External evidence IDs only. Use exact evidence_id values "
            "from retrieved external evidence."
        ),
    )

    explanation: str = Field(min_length=1, max_length=800)


class ObjectiveAssessment(BaseModel):
    """Evidence-based assessment of an assigned research objective."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    objective: str = Field(min_length=5, max_length=180)

    status: Literal[
        "fulfilled",
        "partially_fulfilled",
        "unsupported",
    ]

    evidence_ids: list[str] = Field(
        default_factory=list,
        description=(
            "External evidence IDs only. Use exact evidence_id values "
            "from retrieved external evidence. Never put internal source "
            "names in this field."
        ),
    )

    internal_sources: list[
        Literal["dataset_overview", "sales_summary", "top_products", "monthly_sales_analysis"]
    ] = Field(
        default_factory=list,
        description=(
            "Internal analytics source names used for this assessment. "
            "Use exact available source names. Never return evidence IDs here."
        ),
    )

    explanation: str = Field(min_length=1, max_length=800)


class CollectorFindings(BaseModel):
    """Consolidated findings and evidence coverage from collection."""

    model_config = ConfigDict(extra="forbid")

    retrieved_sources: list[Literal["internal", "fred", "gnews"]]

    objective_assessments: list[ObjectiveAssessment]

    limitations: list[str] = Field(default_factory=list)

    retrieval_warnings: list[str] = Field(default_factory=list)
