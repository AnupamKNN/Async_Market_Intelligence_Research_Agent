from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from market_intelligence.schemas.research import ResearchJobResponse


class ResearchConversationResponse(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    job_count: int
    last_message_at: datetime | None = None


class ResearchConversationDetail(ResearchConversationResponse):
    jobs: list[ResearchJobResponse]


class ResearchConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = " ".join(value.split())

        if not title:
            raise ValueError("Conversation title cannot be empty.")

        return title
