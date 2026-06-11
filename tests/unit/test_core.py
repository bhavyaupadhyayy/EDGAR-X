"""Unit tests for core configuration and logging."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import structlog

from core.config import Settings, get_settings
from core.logging import bind_correlation_id, clear_correlation_id, configure_logging, get_logger


@pytest.fixture(autouse=True)
def reset_structlog() -> Iterator[None]:
    """Restore structlog defaults so configuration never leaks across tests."""
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


class TestSettings:
    """Environment-driven configuration."""

    def test_reads_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FRED_API_KEY", "abc123")
        monkeypatch.setenv("DAILY_SPEND_CAP_USD", "25.5")
        settings = Settings()
        assert settings.fred_api_key == "abc123"
        assert settings.daily_spend_cap_usd == 25.5

    def test_defaults_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
        settings = Settings(_env_file=None)
        assert settings.kafka_bootstrap_servers == "localhost:9092"
        assert settings.daily_spend_cap_usd == 50.0

    def test_get_settings_is_cached(self) -> None:
        assert get_settings() is get_settings()

    def test_placeholder_detection(self) -> None:
        placeholder = Settings(edgar_user_agent="bot (contact: you@example.com)")
        real = Settings(edgar_user_agent="bot (contact: real@corp.com)")
        assert placeholder.edgar_user_agent_is_placeholder()
        assert not real.edgar_user_agent_is_placeholder()


class TestLogging:
    """structlog configuration and correlation ids."""

    def test_configure_and_log(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging()
        get_logger("test").info("hello_event", answer=42)
        output = capsys.readouterr().out
        assert '"event": "hello_event"' in output
        assert '"answer": 42' in output
        assert '"timestamp"' in output

    def test_correlation_id_bound_and_cleared(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging()
        cid = bind_correlation_id()
        get_logger("test").info("with_cid")
        assert cid in capsys.readouterr().out
        clear_correlation_id()
        get_logger("test").info("without_cid")
        assert cid not in capsys.readouterr().out

    def test_explicit_correlation_id(self) -> None:
        assert bind_correlation_id("fixed-id") == "fixed-id"
        clear_correlation_id()
