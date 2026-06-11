"""Async client for Polygon.io options data.

Pulls the full options-chain snapshot for an underlying and flags unusual
activity: contracts where same-day volume is a large multiple of open
interest (a standard "new positioning" heuristic).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import TracebackType
from typing import Any, ClassVar, Literal

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


class OptionsContractSnapshot(BaseModel):
    """Snapshot of a single options contract from the chain endpoint."""

    model_config = ConfigDict(frozen=True)

    contract_ticker: str
    underlying: str
    contract_type: Literal["call", "put"]
    strike: float
    expiration: date
    day_volume: int
    open_interest: int
    implied_volatility: float | None = None


class UnusualActivity(BaseModel):
    """A contract flagged for unusual volume relative to open interest."""

    contract: OptionsContractSnapshot
    volume_oi_ratio: float
    detected_at: datetime

    def to_kafka_payload(self) -> dict[str, Any]:
        """Render this event as a dict conforming to ``options.avsc``."""
        return {
            "underlying": self.contract.underlying,
            "contract_ticker": self.contract.contract_ticker,
            "contract_type": self.contract.contract_type,
            "strike": self.contract.strike,
            "expiration": self.contract.expiration,
            "day_volume": self.contract.day_volume,
            "open_interest": self.contract.open_interest,
            "volume_oi_ratio": self.volume_oi_ratio,
            "implied_volatility": self.contract.implied_volatility,
            "detected_at": self.detected_at,
        }


class PolygonClient:
    """Async Polygon.io client focused on options unusual activity.

    Usage::

        async with PolygonClient() as client:
            events = await client.detect_unusual_activity("AAPL")
    """

    BASE_URL: ClassVar[str] = "https://api.polygon.io"

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
            api_key: Polygon API key; falls back to ``POLYGON_API_KEY`` env var.
            client: Optional pre-built ``httpx.AsyncClient`` (owned by caller).
            requests_per_second: Client-side rate cap.
            max_attempts: Retry attempts per request.
            backoff_base: Base seconds for exponential backoff.
            timeout_seconds: Per-request timeout for the default client.

        Raises:
            ConfigurationError: If no API key is available.
        """
        self._api_key = api_key or get_settings().polygon_api_key
        if not self._api_key:
            raise ConfigurationError("POLYGON_API_KEY is not configured")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._rate_limiter = AsyncRateLimiter(max_rate=requests_per_second)
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base

    async def __aenter__(self) -> PolygonClient:
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

    async def _get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """Issue an authenticated GET and return the JSON body.

        The API key is merged into the URL (not passed as ``params``) so that
        query strings already present — e.g. the pagination cursor inside
        Polygon's ``next_url`` — are preserved.
        """
        merged = dict(params or {})
        merged["apiKey"] = self._api_key or ""
        full_url = httpx.URL(url).copy_merge_params(merged)
        response = await request_with_retry(
            self._client,
            "GET",
            str(full_url),
            rate_limiter=self._rate_limiter,
            max_attempts=self._max_attempts,
            backoff_base=self._backoff_base,
        )
        return dict(response.json())

    async def get_options_chain_snapshot(
        self, underlying: str, *, max_pages: int = 10
    ) -> list[OptionsContractSnapshot]:
        """Fetch the full options-chain snapshot for an underlying ticker.

        Follows ``next_url`` pagination up to ``max_pages`` pages.

        Args:
            underlying: Underlying equity ticker, e.g. ``"AAPL"``.
            max_pages: Safety cap on pagination depth.

        Returns:
            Parsed contract snapshots. Contracts missing required fields are
            skipped with a debug log.
        """
        url: str | None = f"{self.BASE_URL}/v3/snapshot/options/{underlying.upper()}"
        contracts: list[OptionsContractSnapshot] = []
        pages = 0
        while url is not None and pages < max_pages:
            payload = await self._get(url)
            for result in payload.get("results", []):
                snapshot = self._parse_contract(result, underlying.upper())
                if snapshot is not None:
                    contracts.append(snapshot)
            url = payload.get("next_url")
            pages += 1
        logger.info(
            "polygon_chain_snapshot_fetched",
            underlying=underlying,
            contracts=len(contracts),
            pages=pages,
        )
        return contracts

    async def detect_unusual_activity(
        self,
        underlying: str,
        *,
        min_volume: int = 100,
        volume_oi_ratio_threshold: float = 3.0,
    ) -> list[UnusualActivity]:
        """Flag contracts with unusually high volume relative to open interest.

        Contracts with zero open interest are flagged whenever volume exceeds
        ``min_volume`` (all volume is new positioning); the ratio is reported
        as the raw volume in that case.

        Args:
            underlying: Underlying equity ticker.
            min_volume: Minimum day volume to consider (filters noise).
            volume_oi_ratio_threshold: Flag when volume / open interest
                meets or exceeds this multiple.

        Returns:
            Flagged contracts sorted by descending ratio.
        """
        detected_at = datetime.now(UTC)
        events: list[UnusualActivity] = []
        for contract in await self.get_options_chain_snapshot(underlying):
            if contract.day_volume < min_volume:
                continue
            if contract.open_interest > 0:
                ratio = contract.day_volume / contract.open_interest
            else:
                ratio = float(contract.day_volume)
            if ratio >= volume_oi_ratio_threshold:
                events.append(
                    UnusualActivity(
                        contract=contract, volume_oi_ratio=ratio, detected_at=detected_at
                    )
                )
        events.sort(key=lambda event: event.volume_oi_ratio, reverse=True)
        logger.info("polygon_unusual_activity", underlying=underlying, flagged=len(events))
        return events

    @staticmethod
    def _parse_contract(
        result: dict[str, Any], underlying: str
    ) -> OptionsContractSnapshot | None:
        """Parse one chain-snapshot result; return None when fields are missing."""
        details = result.get("details", {})
        try:
            return OptionsContractSnapshot(
                contract_ticker=details["ticker"],
                underlying=underlying,
                contract_type=details["contract_type"],
                strike=float(details["strike_price"]),
                expiration=date.fromisoformat(details["expiration_date"]),
                day_volume=int(result.get("day", {}).get("volume", 0) or 0),
                open_interest=int(result.get("open_interest", 0) or 0),
                implied_volatility=result.get("implied_volatility"),
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("polygon_contract_skipped", error=str(exc), raw_keys=list(details))
            return None
