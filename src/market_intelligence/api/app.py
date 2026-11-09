from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from market_intelligence.api.v1.endpoints.sentiment import router as sentiment_router
from market_intelligence.core.config import PROJECT_ROOT
from market_intelligence.sentiment.inference.predictor import SentimentPredictor


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize shared application resources."""

    artifact_path = (
        PROJECT_ROOT
        / "artifacts"
        / "sentiment"
        / "classical_ml"
        / "logistic_regression_word_char.joblib"
    )

    # Load the model once when the API starts.
    app.state.sentiment_predictor = SentimentPredictor(artifact_path)

    print("Sentiment model loaded successfully.")

    yield

    # Release the application reference during shutdown
    del app.state.sentiment_predictor


app = FastAPI(
    title="Market Intelligence Research Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(sentiment_router, prefix="/api/v1")
