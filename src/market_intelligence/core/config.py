from pathlib import Path

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
