"""FastAPI application configuration and lifecycle management."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.globals import get_llm_cache, set_llm_cache

from market_intelligence.api.v1.endpoints.auth import router as auth_router
from market_intelligence.api.v1.endpoints.conversations import (
    router as conversations_router,
)
from market_intelligence.api.v1.endpoints.research import router as research_router
from market_intelligence.api.v1.endpoints.sentiment import router as sentiment_router
from market_intelligence.cache.client import (
    close_redis_client,
    create_redis_client,
)
from market_intelligence.cache.semantic import create_semantic_cache
from market_intelligence.core.config import PROJECT_ROOT, Settings
from market_intelligence.db.pool import create_database_pool
from market_intelligence.db.repositories.auth import initialize_auth_tables
from market_intelligence.db.repositories.conversations import (
    initialize_research_conversations,
)
from market_intelligence.db.repositories.datasets import (
    initialize_dataset_tables,
)
from market_intelligence.db.repositories.research_jobs import (
    initialize_research_jobs,
)
from market_intelligence.sentiment.inference.predictor import SentimentPredictor


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and release shared application resources."""

    settings = Settings()

    redis_client = create_redis_client(settings)
    db_pool = None
    semantic_cache = None

    previous_llm_cache = get_llm_cache()

    try:
        # ---------------------------------------------------------
        # 1. Initialize Redis
        # ---------------------------------------------------------

        await redis_client.ping()

        app.state.redis = redis_client

        print("Redis connected successfully.")

        # ---------------------------------------------------------
        # 2. Initialize PostgreSQL
        # ---------------------------------------------------------

        db_pool = await create_database_pool(settings)

        await initialize_research_jobs(db_pool)
        await initialize_auth_tables(db_pool)
        await initialize_research_conversations(db_pool)
        await initialize_dataset_tables(db_pool)

        app.state.db_pool = db_pool
        app.state.settings = settings

        print("PostgreSQL connected successfully.")
        print("Research jobs table initialized successfully.")

        # ---------------------------------------------------------
        # 3. Load sentiment prediction model
        # ---------------------------------------------------------

        artifact_path = (
            PROJECT_ROOT
            / "artifacts"
            / "sentiment"
            / "classical_ml"
            / "logistic_regression_word_char.joblib"
        )

        app.state.sentiment_predictor = SentimentPredictor(artifact_path)

        print("Sentiment model loaded successfully.")

        # ---------------------------------------------------------
        # 4. Initialize Redis semantic cache
        # ---------------------------------------------------------

        semantic_cache = await asyncio.to_thread(
            create_semantic_cache,
            settings,
        )

        app.state.semantic_cache = semantic_cache

        set_llm_cache(semantic_cache)

        print("Redis semantic cache initialized successfully.")
        print("LangChain global LLM cache configured.")

        # Application runs while resources remain available.
        yield

    finally:
        # ---------------------------------------------------------
        # 5. Restore the previous LangChain cache
        # ---------------------------------------------------------

        set_llm_cache(previous_llm_cache)

        # ---------------------------------------------------------
        # 6. Close semantic cache, PostgreSQL and Redis
        # ---------------------------------------------------------

        try:
            if semantic_cache is not None:
                await asyncio.to_thread(semantic_cache.redis.close)

        finally:
            try:
                if db_pool is not None:
                    await db_pool.close()

            finally:
                await close_redis_client(redis_client)

        # ---------------------------------------------------------
        # 7. Remove application state references
        # ---------------------------------------------------------

        for resource in (
            "redis",
            "db_pool",
            "semantic_cache",
            "sentiment_predictor",
        ):
            if hasattr(app.state, resource):
                delattr(app.state, resource)

        print("Application resources shut down successfully.")


# =============================================================
# FastAPI application
# =============================================================

app = FastAPI(
    title="Market Intelligence Research Agent",
    description=(
        "Asynchronous AI-powered market intelligence and research platform "
        "with LangGraph orchestration, MCP tools, quantitative analytics "
        "and sentiment analysis."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=Settings().frontend_origins,
    allow_credentials=True,
    allow_methods=[
        "GET",
        "POST",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


# =============================================================
# API v1 Routers
# =============================================================

app.include_router(
    research_router,
    prefix="/api/v1",
)

app.include_router(
    sentiment_router,
    prefix="/api/v1",
)

app.include_router(
    auth_router,
    prefix="/api/v1",
)

app.include_router(
    conversations_router,
    prefix="/api/v1",
)
