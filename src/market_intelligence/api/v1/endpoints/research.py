import json
import logging
import re
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
    ResearchJobRevisionConflict,
    cancel_research_job_for_user,
    create_research_job,
    create_research_job_revision,
    get_research_job_for_user,
)
from market_intelligence.schemas.research import (
    ResearchJobAccepted,
    ResearchJobCancellationResponse,
    ResearchJobResponse,
    ResearchJobRevisionRequest,
    ResearchRequest,
)
from market_intelligence.services.conversation_titles import (
    build_conversation_title,
)
from market_intelligence.services.product_limits import resolve_product_limit
from market_intelligence.services.research_queue import (
    event_stream_key,
    publish_job_event,
)

router = APIRouter(prefix="/research", tags=["Research"])

logger = logging.getLogger(__name__)


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

    try:
        product_limit = resolve_product_limit(
            payload.question,
            payload.product_limit,
            max_limit=request.app.state.settings.analytics_max_result_rows,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    pool = request.app.state.db_pool

    job_id = uuid4()
    user_id = session["user_id"]

    job_payload = payload.model_dump(
        mode="json",
        exclude_none=True,
    )
    job_payload["product_limit"] = product_limit

    # The conversation ID is metadata for the API/database.
    # It must not be passed into the LangGraph worker payload.
    conversation_id = job_payload.pop("conversation_id", None)

    if conversation_id is None:
        conversation_id = uuid4()

        title = build_conversation_title(payload.question)

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

    # try:
    #     await redis.xadd(
    #         QUEUE_STREAM,
    #         {
    #             "job_id": str(job_id),
    #             "payload": json.dumps(job_payload, ensure_ascii=False),
    #         },
    #     )

    # except Exception as exc:
    #     await fail_research_job(
    #         pool,
    #         job_id,
    #         "Unable to enqueue research job.",
    #     )

    #     raise HTTPException(
    #         status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    #         detail="Unable to enqueue the research job.",
    #     ) from exc

    # await publish_job_event(
    #     redis,
    #     job_id,
    #     "queued",
    #     {"message": "Research job accepted."},
    # )

    return ResearchJobAccepted(
        job_id=job_id,
        conversation_id=conversation_id,
        status="queued",
        status_url=f"/api/v1/research/jobs/{job_id}",
        events_url=f"/api/v1/research/jobs/{job_id}/events",
    )


@router.post(
    "/jobs/{job_id}/revise",
    response_model=ResearchJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def revise_research_job(
    job_id: UUID,
    payload: ResearchJobRevisionRequest,
    request: Request,
    session: Annotated[
        asyncpg.Record,
        Depends(get_authenticated_session),
    ],
) -> ResearchJobAccepted:
    """
    Revise an existing conversational turn and enqueue a new execution.

    The previous execution remains stored for audit purposes.
    The new execution reuses the original conversational turn ID.
    """

    validate_csrf(request, session)

    try:
        product_limit = resolve_product_limit(
            payload.question,
            payload.product_limit,
            max_limit=request.app.state.settings.analytics_max_result_rows,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    new_job_id = uuid4()

    try:
        revision = await create_research_job_revision(
            pool=request.app.state.db_pool,
            new_job_id=new_job_id,
            original_job_id=job_id,
            question=payload.question,
            user_id=session["user_id"],
            product_limit=product_limit,
        )

    except ResearchJobRevisionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    if revision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research job not found.",
        )

    conversation_id, _turn_id, _revision_number = revision

    return ResearchJobAccepted(
        job_id=new_job_id,
        conversation_id=conversation_id,
        status="queued",
        status_url=f"/api/v1/research/jobs/{new_job_id}",
        events_url=f"/api/v1/research/jobs/{new_job_id}/events",
    )


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=ResearchJobCancellationResponse,
)
async def cancel_research_job(
    job_id: UUID,
    request: Request,
    session: Annotated[
        asyncpg.Record,
        Depends(get_authenticated_session),
    ],
) -> ResearchJobCancellationResponse:
    """Cancel a research job belonging to the authenticated user."""

    validate_csrf(request, session)

    pool = request.app.state.db_pool

    result = await cancel_research_job_for_user(
        pool,
        job_id,
        session["user_id"],
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research job not found.",
        )

    current_status, cancellation_requested = result

    # PostgreSQL is authoritative. Redis only distributes notifications.
    # Retry publishing the event for an already-cancelled job too.
    if current_status == "cancelled":
        try:
            await publish_job_event(
                request.app.state.redis,
                job_id,
                "cancelled",
                {
                    "message": "Research was cancelled.",
                    "status": "cancelled",
                },
            )
        except Exception:
            logger.exception(
                "Unable to publish cancellation event for job %s.",
                job_id,
            )

    return ResearchJobCancellationResponse(
        job_id=job_id,
        status=current_status,
        cancellation_requested=cancellation_requested,
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
    """Stream research events with cursor-based recovery."""

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

    # Native EventSource automatically supplies this header when
    # reconnecting after receiving an event containing an SSE id.
    last_event_id = request.headers.get("last-event-id", "").strip()

    if last_event_id and not re.fullmatch(r"\d+-\d+", last_event_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Last-Event-ID header.",
        )

    redis = request.app.state.redis

    async def event_generator():
        stream = event_stream_key(job_id)
        last_id = last_event_id or "0-0"

        while True:
            if await request.is_disconnected():
                break

            records = await redis.xread(
                {stream: last_id},
                count=50,
                block=10_000,
            )

            if records:
                for _, messages in records:
                    for message_id, fields in messages:
                        last_id = message_id

                        event_name = fields.get("event", "progress")
                        data = fields.get("data", "{}")

                        yield (f"id: {message_id}\nevent: {event_name}\ndata: {data}\n\n")

                        if event_name in {"completed", "failed", "cancelled"}:
                            return

                continue

            # Redis has no new events. Check PostgreSQL because it
            # is authoritative for the job's current status.
            current = await get_research_job_for_user(
                pool,
                job_id,
                user_id,
            )

            if current is None:
                return

            current_status = current["status"]

            if current_status in {"completed", "failed", "cancelled"}:
                if current_status == "completed":
                    message = "Research completed. Final state recovered from PostgreSQL."
                elif current_status == "cancelled":
                    message = "Research was cancelled."
                else:
                    message = (
                        current.get("error")
                        or "Research failed. Final state recovered from PostgreSQL."
                    )

                recovery_data = {
                    "message": message,
                    "status": current_status,
                    "recovered": True,
                }

                yield (
                    f"event: {current_status}\n"
                    f"data: {json.dumps(recovery_data, ensure_ascii=False)}\n\n"
                )

                return

            # The job is still active. Keep the connection open.
            yield ": keep-alive\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
