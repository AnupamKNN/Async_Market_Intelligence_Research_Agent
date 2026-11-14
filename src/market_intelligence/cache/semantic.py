"""Redis-backed semantic caching for LLM responses."""

from urllib.parse import quote

from langchain_ollama import OllamaEmbeddings
from langchain_redis import RedisSemanticCache

from market_intelligence.core.config import Settings


def build_redis_url(settings: Settings) -> str:
    """Build the Redis connection URL from application settings."""

    password = settings.redis_password.get_secret_value() if settings.redis_password else None

    authentication = f":{quote(password, safe='')}@" if password else ""

    return (
        f"redis://{authentication}{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
    )


def create_semantic_cache(settings: Settings) -> RedisSemanticCache:
    """Create the application-wide semantic cache."""

    embeddings = OllamaEmbeddings(
        model=settings.embedding_model,
        base_url=settings.ollama_base_url,
    )

    return RedisSemanticCache(
        embeddings=embeddings,
        redis_url=build_redis_url(settings),
        distance_threshold=settings.semantic_cache_distance_threshold,
        ttl=settings.semantic_cache_ttl_seconds,
        name=settings.semantic_cache_name,
    )
