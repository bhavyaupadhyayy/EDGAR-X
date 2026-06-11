"""Centralised application configuration.

All runtime configuration is sourced from environment variables (optionally
via a local ``.env`` file). No credentials are ever hardcoded; see
``.env.example`` at the repository root for the full list of expected keys.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_CONTACT = "you@example.com"


class Settings(BaseSettings):
    """Application settings loaded from the environment / ``.env`` file.

    Attributes:
        edgar_user_agent: User-Agent header for SEC EDGAR (SEC requires a
            descriptive value with a contact email).
        fred_api_key: API key for the FRED macro data API.
        polygon_api_key: API key for Polygon.io.
        reddit_client_id: OAuth client id for the Reddit API.
        reddit_client_secret: OAuth client secret for the Reddit API.
        reddit_user_agent: User-Agent for Reddit API requests.
        kafka_bootstrap_servers: Comma-separated Kafka bootstrap servers.
        schema_registry_url: Confluent Schema Registry base URL.
        redis_url: Redis connection URL for the hot cache.
        slack_webhook_url: Optional Slack webhook for pipeline alerting.
        anthropic_api_key: Anthropic API key (Layer 4 onward).
        daily_spend_cap_usd: Hard daily spend cap for LLM API usage.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    edgar_user_agent: str = f"EDGAR-X research bot (contact: {_PLACEHOLDER_CONTACT})"
    fred_api_key: str | None = None
    polygon_api_key: str | None = None
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "edgar-x:v0.1"
    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"
    redis_url: str = "redis://localhost:6379/0"
    slack_webhook_url: str | None = None
    anthropic_api_key: str | None = None
    daily_spend_cap_usd: float = 50.0

    def edgar_user_agent_is_placeholder(self) -> bool:
        """Return True when the EDGAR User-Agent still contains the placeholder contact."""
        return _PLACEHOLDER_CONTACT in self.edgar_user_agent


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance."""
    return Settings()
