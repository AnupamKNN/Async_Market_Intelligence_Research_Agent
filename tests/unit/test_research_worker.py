import asyncio
from uuid import uuid4

import pytest

from market_intelligence.workers import research_worker


async def test_duplicate_delivery_does_not_execute_graph(monkeypatch):
    """A job with an active owner must not execute again."""

    job_id = uuid4()
    execution_called = False

    async def fake_claim(*args, **kwargs):
        return None

    async def fake_get_job(*args, **kwargs):
        return {
            "status": "running",
            "attempt_count": 1,
        }

    async def unexpected_execution(*args, **kwargs):
        nonlocal execution_called
        execution_called = True
        raise AssertionError("Duplicate graph execution was attempted.")

    monkeypatch.setattr(
        research_worker,
        "claim_research_job",
        fake_claim,
    )

    monkeypatch.setattr(
        research_worker,
        "get_research_job",
        fake_get_job,
    )

    monkeypatch.setattr(
        research_worker,
        "execute_with_heartbeat",
        unexpected_execution,
    )

    acknowledged = await research_worker.process_research_job(
        job_id=job_id,
        payload={"question": "Analyze retail performance."},
        settings=object(),
        redis=object(),
        pool=object(),
        worker_id="worker-b",
    )

    assert acknowledged is False
    assert execution_called is False


async def test_losing_lease_cancels_graph_execution(monkeypatch):
    """A worker must stop its graph when it loses lease ownership."""

    job_id = uuid4()
    lease_token = uuid4()

    graph_started = asyncio.Event()
    graph_cancelled = asyncio.Event()

    async def fake_execute_graph(*args, **kwargs):
        graph_started.set()

        try:
            # Simulate a long-running LangGraph operation.
            await asyncio.Event().wait()
        finally:
            graph_cancelled.set()

    async def fake_heartbeat(*args, **kwargs):
        # Ensure execution has started before simulating lease loss.
        await graph_started.wait()

        raise research_worker.LeaseLostError("Simulated lease ownership loss.")

    monkeypatch.setattr(
        research_worker,
        "execute_research_graph",
        fake_execute_graph,
    )

    monkeypatch.setattr(
        research_worker,
        "maintain_job_lease",
        fake_heartbeat,
    )

    with pytest.raises(research_worker.LeaseLostError):
        await research_worker.execute_with_heartbeat(
            job_id=job_id,
            lease_token=lease_token,
            payload={"question": "Analyze retail performance."},
            settings=object(),
            redis=object(),
            pool=object(),
        )

    assert graph_started.is_set()
    assert graph_cancelled.is_set()


async def test_redis_event_failure_does_not_invalidate_completed_job(
    monkeypatch,
):
    """A Redis event failure must not reverse successful DB completion."""

    job_id = uuid4()
    lease_token = uuid4()

    expected_result = {
        "report": "Validated retail research report.",
        "errors": [],
    }

    persisted_results = []

    async def fake_claim(*args, **kwargs):
        return lease_token

    async def fake_get_job(*args, **kwargs):
        return {
            "status": "running",
            "attempt_count": 1,
        }

    async def fake_execute(*args, **kwargs):
        return expected_result

    async def fake_complete(
        pool,
        claimed_job_id,
        result,
        lease_token=None,
    ):
        assert claimed_job_id == job_id
        assert lease_token == lease_token_expected
        persisted_results.append(result)
        return True

    async def fake_publish(*args, **kwargs):
        raise ConnectionError("Simulated Redis outage.")

    # Preserve the expected token separately for the completion assertion.
    lease_token_expected = lease_token

    monkeypatch.setattr(
        research_worker,
        "claim_research_job",
        fake_claim,
    )

    monkeypatch.setattr(
        research_worker,
        "get_research_job",
        fake_get_job,
    )

    monkeypatch.setattr(
        research_worker,
        "execute_with_heartbeat",
        fake_execute,
    )

    monkeypatch.setattr(
        research_worker,
        "complete_research_job",
        fake_complete,
    )

    monkeypatch.setattr(
        research_worker,
        "publish_job_event",
        fake_publish,
    )

    acknowledged = await research_worker.process_research_job(
        job_id=job_id,
        payload={"question": "Analyze retail performance."},
        settings=object(),
        redis=object(),
        pool=object(),
        worker_id="worker-a",
    )

    assert acknowledged is True
    assert persisted_results == [expected_result]


async def _run_job_with_retry_result(monkeypatch, retry_status):
    """Run a failing research job with a controlled retry outcome."""

    job_id = uuid4()
    lease_token = uuid4()

    retry_calls = []
    published_events = []

    async def fake_claim(*args, **kwargs):
        return lease_token

    async def fake_get_job(*args, **kwargs):
        return {
            "status": "running",
            "attempt_count": 2,
        }

    async def fake_execute(*args, **kwargs):
        raise RuntimeError("Temporary provider failure.")

    async def fake_retry(
        pool,
        claimed_job_id,
        error,
        lease_token=None,
    ):
        retry_calls.append(
            {
                "job_id": claimed_job_id,
                "error": error,
                "lease_token": lease_token,
            }
        )
        return retry_status

    async def fake_publish(redis, claimed_job_id, event, data):
        published_events.append((event, data))

    monkeypatch.setattr(
        research_worker,
        "claim_research_job",
        fake_claim,
    )

    monkeypatch.setattr(
        research_worker,
        "get_research_job",
        fake_get_job,
    )

    monkeypatch.setattr(
        research_worker,
        "execute_with_heartbeat",
        fake_execute,
    )

    monkeypatch.setattr(
        research_worker,
        "retry_research_job",
        fake_retry,
    )

    monkeypatch.setattr(
        research_worker,
        "publish_event_best_effort",
        fake_publish,
    )

    acknowledged = await research_worker.process_research_job(
        job_id=job_id,
        payload={"question": "Analyze retail performance."},
        settings=object(),
        redis=object(),
        pool=object(),
        worker_id="worker-a",
    )

    return acknowledged, retry_calls, published_events, job_id, lease_token


async def test_failed_attempt_remains_pending_when_retry_is_available(
    monkeypatch,
):
    """A retryable failure must not acknowledge the Redis message."""

    acknowledged, retry_calls, events, job_id, lease_token = await _run_job_with_retry_result(
        monkeypatch,
        "queued",
    )

    assert acknowledged is False

    assert len(retry_calls) == 1
    assert retry_calls[0]["job_id"] == job_id
    assert retry_calls[0]["lease_token"] == lease_token
    assert retry_calls[0]["error"] == ("RuntimeError: Temporary provider failure.")

    # Only the initial started event should be published.
    assert [event for event, _ in events] == ["started"]


async def test_exhausted_attempt_publishes_failure_and_acknowledges(
    monkeypatch,
):
    """An exhausted job must publish its terminal failure and be acknowledged."""

    acknowledged, retry_calls, events, job_id, lease_token = await _run_job_with_retry_result(
        monkeypatch,
        "failed",
    )

    assert acknowledged is True

    assert len(retry_calls) == 1
    assert retry_calls[0]["job_id"] == job_id
    assert retry_calls[0]["lease_token"] == lease_token

    event_names = [event for event, _ in events]

    assert event_names == ["started", "failed"]

    failure_event = events[-1][1]

    assert failure_event["status"] == "failed"
    assert "exhausting retry attempts" in failure_event["message"]


async def test_lost_lease_does_not_acknowledge_or_publish_failure(
    monkeypatch,
):
    """A worker that loses its lease must not acknowledge or fail the job."""

    acknowledged, retry_calls, events, job_id, lease_token = await _run_job_with_retry_result(
        monkeypatch,
        None,
    )

    assert acknowledged is False

    assert len(retry_calls) == 1
    assert retry_calls[0]["job_id"] == job_id
    assert retry_calls[0]["lease_token"] == lease_token

    # The worker must not publish a terminal failure event.
    assert [event for event, _ in events] == ["started"]


async def test_redis_pending_heartbeat_uses_xclaim_justid(monkeypatch):
    """Redis heartbeat must refresh the pending entry without incrementing deliveries."""

    job_id = uuid4()
    message_id = "1700000000000-0"
    calls = []

    class StopHeartbeat(Exception):
        pass

    class FakeRedis:
        async def xclaim(self, *args, **kwargs):
            calls.append((args, kwargs))
            return [message_id]

    sleep_calls = 0

    async def fake_sleep(seconds):
        nonlocal sleep_calls

        assert seconds == research_worker.HEARTBEAT_INTERVAL_SECONDS

        sleep_calls += 1

        if sleep_calls > 1:
            raise StopHeartbeat

    monkeypatch.setattr(
        research_worker.asyncio,
        "sleep",
        fake_sleep,
    )

    with pytest.raises(StopHeartbeat):
        await research_worker.maintain_redis_pending_message(
            redis=FakeRedis(),
            job_id=job_id,
            message_id=message_id,
            consumer_name="worker-a",
        )

    assert len(calls) == 1

    args, kwargs = calls[0]

    assert args == (
        research_worker.QUEUE_STREAM,
        research_worker.QUEUE_GROUP,
        "worker-a",
    )

    assert kwargs == {
        "min_idle_time": 0,
        "message_ids": [message_id],
        "justid": True,
    }


async def test_execute_with_heartbeat_starts_redis_heartbeat(monkeypatch):
    """Redis pending-message heartbeat must run alongside graph execution."""

    job_id = uuid4()
    lease_token = uuid4()
    message_id = "1700000000000-0"

    redis_heartbeat_started = asyncio.Event()
    heartbeat_calls = []

    expected_result = {
        "report": "Completed research report.",
        "errors": [],
    }

    async def fake_execute(*args, **kwargs):
        await redis_heartbeat_started.wait()
        return expected_result

    async def fake_database_heartbeat(*args, **kwargs):
        await asyncio.Event().wait()

    async def fake_redis_heartbeat(
        redis,
        claimed_job_id,
        claimed_message_id,
        consumer_name,
    ):
        heartbeat_calls.append(
            (
                claimed_job_id,
                claimed_message_id,
                consumer_name,
            )
        )

        redis_heartbeat_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        research_worker,
        "execute_research_graph",
        fake_execute,
    )

    monkeypatch.setattr(
        research_worker,
        "maintain_job_lease",
        fake_database_heartbeat,
    )

    monkeypatch.setattr(
        research_worker,
        "maintain_redis_pending_message",
        fake_redis_heartbeat,
    )

    result = await research_worker.execute_with_heartbeat(
        job_id=job_id,
        lease_token=lease_token,
        payload={"question": "Analyze retail performance."},
        settings=object(),
        redis=object(),
        pool=object(),
        message_id=message_id,
        consumer_name="worker-a",
    )

    assert result == expected_result

    assert heartbeat_calls == [
        (
            job_id,
            message_id,
            "worker-a",
        )
    ]
