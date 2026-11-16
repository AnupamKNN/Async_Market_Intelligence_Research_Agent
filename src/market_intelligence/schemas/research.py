from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    question: str = Field(min_length=10, max_length=5000)

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
    product_limit: int = Field(default=5, ge=1, le=50)


class ResearchJobAccepted(BaseModel):
    job_id: UUID
    conversation_id: UUID
    status: Literal["queued"]
    status_url: str
    events_url: str


class ResearchJobResponse(BaseModel):
    job_id: UUID
    question: str
    status: Literal["queued", "running", "completed", "failed"]
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
