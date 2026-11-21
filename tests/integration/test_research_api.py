import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from market_intelligence.api.app import app
from market_intelligence.api.v1.dependencies import get_authenticated_session
from market_intelligence.api.v1.endpoints import (
    conversations as conversations_endpoint,
)
from market_intelligence.api.v1.endpoints import (
    research as research_endpoint,
)
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

    assert response.status_code == 202, response.text

    response_data = response.json()

    assert created["user_id"] == user_id
    assert created["conversation_user_id"] == user_id
    assert created["payload"]["question"] == "Summarize sales trends."
    assert created["payload"]["product_limit"] == 10

    assert created["conversation_id"] == created["job_conversation_id"]
    assert str(created["job_id"]) == response_data["job_id"]
    assert str(created["conversation_id"]) == response_data["conversation_id"]
    assert created["title"] == "Sales trends"


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


def test_authenticated_user_can_cancel_research(
    client: TestClient,
    authenticated_session,
    monkeypatch,
):
    user_id, csrf_token = authenticated_session
    job_id = uuid4()
    published_events = []

    async def fake_cancel(pool, requested_job_id, owner_id):
        assert requested_job_id == job_id
        assert owner_id == user_id
        return "cancelled", True

    async def fake_publish(redis, requested_job_id, event, data):
        published_events.append((event, data))

    monkeypatch.setattr(
        research_endpoint,
        "cancel_research_job_for_user",
        fake_cancel,
    )

    monkeypatch.setattr(
        research_endpoint,
        "publish_job_event",
        fake_publish,
    )

    monkeypatch.setattr(
        app.state,
        "redis",
        object(),
        raising=False,
    )

    client.cookies.set("mi_csrf", csrf_token)

    response = client.post(
        f"/api/v1/research/jobs/{job_id}/cancel",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200

    data = response.json()

    assert data["job_id"] == str(job_id)
    assert data["status"] == "cancelled"
    assert data["cancellation_requested"] is True

    assert len(published_events) == 1
    assert published_events[0][0] == "cancelled"


def test_sse_recovers_cancelled_job(
    client: TestClient,
    authenticated_session,
    monkeypatch,
):
    user_id, _ = authenticated_session
    job_id = uuid4()

    async def fake_get_job(pool, requested_job_id, owner_id):
        assert requested_job_id == job_id
        assert owner_id == user_id

        return {
            "job_id": job_id,
            "status": "cancelled",
            "result": None,
            "error": "Cancelled by user.",
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
    assert "event: cancelled" in response.text
    assert "Research was cancelled." in response.text
    assert '"recovered": true' in response.text


@pytest.mark.parametrize(
    ("question", "explicit_limit", "expected_limit"),
    [
        ("Find the top 200 products.", None, 200),
        ("Summarize sales trends.", 250, 250),
    ],
)
def test_submit_research_resolves_product_limit(
    client: TestClient,
    authenticated_session,
    monkeypatch,
    question,
    explicit_limit,
    expected_limit,
):
    _, csrf_token = authenticated_session
    created = {}

    async def fake_create_research_conversation(
        pool,
        conversation_id,
        owner_id,
        title,
    ):
        return None

    async def fake_create_research_job(
        pool,
        job_id,
        payload,
        owner_id,
        conversation_id=None,
    ):
        created["payload"] = payload

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

    request_payload = {"question": question}

    if explicit_limit is not None:
        request_payload["product_limit"] = explicit_limit

    client.cookies.set("mi_csrf", csrf_token)

    response = client.post(
        "/api/v1/research/jobs",
        json=request_payload,
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 202, (
        f"Expected 202, received {response.status_code}: {response.text}"
    )
    assert created["payload"]["product_limit"] == expected_limit


def test_submit_research_rejects_product_limit_above_configured_maximum(
    client: TestClient,
    authenticated_session,
    monkeypatch,
):
    _, csrf_token = authenticated_session

    monkeypatch.setattr(
        app.state.settings,
        "analytics_max_result_rows",
        100,
    )

    client.cookies.set("mi_csrf", csrf_token)

    response = client.post(
        "/api/v1/research/jobs",
        json={"question": "Find the top 101 products."},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 422
    assert "100" in response.json()["detail"]


def test_revise_research_forwards_resolved_product_limit(
    client: TestClient,
    authenticated_session,
    monkeypatch,
):
    _, csrf_token = authenticated_session

    original_job_id = uuid4()
    conversation_id = uuid4()
    turn_id = uuid4()
    captured = {}

    async def fake_create_research_job_revision(**kwargs):
        captured.update(kwargs)
        return conversation_id, turn_id, 2

    monkeypatch.setattr(
        research_endpoint,
        "create_research_job_revision",
        fake_create_research_job_revision,
    )

    client.cookies.set("mi_csrf", csrf_token)

    response = client.post(
        f"/api/v1/research/jobs/{original_job_id}/revise",
        json={"question": "Find the top 200 products."},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 202
    assert captured["original_job_id"] == original_job_id
    assert captured["question"] == "Find the top 200 products."
    assert captured["product_limit"] == 200
    assert captured["user_id"] is not None


def test_authenticated_user_can_rename_conversation(
    client: TestClient,
    authenticated_session,
    monkeypatch,
):
    _, csrf_token = authenticated_session
    conversation_id = uuid4()
    captured = {}

    now = datetime.now(UTC)

    async def fake_rename(pool, requested_id, user_id, title):
        captured["conversation_id"] = requested_id
        captured["user_id"] = user_id
        captured["title"] = title

        return {
            "id": conversation_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "job_count": 0,
            "last_message_at": None,
        }

    monkeypatch.setattr(
        conversations_endpoint,
        "rename_research_conversation",
        fake_rename,
    )

    client.cookies.set("mi_csrf", csrf_token)

    response = client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"title": "  Quarterly   Sales Analysis  "},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Quarterly Sales Analysis"
    assert captured["conversation_id"] == conversation_id
    assert captured["user_id"] is not None
    assert captured["title"] == "Quarterly Sales Analysis"


def test_renaming_nonexistent_conversation_returns_404(
    client: TestClient,
    authenticated_session,
    monkeypatch,
):
    _, csrf_token = authenticated_session

    async def fake_rename(*args, **kwargs):
        return None

    monkeypatch.setattr(
        conversations_endpoint,
        "rename_research_conversation",
        fake_rename,
    )

    client.cookies.set("mi_csrf", csrf_token)

    response = client.patch(
        f"/api/v1/conversations/{uuid4()}",
        json={"title": "Updated Title"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 404


def test_authenticated_user_can_delete_conversation(
    client: TestClient,
    authenticated_session,
    monkeypatch,
):
    _, csrf_token = authenticated_session
    conversation_id = uuid4()
    captured = {}

    async def fake_delete(pool, requested_id, user_id):
        captured["conversation_id"] = requested_id
        captured["user_id"] = user_id
        return []

    monkeypatch.setattr(
        conversations_endpoint,
        "delete_research_conversation",
        fake_delete,
    )

    client.cookies.set("mi_csrf", csrf_token)

    response = client.delete(
        f"/api/v1/conversations/{conversation_id}",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 204
    assert captured["conversation_id"] == conversation_id
    assert captured["user_id"] is not None


def test_deleting_nonexistent_conversation_returns_404(
    client: TestClient,
    authenticated_session,
    monkeypatch,
):
    _, csrf_token = authenticated_session

    async def fake_delete(*args, **kwargs):
        return None

    monkeypatch.setattr(
        conversations_endpoint,
        "delete_research_conversation",
        fake_delete,
    )

    client.cookies.set("mi_csrf", csrf_token)

    response = client.delete(
        f"/api/v1/conversations/{uuid4()}",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 404


def test_deleting_conversation_with_running_jobs_returns_409(
    client: TestClient,
    authenticated_session,
    monkeypatch,
):
    _, csrf_token = authenticated_session

    async def fake_delete(*args, **kwargs):
        raise conversations_endpoint.ConversationHasRunningJobsError(
            "This conversation contains research that is still running."
        )

    monkeypatch.setattr(
        conversations_endpoint,
        "delete_research_conversation",
        fake_delete,
    )

    client.cookies.set("mi_csrf", csrf_token)

    response = client.delete(
        f"/api/v1/conversations/{uuid4()}",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 409
