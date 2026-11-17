import json
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from market_intelligence.cache.client import (
    close_redis_client,
    create_redis_client,
)
from market_intelligence.core.config import Settings
from market_intelligence.services import research_queue


@asynccontextmanager
async def isolated_redis_queue(monkeypatch):
    """Create isolated Redis streams and a consumer group for testing."""

    redis = create_redis_client(Settings())

    try:
        await redis.ping()
    except (RedisError, OSError) as exc:
        await close_redis_client(redis)
        pytest.skip(
            f"Redis integration tests require a reachable Redis instance: {type(exc).__name__}"
        )

    prefix = f"mi:test:research-queue:{uuid4().hex}"

    stream = f"{prefix}:jobs"
    group = f"{prefix}:workers"
    dead_letter_stream = f"{prefix}:dlq"

    monkeypatch.setattr(research_queue, "QUEUE_STREAM", stream)
    monkeypatch.setattr(research_queue, "QUEUE_GROUP", group)
    monkeypatch.setattr(
        research_queue,
        "DEAD_LETTER_STREAM",
        dead_letter_stream,
    )

    try:
        await redis.xgroup_create(
            stream,
            group,
            id="0",
            mkstream=True,
        )

        yield redis, stream, group, dead_letter_stream

    finally:
        try:
            dedupe_keys = [
                key async for key in redis.scan_iter(match=f"{dead_letter_stream}:dedupe:*")
            ]

            keys_to_delete = [
                stream,
                dead_letter_stream,
                *dedupe_keys,
            ]

            await redis.delete(*keys_to_delete)

        finally:
            await close_redis_client(redis)


async def test_real_redis_acknowledgement_deletes_message(monkeypatch):
    """Successfully acknowledged messages must be removed from the stream."""

    async with isolated_redis_queue(monkeypatch) as (
        redis,
        stream,
        group,
        _,
    ):
        message_id = await redis.xadd(
            stream,
            {
                "job_id": str(uuid4()),
                "payload": '{"question": "Test acknowledgement"}',
            },
        )

        deliveries = await redis.xreadgroup(
            group,
            "worker-a",
            {stream: ">"},
            count=1,
        )

        assert len(deliveries) == 1
        assert len(deliveries[0][1]) == 1

        delivery_id, _ = deliveries[0][1][0]
        assert delivery_id == message_id

        pending_count = await research_queue.get_pending_delivery_count(
            redis,
            message_id,
        )

        assert pending_count == 1

        acknowledged = await research_queue.acknowledge_research_message(
            redis,
            message_id,
        )

        assert acknowledged is True

        assert await redis.xlen(stream) == 0

        remaining_pending = await research_queue.get_pending_delivery_count(
            redis,
            message_id,
        )

        assert remaining_pending is None


async def test_real_redis_dead_letter_preserves_and_cleans_message(
    monkeypatch,
):
    """DLQ insertion must preserve the message and remove its source entry."""

    async with isolated_redis_queue(monkeypatch) as (
        redis,
        stream,
        group,
        dead_letter_stream,
    ):
        original_fields = {
            "job_id": "not-a-valid-uuid",
            "payload": "{invalid-json",
        }

        message_id = await redis.xadd(
            stream,
            original_fields,
        )

        deliveries = await redis.xreadgroup(
            group,
            "worker-a",
            {stream: ">"},
            count=1,
        )

        assert len(deliveries) == 1

        delivery_id, received_fields = deliveries[0][1][0]
        assert delivery_id == message_id

        assert received_fields == original_fields

        # Simulate two redeliveries. Normal XCLAIM increments delivery count.
        for consumer in ("worker-b", "worker-c"):
            claimed = await redis.xclaim(
                stream,
                group,
                consumer,
                min_idle_time=0,
                message_ids=[message_id],
            )

            assert claimed

        delivery_count = await research_queue.get_pending_delivery_count(
            redis,
            message_id,
        )

        assert delivery_count == 3

        dead_lettered = await research_queue.dead_letter_research_message(
            redis,
            message_id,
            received_fields,
            delivery_count,
            "JSONDecodeError: Invalid JSON",
        )

        assert dead_lettered is True

        assert await redis.xlen(stream) == 0

        assert (
            await research_queue.get_pending_delivery_count(
                redis,
                message_id,
            )
            is None
        )

        dead_letter_entries = await redis.xrange(dead_letter_stream)

        assert len(dead_letter_entries) == 1

        _, dead_letter_fields = dead_letter_entries[0]

        assert dead_letter_fields["source_stream"] == stream
        assert dead_letter_fields["source_group"] == group
        assert dead_letter_fields["source_message_id"] == message_id
        assert dead_letter_fields["delivery_count"] == "3"

        assert dead_letter_fields["failure_reason"] == "JSONDecodeError: Invalid JSON"

        assert json.loads(dead_letter_fields["original_fields"]) == original_fields

        assert dead_letter_fields["dead_lettered_at"]

        # A repeated operation must not create another DLQ record.
        repeated_result = await research_queue.dead_letter_research_message(
            redis,
            message_id,
            received_fields,
            delivery_count,
            "JSONDecodeError: Invalid JSON",
        )

        assert repeated_result is False
        assert await redis.xlen(dead_letter_stream) == 1


async def test_real_redis_does_not_dead_letter_non_pending_message(
    monkeypatch,
):
    """A source entry that is not pending must not be moved to the DLQ."""

    async with isolated_redis_queue(monkeypatch) as (
        redis,
        stream,
        _,
        dead_letter_stream,
    ):
        original_fields = {
            "job_id": "invalid",
            "payload": "{invalid-json",
        }

        message_id = await redis.xadd(
            stream,
            original_fields,
        )

        # Deliberately do not read the message through XREADGROUP.
        # Therefore it is not pending.
        assert (
            await research_queue.get_pending_delivery_count(
                redis,
                message_id,
            )
            is None
        )

        dead_lettered = await research_queue.dead_letter_research_message(
            redis,
            message_id,
            original_fields,
            3,
            "Malformed message",
        )

        assert dead_lettered is False

        assert await redis.xlen(dead_letter_stream) == 0

        # The original stream entry must remain untouched.
        assert await redis.xlen(stream) == 1


async def test_real_redis_worker_dead_letters_after_three_deliveries(
    monkeypatch,
):
    """Worker moves malformed messages to DLQ after three deliveries."""

    from market_intelligence.workers import research_worker

    async with isolated_redis_queue(monkeypatch) as (
        redis,
        stream,
        group,
        dead_letter_stream,
    ):
        original_fields = {
            "job_id": "invalid-uuid",
            "payload": "{invalid-json",
        }

        message_id = await redis.xadd(
            stream,
            original_fields,
        )

        deliveries = await redis.xreadgroup(
            group,
            "worker-a",
            {stream: ">"},
            count=1,
        )

        assert len(deliveries) == 1

        _, received_fields = deliveries[0][1][0]

        # Delivery 1: message remains pending.
        await research_worker.handle_malformed_queue_message(
            redis,
            message_id,
            received_fields,
            ValueError("Malformed message."),
        )

        assert (
            await research_queue.get_pending_delivery_count(
                redis,
                message_id,
            )
            == 1
        )

        assert await redis.xlen(dead_letter_stream) == 0

        # Delivery 2: reclaim the message.
        reclaimed = await redis.xclaim(
            stream,
            group,
            "worker-b",
            min_idle_time=0,
            message_ids=[message_id],
        )

        assert reclaimed

        await research_worker.handle_malformed_queue_message(
            redis,
            message_id,
            received_fields,
            ValueError("Malformed message."),
        )

        assert (
            await research_queue.get_pending_delivery_count(
                redis,
                message_id,
            )
            == 2
        )

        assert await redis.xlen(dead_letter_stream) == 0

        # Delivery 3: another reclaim reaches the threshold.
        reclaimed = await redis.xclaim(
            stream,
            group,
            "worker-c",
            min_idle_time=0,
            message_ids=[message_id],
        )

        assert reclaimed

        await research_worker.handle_malformed_queue_message(
            redis,
            message_id,
            received_fields,
            ValueError("Malformed message."),
        )

        # The original message should now be acknowledged and deleted.
        assert await redis.xlen(stream) == 0

        assert (
            await research_queue.get_pending_delivery_count(
                redis,
                message_id,
            )
            is None
        )

        # Exactly one DLQ entry must exist.
        dead_letters = await redis.xrange(dead_letter_stream)

        assert len(dead_letters) == 1

        _, dead_letter_fields = dead_letters[0]

        assert dead_letter_fields["source_message_id"] == message_id
        assert dead_letter_fields["delivery_count"] == "3"

        assert json.loads(dead_letter_fields["original_fields"]) == original_fields

