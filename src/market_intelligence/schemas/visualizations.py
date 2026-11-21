"""Validated chart schemas for research report visualizations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChartDataPoint(BaseModel):
    """One chart data point."""

    model_config = ConfigDict(extra="forbid")

    x: str = Field(min_length=1, max_length=200)
    y: float | None

    metadata: dict[
        str,
        str | int | float | bool | None,
    ] = Field(default_factory=dict)


class ChartSeries(BaseModel):
    """A named collection of chart data points."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)

    render_as: Literal["line", "bar", "scatter"] | None = None

    data: list[ChartDataPoint]


class ResearchChart(BaseModel):
    """Validated chart specification."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None

    chart_type: Literal["line", "bar"]

    x_axis_title: str
    y_axis_title: str

    series: list[ChartSeries]


class ResearchVisualizations(BaseModel):
    """Versioned visualization payload attached to a research result."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    charts: list[ResearchChart] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)