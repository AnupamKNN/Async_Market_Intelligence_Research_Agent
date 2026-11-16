from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from market_intelligence.api.app import app
from market_intelligence.api.v1.dependencies import get_authenticated_session
from market_intelligence.api.v1.endpoints import research as research_endpoint
from market_intelligence.services.auth_security import generate_token, hash_token


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

    async def fake_publish_job_event(redis, job_id, event, data):
        return None

    class FakeRedis:
        async def xadd(self, *args, **kwargs):
            return "1-0"

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
    monkeypatch.setattr(
        research_endpoint,
        "publish_job_event",
        fake_publish_job_event,
    )
    monkeypatch.setattr(app.state, "redis", FakeRedis())

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
