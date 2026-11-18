import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from market_intelligence.api.app import app
from market_intelligence.api.v1.dependencies import get_authenticated_session
from market_intelligence.api.v1.endpoints import research as research_endpoint
from market_intelligence.services.auth_security import generate_token, hash_token
from market_intelligence.services.research_queue import event_stream_key


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def authenticated_session():
    user_id = uuid4()
    csrf_token = generate_token()

    async def override_session():
        return {
            "user_id": user_id,
            "csrf_token_hash": hash_token(csrf_token),
        }

    app.dependency_overrides[get_authenticated_session] = override_session

    yield user_id, csrf_token

    app.dependency_overrides.pop(get_authenticated_session, None)


def test_authenticated_user_can_submit_research(
    client: TestClient,
    authenticated_session,
    monkeypatch,
):
    user_id, csrf_token = authenticated_session
    created = {}

    async def fake_create_research_conversation(
        pool,
        conversation_id,
        owner_id,
        title,
    ):
        created["conversation_id"] = conversation_id
        created["conversation_user_id"] = owner_id
        created["title"] = title

    async def fake_create_research_job(
        pool,
        job_id,
        payload,
        owner_id,
        conversation_id=None,
    ):
        created["job_id"] = job_id
        created["payload"] = payload
        created["user_id"] = owner_id
        created["job_conversation_id"] = conversation_id

    monkeypatch.setattr(
        research_endpoint,
        "create_research_conversation",
        fake_create_research_conversation,
    )
    monkeypatch.setattr(
        research_endpoint,
        "create_research_job",
        fake_create_research_job,
    )

    client.cookies.set("mi_csrf", csrf_token)

    response = client.post(
        "/api/v1/research/jobs",
        json={"question": "Summarize sales trends."},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 202

    response_data = response.json()

    assert created["user_id"] == user_id
    assert created["conversation_user_id"] == user_id
    assert created["payload"]["question"] == "Summarize sales trends."

    assert created["conversation_id"] == created["job_conversation_id"]
    assert str(created["job_id"]) == response_data["job_id"]
    assert str(created["conversation_id"]) == response_data["conversation_id"]
    assert created["title"] == "Summarize sales trends."


def test_sse_resumes_after_last_event_id_and_recovers_completion(
    client: TestClient,
    authenticated_session,
    monkeypatch,
):
    """Replay events after the browser cursor and recover terminal state."""

    user_id, _ = authenticated_session
    job_id = uuid4()
    stream = event_stream_key(job_id)

    cursor = "1700000000000-0"
    next_event_id = "1700000001000-0"

    job = {
        "job_id": job_id,
        "status": "completed",
        "result": {"report": "Persisted research report."},
        "error": None,
    }

    xread_cursors = []

    async def fake_get_job(pool, requested_job_id, owner_id):
        assert requested_job_id == job_id
        assert owner_id == user_id
        return job

    class FakeRedis:
        async def xread(self, streams, count, block):
            xread_cursors.append(streams[stream])

            if len(xread_cursors) == 1:
                return [
                    (
                        stream,
                        [
                            (
                                next_event_id,
                                {
                                    "event": "progress",
                                    "data": json.dumps(
                                        {
                                            "stage": "analysis",
                                            "message": "Analysis completed.",
                                        }
                                    ),
                                },
                            )
                        ],
                    )
                ]

            return []

    monkeypatch.setattr(
        research_endpoint,
        "get_research_job_for_user",
        fake_get_job,
    )
    monkeypatch.setattr(
        app.state,
        "redis",
        FakeRedis(),
        raising=False,
    )

    response = client.get(
        f"/api/v1/research/jobs/{job_id}/events",
        headers={"Last-Event-ID": cursor},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    assert xread_cursors == [
        cursor,
        next_event_id,
    ]

    assert "event: progress" in response.text
    assert "event: completed" in response.text
    assert '"recovered": true' in response.text


def test_sse_recovers_failed_job_when_redis_has_no_events(
    client: TestClient,
    authenticated_session,
    monkeypatch,
):
    """A failed PostgreSQL job must emit a terminal SSE event."""

    user_id, _ = authenticated_session
    job_id = uuid4()

    async def fake_get_job(pool, requested_job_id, owner_id):
        assert requested_job_id == job_id
        assert owner_id == user_id

        return {
            "job_id": job_id,
            "status": "failed",
            "result": None,
            "error": "Provider unavailable.",
        }

    class FakeRedis:
        async def xread(self, streams, count, block):
            return []

    monkeypatch.setattr(
        research_endpoint,
        "get_research_job_for_user",
        fake_get_job,
    )
    monkeypatch.setattr(
        app.state,
        "redis",
        FakeRedis(),
        raising=False,
    )

    response = client.get(
        f"/api/v1/research/jobs/{job_id}/events",
    )

    assert response.status_code == 200
    assert "event: failed" in response.text
    assert "Provider unavailable." in response.text
    assert '"recovered": true' in response.text


def test_sse_rejects_invalid_last_event_id(
    client: TestClient,
    authenticated_session,
    monkeypatch,
):
    """An invalid Redis stream cursor must be rejected."""

    user_id, _ = authenticated_session
    job_id = uuid4()

    async def fake_get_job(pool, requested_job_id, owner_id):
        return {
            "job_id": job_id,
            "status": "running",
            "result": None,
            "error": None,
        }

    monkeypatch.setattr(
        research_endpoint,
        "get_research_job_for_user",
        fake_get_job,
    )

    response = client.get(
        f"/api/v1/research/jobs/{job_id}/events",
        headers={"Last-Event-ID": "invalid-cursor"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Last-Event-ID header."
