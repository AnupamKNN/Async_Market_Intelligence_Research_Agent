import json

from market_intelligence.services import research_queue


async def test_get_pending_delivery_count():
    message_id = "1700000000000-0"

    class FakeRedis:
        async def xpending_range(self, *args, **kwargs):
            assert args == (
                research_queue.QUEUE_STREAM,
                research_queue.QUEUE_GROUP,
            )
            assert kwargs["min"] == message_id
            assert kwargs["max"] == message_id
            assert kwargs["count"] == 1

            return [{"times_delivered": 2}]

    result = await research_queue.get_pending_delivery_count(
        FakeRedis(),
        message_id,
    )

    assert result == 2


async def test_get_pending_delivery_count_returns_none_for_missing_message():
    class FakeRedis:
        async def xpending_range(self, *args, **kwargs):
            return []

    result = await research_queue.get_pending_delivery_count(
        FakeRedis(),
        "1700000000000-0",
    )

    assert result is None


async def test_acknowledge_research_message_uses_atomic_script():
    message_id = "1700000000000-0"

    class FakeRedis:
        async def eval(self, *args):
            assert args[1] == 1
            assert args[2] == research_queue.QUEUE_STREAM
            assert args[3] == research_queue.QUEUE_GROUP
            assert args[4] == message_id
            return 1

    acknowledged = await research_queue.acknowledge_research_message(
        FakeRedis(),
        message_id,
    )

    assert acknowledged is True


async def test_dead_letter_preserves_original_message():
    message_id = "1700000000000-0"

    original_fields = {
        "job_id": "not-a-valid-uuid",
        "payload": "{invalid-json",
    }

    class FakeRedis:
        async def eval(self, *args):
            assert args[1] == 3
            assert args[2] == research_queue.DEAD_LETTER_STREAM
            assert args[3] == (f"{research_queue.DEAD_LETTER_STREAM}:dedupe:{message_id}")
            assert args[4] == research_queue.QUEUE_STREAM
            assert args[5] == research_queue.QUEUE_GROUP
            assert args[6] == message_id
            assert args[7] == "3"
            assert args[8] == "JSONDecodeError: Invalid JSON"

            preserved_fields = json.loads(args[9])

            assert preserved_fields == original_fields

            assert args[10] == str(research_queue.DLQ_DEDUPE_TTL_SECONDS)

            return 1

    dead_lettered = await research_queue.dead_letter_research_message(
        FakeRedis(),
        message_id,
        original_fields,
        3,
        "JSONDecodeError: Invalid JSON",
    )

    assert dead_lettered is True
