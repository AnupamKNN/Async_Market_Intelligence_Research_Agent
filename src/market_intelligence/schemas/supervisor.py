"""Structured output schema for the LLM research supervisor."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ResearchSource = Literal["internal", "external"]

FREDSeriesID = Annotated[
    str,
    Field(
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z0-9_]+$",
    ),
]

AnalysisObjective = Annotated[
    str,
    Field(min_length=5, max_length=180),
]


class SupervisorPlan(BaseModel):
    """Validated research execution plan produced by the LLM supervisor."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    sources: list[ResearchSource] = Field(
        default_factory=list,
        min_length=1,
        max_length=2,
        description="Research sources to activate.",
    )

    fred_series_ids: list[FREDSeriesID] = Field(
        default_factory=list,
        max_length=8,
        description="Relevant FRED economic series identifiers.",
    )

    news_query: str | None = Field(
        default=None,
        max_length=200,
        description="Focused search query for external market news.",
    )

    analysis_objectives: list[AnalysisObjective] = Field(
        default_factory=list,
        max_length=8,
        description="Specific analytical objectives for the research workflow.",
    )

    rationale: str = Field(
        default="",
        description="Brief explanation of the selected research strategy.",
    )

    @model_validator(mode="after")
    def validate_retrieval_plan(self):
        """Ensure that the selected sources have valid retrieval targets."""

        if not self.sources:
            return self

        if len(set(self.sources)) != len(self.sources):
            raise ValueError("Research sources must be unique.")

        has_external_targets = bool(self.fred_series_ids or self.news_query)

        if "external" in self.sources and not has_external_targets:
            raise ValueError("External research requires FRED series IDs or a news query.")

        if "external" not in self.sources and has_external_targets:
            raise ValueError("External retrieval targets require the external source.")

        return self
