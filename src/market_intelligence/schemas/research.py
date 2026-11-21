from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ResearchRequest(BaseModel):
    question: str = Field(max_length=5000)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Question cannot be empty.")

        return value

    conversation_id: UUID | None = None

    requested_sources: list[Literal["internal", "external"]] = Field(
        default_factory=lambda: ["internal"],
        min_length=1,
    )

    start_date: date | None = None
    end_date: date | None = None
    fred_series_ids: list[str] = Field(default_factory=list)
    news_query: str | None = None
    max_articles: int = Field(default=5, ge=1, le=30)
    product_limit: int | None = Field(
        default=None,
        ge=1,
    )


class ResearchJobRevisionRequest(BaseModel):
    question: str = Field(max_length=5000)
    product_limit: int | None = Field(
        default=None,
        ge=1,
    )

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Question cannot be empty.")

        return value


class ResearchJobAccepted(BaseModel):
    job_id: UUID
    conversation_id: UUID
    status: Literal["queued"]
    status_url: str
    events_url: str


class ResearchJobResponse(BaseModel):
    job_id: UUID
    question: str
    status: Literal[
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class ResearchJobCancellationResponse(BaseModel):
    job_id: UUID
    status: Literal[
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]
    cancellation_requested: bool
