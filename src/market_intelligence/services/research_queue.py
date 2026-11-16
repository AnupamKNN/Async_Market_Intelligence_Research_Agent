import json
from typing import Any
from uuid import UUID

QUEUE_STREAM = "mi:research:jobs"
QUEUE_GROUP = "mi:research:workers"
EVENT_TTL_SECONDS = 86_400


def event_stream_key(job_id: UUID) -> str:
    return f"mi:research:events:{job_id}"


async def publish_job_event(
    redis: Any,
    job_id: UUID,
    event: str,
    data: dict[str, Any],
) -> None:
    stream = event_stream_key(job_id)

    await redis.xadd(
        stream,
        {
            "event": event,
            "data": json.dumps(data, default=str, ensure_ascii=False),
        },
        maxlen=500,
        approximate=True,
    )

    await redis.expire(stream, EVENT_TTL_SECONDS)
