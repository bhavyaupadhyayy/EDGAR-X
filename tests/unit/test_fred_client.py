"""Unit tests for the FRED macro client (all HTTP mocked via respx)."""

from __future__ import annotations

from datetime import date

import pytest
import respx

from ingestion.sources.fred_client import FredClient, FredSeries
from ingestion.sources.http_utils import ConfigurationError

OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"

PAYLOAD = {
    "observations": [
        {"date": "2026-05-01", "value": "5.25"},
        {"date": "2026-05-02", "value": "."},
        {"date": "2026-05-03", "value": "5.50"},
    ]
}


class TestFredClient:
    """Series fetching and normalisation."""

    async def test_get_series_normalises_observations(
        self, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(OBSERVATIONS_URL).respond(200, json=PAYLOAD)
        async with FredClient() as client:
            series = await client.get_series(FredSeries.FEDFUNDS)
        assert series.series_id == "FEDFUNDS"
        assert len(series.observations) == 2
        assert series.observations[0].timestamp == date(2026, 5, 1)
        assert series.observations[0].value == 5.25

    async def test_missing_values_are_skipped(self, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(OBSERVATIONS_URL).respond(200, json=PAYLOAD)
        async with FredClient() as client:
            series = await client.get_series(FredSeries.DGS10)
        assert all(obs.value != 0 for obs in series.observations)
        assert [obs.value for obs in series.observations] == [5.25, 5.50]

    async def test_date_range_passed_as_params(self, respx_mock: respx.MockRouter) -> None:
        route = respx_mock.get(OBSERVATIONS_URL).respond(200, json={"observations": []})
        async with FredClient() as client:
            await client.get_series(
                FredSeries.GDP, start_date=date(2026, 1, 1), end_date=date(2026, 6, 1)
            )
        params = route.calls.last.request.url.params
        assert params["observation_start"] == "2026-01-01"
        assert params["observation_end"] == "2026-06-01"
        assert params["series_id"] == "GDP"

    async def test_fetches_all_tracked_series(self, respx_mock: respx.MockRouter) -> None:
        route = respx_mock.get(OBSERVATIONS_URL).respond(200, json=PAYLOAD)
        async with FredClient() as client:
            result = await client.get_all_tracked_series()
        assert set(result) == {s.value for s in FredSeries}
        assert route.call_count == len(FredSeries)

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from core.config import get_settings

        monkeypatch.delenv("FRED_API_KEY", raising=False)
        get_settings.cache_clear()
        with pytest.raises(ConfigurationError):
            FredClient()
