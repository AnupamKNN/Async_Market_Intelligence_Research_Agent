import logging
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from market_intelligence.api.v1.dependencies import (
    get_authenticated_session,
    validate_csrf,
)
from market_intelligence.db.repositories.conversations import (
    ConversationHasRunningJobsError,
    delete_research_conversation,
    get_research_conversation_for_user,
    list_conversation_jobs,
    list_research_conversations,
    rename_research_conversation,
)
from market_intelligence.schemas.conversations import (
    ResearchConversationDetail,
    ResearchConversationRename,
    ResearchConversationResponse,
)
from market_intelligence.services.research_queue import event_stream_key

router = APIRouter(prefix="/conversations", tags=["Conversations"])

logger = logging.getLogger(__name__)


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


@router.patch(
    "/{conversation_id}",
    response_model=ResearchConversationResponse,
)
async def rename_conversation(
    conversation_id: UUID,
    payload: ResearchConversationRename,
    request: Request,
    session: Annotated[
        asyncpg.Record,
        Depends(get_authenticated_session),
    ],
) -> ResearchConversationResponse:
    """Rename a conversation owned by the authenticated user."""

    validate_csrf(request, session)

    conversation = await rename_research_conversation(
        request.app.state.db_pool,
        conversation_id,
        session["user_id"],
        payload.title,
    )

    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    return ResearchConversationResponse(**conversation)


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation(
    conversation_id: UUID,
    request: Request,
    session: Annotated[
        asyncpg.Record,
        Depends(get_authenticated_session),
    ],
) -> Response:
    """Delete a user's conversation and all associated research history."""

    validate_csrf(request, session)

    try:
        deleted_job_ids = await delete_research_conversation(
            request.app.state.db_pool,
            conversation_id,
            session["user_id"],
        )

    except ConversationHasRunningJobsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    if deleted_job_ids is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    # Database deletion is authoritative. Redis event-stream cleanup
    # is best-effort because the event streams also have a TTL.
    if deleted_job_ids:
        redis = request.app.state.redis

        event_keys = [
            event_stream_key(job_id)
            for job_id in deleted_job_ids
        ]

        try:
            await redis.delete(*event_keys)
        except Exception:
            logger.warning(
                "Conversation %s was deleted, but its Redis event streams "
                "could not be cleaned up.",
                conversation_id,
                exc_info=True,
            )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
