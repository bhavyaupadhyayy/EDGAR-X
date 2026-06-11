"""Unit tests for the Polygon.io options client (all HTTP mocked via respx)."""

from __future__ import annotations

from typing import Any

import pytest
import respx

from ingestion.sources.http_utils import ConfigurationError
from ingestion.sources.polygon_client import PolygonClient

SNAPSHOT_URL = "https://api.polygon.io/v3/snapshot/options/AAPL"


def _contract(
    ticker: str,
    *,
    volume: int,
    open_interest: int,
    contract_type: str = "call",
    iv: float | None = 0.42,
) -> dict[str, Any]:
    return {
        "details": {
            "ticker": ticker,
            "contract_type": contract_type,
            "strike_price": 200.0,
            "expiration_date": "2026-07-17",
        },
        "day": {"volume": volume},
        "open_interest": open_interest,
        "implied_volatility": iv,
    }


class TestChainSnapshot:
    """Chain snapshot parsing and pagination."""

    async def test_parses_contracts(self, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(SNAPSHOT_URL).respond(
            200,
            json={"results": [_contract("O:AAPL260717C00200000", volume=500, open_interest=1000)]},
        )
        async with PolygonClient() as client:
            contracts = await client.get_options_chain_snapshot("AAPL")
        assert len(contracts) == 1
        assert contracts[0].underlying == "AAPL"
        assert contracts[0].day_volume == 500
        assert contracts[0].implied_volatility == 0.42

    async def test_follows_next_url_pagination(self, respx_mock: respx.MockRouter) -> None:
        next_url = "https://api.polygon.io/v3/snapshot/options/AAPL?cursor=abc"
        respx_mock.get(SNAPSHOT_URL).mock(
            side_effect=lambda request: _page_response(request, next_url)
        )
        async with PolygonClient() as client:
            contracts = await client.get_options_chain_snapshot("AAPL")
        assert len(contracts) == 2

    async def test_malformed_contract_is_skipped(self, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(SNAPSHOT_URL).respond(
            200,
            json={
                "results": [
                    {"details": {"ticker": "broken"}},
                    _contract("O:AAPL260717C00200000", volume=10, open_interest=10),
                ]
            },
        )
        async with PolygonClient() as client:
            contracts = await client.get_options_chain_snapshot("AAPL")
        assert len(contracts) == 1


def _page_response(request: Any, next_url: str) -> Any:
    """Return page 1 with a next_url, page 2 without."""
    import httpx

    if "cursor" in str(request.url):
        return httpx.Response(
            200, json={"results": [_contract("O:AAPL2", volume=1, open_interest=1)]}
        )
    return httpx.Response(
        200,
        json={
            "results": [_contract("O:AAPL1", volume=1, open_interest=1)],
            "next_url": next_url,
        },
    )


class TestUnusualActivity:
    """The volume / open-interest flagging heuristic."""

    async def test_flags_high_ratio_contracts(self, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(SNAPSHOT_URL).respond(
            200,
            json={
                "results": [
                    _contract("O:HOT", volume=5000, open_interest=1000),  # ratio 5 -> flagged
                    _contract("O:COLD", volume=500, open_interest=1000),  # ratio 0.5 -> not
                ]
            },
        )
        async with PolygonClient() as client:
            events = await client.detect_unusual_activity("AAPL")
        assert [e.contract.contract_ticker for e in events] == ["O:HOT"]
        assert events[0].volume_oi_ratio == 5.0

    async def test_low_volume_filtered_even_with_high_ratio(
        self, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(SNAPSHOT_URL).respond(
            200, json={"results": [_contract("O:TINY", volume=50, open_interest=1)]}
        )
        async with PolygonClient() as client:
            assert await client.detect_unusual_activity("AAPL") == []

    async def test_zero_open_interest_uses_raw_volume(
        self, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(SNAPSHOT_URL).respond(
            200, json={"results": [_contract("O:NEW", volume=400, open_interest=0)]}
        )
        async with PolygonClient() as client:
            events = await client.detect_unusual_activity("AAPL")
        assert len(events) == 1
        assert events[0].volume_oi_ratio == 400.0

    async def test_sorted_by_descending_ratio(self, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(SNAPSHOT_URL).respond(
            200,
            json={
                "results": [
                    _contract("O:MED", volume=4000, open_interest=1000),
                    _contract("O:TOP", volume=9000, open_interest=1000),
                ]
            },
        )
        async with PolygonClient() as client:
            events = await client.detect_unusual_activity("AAPL")
        assert [e.contract.contract_ticker for e in events] == ["O:TOP", "O:MED"]

    async def test_kafka_payload_shape(self, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(SNAPSHOT_URL).respond(
            200, json={"results": [_contract("O:HOT", volume=5000, open_interest=1000)]}
        )
        async with PolygonClient() as client:
            events = await client.detect_unusual_activity("AAPL")
        payload = events[0].to_kafka_payload()
        assert payload["underlying"] == "AAPL"
        assert payload["volume_oi_ratio"] == 5.0
        assert payload["day_volume"] == 5000

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from core.config import get_settings

        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        get_settings.cache_clear()
        with pytest.raises(ConfigurationError):
            PolygonClient()
