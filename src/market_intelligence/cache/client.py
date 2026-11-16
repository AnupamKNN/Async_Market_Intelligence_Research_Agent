"""Asynchronous Redis client management."""

from redis.asyncio import Redis

from market_intelligence.core.config import Settings


def create_redis_client(settings: Settings) -> Redis:
    """Create a shared asynchronous Redis client."""

    password = settings.redis_password.get_secret_value() if settings.redis_password else None

    return Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=password or None,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=30,
        health_check_interval=30,
        max_connections=20,
    )


async def close_redis_client(client: Redis) -> None:
    """Close the Redis client and its connection pool."""

    await client.aclose()
