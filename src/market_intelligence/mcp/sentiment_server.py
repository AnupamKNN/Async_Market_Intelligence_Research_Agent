"""Sentiment MCP server exposing the production customer-review classifier."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastmcp import Context, FastMCP

from market_intelligence.core.config import PROJECT_ROOT
from market_intelligence.sentiment.inference.predictor import SentimentPredictor

MODEL_PATH = (
    PROJECT_ROOT
    / "artifacts"
    / "sentiment"
    / "classical_ml"
    / "logistic_regression_word_char.joblib"
)


@asynccontextmanager
async def app_lifespan(
    _server: FastMCP,
) -> AsyncIterator[dict[str, Any]]:
    """Load the production model once and retain it for the server lifetime."""

    predictor = SentimentPredictor(MODEL_PATH)
    yield {"predictor": predictor}


mcp = FastMCP(
    name="Market Intelligence Sentiment",
    lifespan=app_lifespan,
    instructions=(
        "Classifies customer-review sentiment using the production model "
        "trained on the UCI Amazon, IMDb, and Yelp review dataset. "
        "This model is not trained or validated for financial-news sentiment."
    ),
)


def get_predictor(ctx: Context) -> SentimentPredictor:
    """Retrieve the shared sentiment predictor."""

    return cast(SentimentPredictor, ctx.lifespan_context["predictor"])


@mcp.tool
async def predict_customer_review_sentiment(
    ctx: Context,
    text: str,
) -> dict[str, Any]:
    """Classify one customer review as positive or negative."""

    if len(text) > 10_000:
        raise ValueError("Text cannot exceed 10,000 characters.")

    return get_predictor(ctx).predict(text)


@mcp.tool
async def predict_customer_review_sentiment_batch(
    ctx: Context,
    texts: list[str],
) -> dict[str, Any]:
    """Classify up to 100 customer reviews in one batch."""

    if len(texts) > 100:
        raise ValueError("A maximum of 100 texts is allowed per batch.")

    if any(len(text) > 10_000 for text in texts):
        raise ValueError("Each text cannot exceed 10,000 characters.")

    predictions = get_predictor(ctx).predict_batch(texts)

    return {
        "count": len(predictions),
        "predictions": predictions,
    }


def main() -> None:
    """Run the Sentiment MCP server over stdio."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
