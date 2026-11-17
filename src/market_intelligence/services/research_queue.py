import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

QUEUE_STREAM = "mi:research:jobs"
QUEUE_GROUP = "mi:research:workers"

DEAD_LETTER_STREAM = "mi:research:jobs:dlq"

EVENT_TTL_SECONDS = 86_400
MAX_MALFORMED_DELIVERIES = 3
DLQ_DEDUPE_TTL_SECONDS = 30 * 24 * 60 * 60


_ACK_AND_DELETE_SCRIPT = """
local acknowledged = redis.call(
    'XACK',
    KEYS[1],
    ARGV[1],
    ARGV[2]
)

if acknowledged > 0 then
    redis.call('XDEL', KEYS[1], ARGV[2])
end

return acknowledged
"""


_DEAD_LETTER_SCRIPT = """
-- Confirm that the source message is still pending.
local pending = redis.call(
    'XPENDING',
    KEYS[3],
    ARGV[1],
    ARGV[2],
    ARGV[2],
    1
)

if #pending == 0 then
    return 0
end

-- Prevent duplicate dead-letter records if this operation is retried.
local inserted = redis.call(
    'SET',
    KEYS[2],
    '1',
    'EX',
    ARGV[6],
    'NX'
)

if inserted then
    redis.call(
        'XADD',
        KEYS[1],
        '*',
        'source_stream', KEYS[3],
        'source_group', ARGV[1],
        'source_message_id', ARGV[2],
        'delivery_count', ARGV[3],
        'failure_reason', ARGV[4],
        'original_fields', ARGV[5],
        'dead_lettered_at', ARGV[7]
    )
end

-- Acknowledge and delete the original only after DLQ insertion.
local acknowledged = redis.call(
    'XACK',
    KEYS[3],
    ARGV[1],
    ARGV[2]
)

if acknowledged > 0 then
    redis.call('XDEL', KEYS[3], ARGV[2])
end

return acknowledged
"""


def _as_text(value: Any) -> str:
    """Normalize Redis response values to strings."""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    return str(value)


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


async def acknowledge_research_message(
    redis: Any,
    message_id: str | bytes,
) -> bool:
    """
    Atomically acknowledge and delete a successfully processed queue entry.
    """

    acknowledged = await redis.eval(
        _ACK_AND_DELETE_SCRIPT,
        1,
        QUEUE_STREAM,
        QUEUE_GROUP,
        _as_text(message_id),
    )

    return bool(acknowledged)


async def get_pending_delivery_count(
    redis: Any,
    message_id: str | bytes,
) -> int | None:
    """
    Return the delivery count of a specific pending message.

    None means the message is no longer in the pending-entry list.
    """

    source_id = _as_text(message_id)

    entries = await redis.xpending_range(
        QUEUE_STREAM,
        QUEUE_GROUP,
        min=source_id,
        max=source_id,
        count=1,
    )

    if not entries:
        return None

    entry = entries[0]

    count = entry.get("times_delivered")

    if count is None:
        count = entry.get(b"times_delivered")

    if count is None:
        raise ValueError(f"Redis did not return a delivery count for message {source_id}.")

    return int(count)


async def dead_letter_research_message(
    redis: Any,
    message_id: str | bytes,
    fields: dict[Any, Any],
    delivery_count: int,
    reason: str,
) -> bool:
    """
    Atomically move a malformed pending message into the DLQ,
    acknowledge the original and delete its source stream entry.

    The deduplication key protects against repeated DLQ insertion.
    """

    source_id = _as_text(message_id)

    original_fields = {_as_text(key): _as_text(value) for key, value in fields.items()}

    dedupe_key = f"{DEAD_LETTER_STREAM}:dedupe:{source_id}"

    acknowledged = await redis.eval(
        _DEAD_LETTER_SCRIPT,
        3,
        DEAD_LETTER_STREAM,
        dedupe_key,
        QUEUE_STREAM,
        QUEUE_GROUP,
        source_id,
        str(delivery_count),
        reason[:2000],
        json.dumps(original_fields, ensure_ascii=False),
        str(DLQ_DEDUPE_TTL_SECONDS),
        datetime.now(UTC).isoformat(),
    )

    return bool(acknowledged)
