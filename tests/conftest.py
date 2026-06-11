"""Shared pytest fixtures for the EDGAR-X test suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Provide deterministic env-derived settings for every test.

    Sets test API keys, prevents any local ``.env`` from leaking into tests,
    and clears the settings cache around each test.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("EDGAR_USER_AGENT", "edgar-x-tests (contact: tests@example.com)")
    monkeypatch.setenv("FRED_API_KEY", "test-fred-key")
    monkeypatch.setenv("POLYGON_API_KEY", "test-polygon-key")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    monkeypatch.setenv("SCHEMA_REGISTRY_URL", "http://localhost:8081")
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
