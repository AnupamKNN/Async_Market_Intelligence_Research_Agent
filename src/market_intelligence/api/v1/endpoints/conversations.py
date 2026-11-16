from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from market_intelligence.api.v1.dependencies import (
    get_authenticated_session,
)
from market_intelligence.db.repositories.conversations import (
    get_research_conversation_for_user,
    list_conversation_jobs,
    list_research_conversations,
)
from market_intelligence.schemas.conversations import (
    ResearchConversationDetail,
    ResearchConversationResponse,
)

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get("", response_model=list[ResearchConversationResponse])
async def get_conversations(
    request: Request,
    session: Annotated[
        asyncpg.Record,
        Depends(get_authenticated_session),
    ],
) -> list[ResearchConversationResponse]:
    """List conversations belonging to the authenticated user."""

    conversations = await list_research_conversations(
        request.app.state.db_pool,
        session["user_id"],
    )

    return [ResearchConversationResponse(**conversation) for conversation in conversations]


@router.get(
    "/{conversation_id}",
    response_model=ResearchConversationDetail,
)
async def get_conversation(
    conversation_id: UUID,
    request: Request,
    session: Annotated[
        asyncpg.Record,
        Depends(get_authenticated_session),
    ],
) -> ResearchConversationDetail:
    """Retrieve a conversation and its research turns."""

    pool = request.app.state.db_pool
    user_id = session["user_id"]

    conversation = await get_research_conversation_for_user(
        pool,
        conversation_id,
        user_id,
    )

    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    jobs = await list_conversation_jobs(
        pool,
        conversation_id,
        user_id,
    )

    return ResearchConversationDetail(
        **conversation,
        jobs=jobs,
    )
