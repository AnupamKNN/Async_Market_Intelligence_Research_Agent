from pathlib import Path

import pytest

from market_intelligence.sentiment.inference.predictor import SentimentPredictor

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ARTIFACT_PATH = (
    PROJECT_ROOT
    / "artifacts"
    / "sentiment"
    / "classical_ml"
    / "logistic_regression_word_char.joblib"
)


@pytest.fixture(scope="module")
def predictor() -> SentimentPredictor:
    """Load the trained sentiment model once for this test module."""
    return SentimentPredictor(ARTIFACT_PATH)


def test_predictor_loads_model(predictor: SentimentPredictor) -> None:
    assert predictor.model is not None
    assert predictor.vectorizer is not None
    assert predictor.label_mapping == {
        0: "negative",
        1: "positive",
    }


def test_single_prediction(predictor: SentimentPredictor) -> None:
    result = predictor.predict("The product quality is excellent.")

    assert result["label"] in {"positive", "negative"}
    assert result["label_id"] in {0, 1}

    assert 0.0 <= result["positive_probability"] <= 1.0
    assert 0.0 <= result["negative_probability"] <= 1.0

    assert result["positive_probability"] + result["negative_probability"] == pytest.approx(1.0)


def test_batch_prediction(predictor: SentimentPredictor) -> None:
    reviews = [
        "Excellent product.",
        "Terrible experience.",
        "Average service.",
    ]

    results = predictor.predict_batch(reviews)

    assert len(results) == len(reviews)

    for result in results:
        assert result["label"] in {"positive", "negative"}
        assert result["label_id"] in {0, 1}


def test_empty_batch(predictor: SentimentPredictor) -> None:
    assert predictor.predict_batch([]) == []


@pytest.mark.parametrize("invalid_text", [None, 123, "", "   "])
def test_invalid_text(
    predictor: SentimentPredictor,
    invalid_text: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        predictor.predict(invalid_text)


def test_missing_artifact() -> None:
    with pytest.raises(FileNotFoundError):
        SentimentPredictor("artifacts/sentiment/missing_model.joblib")
