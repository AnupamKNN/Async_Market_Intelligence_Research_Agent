import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langchain_core.globals import get_llm_cache, set_llm_cache

from market_intelligence.api.v1.endpoints.sentiment import router as sentiment_router
from market_intelligence.cache.client import (
    close_redis_client,
    create_redis_client,
)
from market_intelligence.cache.semantic import create_semantic_cache
from market_intelligence.core.config import PROJECT_ROOT, Settings
from market_intelligence.sentiment.inference.predictor import SentimentPredictor


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and release shared application resources."""

    settings = Settings()
    redis_client = create_redis_client(settings)
    semantic_cache = None
    previous_llm_cache = get_llm_cache()

    try:
        # Initialize asynchronous Redis connection.
        await redis_client.ping()
        app.state.redis = redis_client
        print("Redis connected successfully.")

        # Load sentiment model once.
        artifact_path = (
            PROJECT_ROOT
            / "artifacts"
            / "sentiment"
            / "classical_ml"
            / "logistic_regression_word_char.joblib"
        )

        app.state.sentiment_predictor = SentimentPredictor(artifact_path)
        print("Sentiment model loaded successfully.")

        # Initialize semantic cache without blocking the event loop.
        semantic_cache = await asyncio.to_thread(
            create_semantic_cache,
            settings,
        )

        app.state.semantic_cache = semantic_cache
        set_llm_cache(semantic_cache)

        print("Redis semantic cache initialized successfully.")
        print("LangChain global LLM cache configured.")

        yield

    finally:
        # Restore the previous LangChain global cache.
        set_llm_cache(previous_llm_cache)

        try:
            if semantic_cache is not None:
                await asyncio.to_thread(semantic_cache.redis.close)
        finally:
            await close_redis_client(redis_client)

        for resource in ("redis", "semantic_cache", "sentiment_predictor"):
            if hasattr(app.state, resource):
                delattr(app.state, resource)


app = FastAPI(
    title="Market Intelligence Research Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(sentiment_router, prefix="/api/v1")
