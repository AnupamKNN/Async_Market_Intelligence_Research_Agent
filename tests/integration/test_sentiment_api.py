import pytest
from fastapi.testclient import TestClient

from market_intelligence.api.app import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_positive_sentiment_api(client: TestClient) -> None:
    response = client.post(
        "/api/v1/sentiment/predict",
        json={"text": "Excellent product. I absolutely love it."},
    )

    assert response.status_code == 200
    assert response.json()["label"] == "positive"


def test_negative_sentiment_api(client: TestClient) -> None:
    response = client.post(
        "/api/v1/sentiment/predict",
        json={"text": "Terrible product. I completely regret buying it."},
    )

    assert response.status_code == 200
    assert response.json()["label"] == "negative"


@pytest.mark.parametrize(
    "payload",
    [
        {"text": ""},
        {"text": "   "},
        {},
        {"text": 123},
    ],
)
def test_invalid_sentiment_request(
    client: TestClient,
    payload: dict,
) -> None:
    response = client.post(
        "/api/v1/sentiment/predict",
        json=payload,
    )

    assert response.status_code == 422

