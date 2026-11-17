import json
from typing import Annotated
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from market_intelligence.api.v1.dependencies import (
    get_authenticated_session,
    validate_csrf,
)
from market_intelligence.db.repositories.conversations import (
    create_research_conversation,
    get_research_conversation_for_user,
    touch_research_conversation,
)
from market_intelligence.db.repositories.research_jobs import (
    create_research_job,
    fail_research_job,
    get_research_job_for_user,
)
from market_intelligence.schemas.research import (
    ResearchJobAccepted,
    ResearchJobResponse,
    ResearchRequest,
)
from market_intelligence.services.research_queue import (
    QUEUE_STREAM,
    event_stream_key,
    publish_job_event,
)

router = APIRouter(prefix="/research", tags=["Research"])


@router.post(
    "/jobs",
    response_model=ResearchJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_research(
    payload: ResearchRequest,
    request: Request,
    session: Annotated[
        asyncpg.Record,
        Depends(get_authenticated_session),
    ],
) -> ResearchJobAccepted:
    """Create a research job for the authenticated user."""

    validate_csrf(request, session)

    pool = request.app.state.db_pool
    redis = request.app.state.redis

    job_id = uuid4()
    user_id = session["user_id"]

    job_payload = payload.model_dump(
        mode="json",
        exclude_none=True,
    )

    # The conversation ID is metadata for the API/database.
    # It must not be passed into the LangGraph worker payload.
    conversation_id = job_payload.pop("conversation_id", None)

    if conversation_id is None:
        conversation_id = uuid4()

        title = " ".join(payload.question.split())

        if len(title) > 80:
            title = title[:77].rstrip() + "..."

        await create_research_conversation(
            pool,
            conversation_id,
            user_id,
            title,
        )
    else:
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

        await touch_research_conversation(
            pool,
            conversation_id,
            user_id,
        )

    await create_research_job(
        pool,
        job_id,
        job_payload,
        user_id,
        conversation_id=conversation_id,
    )

    try:
        await redis.xadd(
            QUEUE_STREAM,
            {
                "job_id": str(job_id),
                "payload": json.dumps(job_payload, ensure_ascii=False),
            },
        )

    except Exception as exc:
        await fail_research_job(
            pool,
            job_id,
            "Unable to enqueue research job.",
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to enqueue the research job.",
        ) from exc

    await publish_job_event(
        redis,
        job_id,
        "queued",
        {"message": "Research job accepted."},
    )

    return ResearchJobAccepted(
        job_id=job_id,
        conversation_id=conversation_id,
        status="queued",
        status_url=f"/api/v1/research/jobs/{job_id}",
        events_url=f"/api/v1/research/jobs/{job_id}/events",
    )


@router.get(
    "/jobs/{job_id}",
    response_model=ResearchJobResponse,
)
async def retrieve_research_job(
    job_id: UUID,
    request: Request,
    session: Annotated[
        asyncpg.Record,
        Depends(get_authenticated_session),
    ],
) -> ResearchJobResponse:
    """Retrieve a research job belonging to the authenticated user."""

    job = await get_research_job_for_user(
        request.app.state.db_pool,
        job_id,
        session["user_id"],
    )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research job not found.",
        )

    return ResearchJobResponse(**job)


@router.get("/jobs/{job_id}/events")
async def stream_research_events(
    job_id: UUID,
    request: Request,
    session: Annotated[
        asyncpg.Record,
        Depends(get_authenticated_session),
    ],
) -> StreamingResponse:
    """Stream events only to the owner of the research job."""

    pool = request.app.state.db_pool
    user_id = session["user_id"]

    job = await get_research_job_for_user(
        pool,
        job_id,
        user_id,
    )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research job not found.",
        )

    redis = request.app.state.redis

    async def event_generator():
        stream = event_stream_key(job_id)
        last_id = "0-0"

        while True:
            if await request.is_disconnected():
                break

            records = await redis.xread(
                {stream: last_id},
                count=50,
                block=10_000,
            )

            if not records:
                current = await get_research_job_for_user(
                    pool,
                    job_id,
                    user_id,
                )

                if current and current["status"] in {"completed", "failed"}:
                    break

                yield ": keep-alive\n\n"
                continue

            for _, messages in records:
                for message_id, fields in messages:
                    last_id = message_id

                    event_name = fields.get("event", "progress")
                    data = fields.get("data", "{}")

                    yield (f"id: {message_id}\nevent: {event_name}\ndata: {data}\n\n")

                    if event_name in {"completed", "failed"}:
                        return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
