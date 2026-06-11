"""Async client for the FRED (Federal Reserve Economic Data) API.

Fetches the macro indicator series EDGAR-X tracks and normalises them into
timestamped observations. Missing observations (FRED encodes them as ``"."``)
are skipped with a debug log rather than coerced to zero.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from types import TracebackType
from typing import ClassVar

import httpx
from pydantic import BaseModel, ConfigDict

from core.config import get_settings
from core.logging import get_logger
from ingestion.sources.http_utils import (
    AsyncRateLimiter,
    ConfigurationError,
    request_with_retry,
)

logger = get_logger(__name__)


class FredSeries(StrEnum):
    """The macro indicator series tracked by EDGAR-X."""

    FEDFUNDS = "FEDFUNDS"
    CPIAUCSL = "CPIAUCSL"
    UNRATE = "UNRATE"
    GDP = "GDP"
    DGS10 = "DGS10"
    T10Y2Y = "T10Y2Y"


class MacroObservation(BaseModel):
    """A single observation of a macro series."""

    model_config = ConfigDict(frozen=True)

    series_id: str
    timestamp: date
    value: float


class MacroSeries(BaseModel):
    """A normalised time series for one FRED series."""

    series_id: str
    observations: list[MacroObservation]


class FredClient:
    """Async FRED API client with rate limiting and retry.

    Usage::

        async with FredClient() as client:
            series = await client.get_series(FredSeries.FEDFUNDS)
    """

    BASE_URL: ClassVar[str] = "https://api.stlouisfed.org/fred"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        requests_per_second: float = 5.0,
        max_attempts: int = 3,
        backoff_base: float = 0.5,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Initialise the client.

        Args:
            api_key: FRED API key; falls back to ``FRED_API_KEY`` env var.
            client: Optional pre-built ``httpx.AsyncClient`` (owned by caller).
            requests_per_second: Client-side rate cap.
            max_attempts: Retry attempts per request.
            backoff_base: Base seconds for exponential backoff.
            timeout_seconds: Per-request timeout for the default client.

        Raises:
            ConfigurationError: If no API key is available.
        """
        self._api_key = api_key or get_settings().fred_api_key
        if not self._api_key:
            raise ConfigurationError("FRED_API_KEY is not configured")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._rate_limiter = AsyncRateLimiter(max_rate=requests_per_second)
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base

    async def __aenter__(self) -> FredClient:
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the underlying HTTP client if this instance owns it."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this instance owns it."""
        if self._owns_client:
            await self._client.aclose()

    async def get_series(
        self,
        series: FredSeries | str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> MacroSeries:
        """Fetch observations for one series.

        Args:
            series: Series identifier (enum member or raw FRED series id).
            start_date: Inclusive lower bound on observation date.
            end_date: Inclusive upper bound on observation date.

        Returns:
            The normalised series. Missing observations are omitted.
        """
        series_id = str(series)
        params: dict[str, str] = {
            "series_id": series_id,
            "api_key": self._api_key or "",
            "file_type": "json",
        }
        if start_date:
            params["observation_start"] = start_date.isoformat()
        if end_date:
            params["observation_end"] = end_date.isoformat()
        response = await request_with_retry(
            self._client,
            "GET",
            f"{self.BASE_URL}/series/observations",
            rate_limiter=self._rate_limiter,
            max_attempts=self._max_attempts,
            backoff_base=self._backoff_base,
            params=params,
        )
        observations: list[MacroObservation] = []
        skipped = 0
        for row in response.json().get("observations", []):
            raw_value = row.get("value", ".")
            if raw_value == ".":
                skipped += 1
                continue
            observations.append(
                MacroObservation(
                    series_id=series_id,
                    timestamp=date.fromisoformat(row["date"]),
                    value=float(raw_value),
                )
            )
        if skipped:
            logger.debug("fred_missing_observations_skipped", series_id=series_id, count=skipped)
        logger.info("fred_series_fetched", series_id=series_id, observations=len(observations))
        return MacroSeries(series_id=series_id, observations=observations)

    async def get_all_tracked_series(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, MacroSeries]:
        """Fetch every series in :class:`FredSeries`.

        Args:
            start_date: Inclusive lower bound on observation date.
            end_date: Inclusive upper bound on observation date.

        Returns:
            Mapping of series id to its normalised series.
        """
        results: dict[str, MacroSeries] = {}
        for series in FredSeries:
            results[series.value] = await self.get_series(
                series, start_date=start_date, end_date=end_date
            )
        return results
