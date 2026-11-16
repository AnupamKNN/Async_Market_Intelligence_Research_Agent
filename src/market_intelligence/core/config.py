from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Centralized application settings."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    postgres_host: str = Field(default="127.0.0.1", validation_alias="POSTGRES_HOST")

    postgres_port: int = Field(
        default=5433,
        validation_alias="POSTGRES_PORT",
    )

    postgres_db: str = Field(
        default="market_intelligence",
        validation_alias="POSTGRES_DB",
    )

    postgres_user: str = Field(
        default="market_admin",
        validation_alias="POSTGRES_USER",
    )

    postgres_password: SecretStr = Field(
        validation_alias="POSTGRES_PASSWORD",
    )

    # External research APIs
    fred_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="FRED_API_KEY",
    )
    gnews_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="GNEWS_API_KEY",
    )

    # Redis
    redis_host: str = Field(
        default="127.0.0.1",
        validation_alias="REDIS_HOST",
    )

    redis_port: int = Field(
        default=6379,
        validation_alias="REDIS_PORT",
    )

    redis_db: int = Field(
        default=0,
        ge=0,
        validation_alias="REDIS_DB",
    )

    redis_password: SecretStr | None = Field(
        default=None,
        validation_alias="REDIS_PASSWORD",
    )

    # Ollama embeddings
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_BASE_URL",
    )

    embedding_model: str = Field(
        default="qwen3-embedding:4b",
        validation_alias="EMBEDDING_MODEL",
    )

    # Semantic cache
    semantic_cache_distance_threshold: float = Field(
        default=0.12,
        ge=0.0,
        le=2.0,
        validation_alias="SEMANTIC_CACHE_DISTANCE_THRESHOLD",
    )

    semantic_cache_ttl_seconds: int = Field(
        default=900,
        gt=0,
        validation_alias="SEMANTIC_CACHE_TTL_SECONDS",
    )

    semantic_cache_name: str = Field(
        default="mi_semantic_cache_v1",
        validation_alias="SEMANTIC_CACHE_NAME",
    )

    # Portkey AI Gateway
    portkey_base_url: str = Field(
        default="http://127.0.0.1:8787/v1",
        validation_alias="PORTKEY_BASE_URL",
    )

    # Groq
    groq_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="GROQ_API_KEY",
    )

    # OpenAI
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )

    # LLM Supervisor
    supervisor_llm_provider: Literal["ollama", "groq", "openai"] = Field(
        default="groq",
        validation_alias="SUPERVISOR_LLM_PROVIDER",
    )

    supervisor_llm_model: str = Field(
        default="openai/gpt-oss-20b",
        min_length=1,
        validation_alias="SUPERVISOR_LLM_MODEL",
    )

    supervisor_llm_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        validation_alias="SUPERVISOR_LLM_TEMPERATURE",
    )

    collector_llm_provider: Literal["ollama", "groq", "openai"] = Field(
        default="groq",
        validation_alias="COLLECTOR_LLM_PROVIDER",
    )

    collector_llm_model: str = Field(
        default="openai/gpt-oss-20b",
        validation_alias="COLLECTOR_LLM_MODEL",
    )

    # Authentication
    auth_session_ttl_hours: int = Field(
        default=168,
        ge=1,
        le=720,
        validation_alias="AUTH_SESSION_TTL_HOURS",
    )

    auth_cookie_secure: bool = Field(
        default=False,
        validation_alias="AUTH_COOKIE_SECURE",
    )

    frontend_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        validation_alias="FRONTEND_ORIGINS",
    )
