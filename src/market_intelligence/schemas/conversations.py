from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

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
