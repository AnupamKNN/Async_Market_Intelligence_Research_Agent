import asyncpg

from market_intelligence.core.config import Settings


async def create_database_pool(settings: Settings | None = None) -> asyncpg.Pool:
    """Create an application-wide async PostgreSQL connection pool."""

    config = settings or Settings()

    return await asyncpg.create_pool(
        host=config.postgres_host,
        port=config.postgres_port,
        database=config.postgres_db,
        user=config.postgres_user,
        password=config.postgres_password.get_secret_value(),
        min_size=1,
        max_size=10,
        command_timeout=20,
        max_inactive_connection_lifetime=300,
        server_settings={
            "application_name": "market-intelligence-internal-analytics-mcp",
            "statement_timeout": "15000",
            "idle_in_transaction_session_timeout": "30000",
        },
    )
