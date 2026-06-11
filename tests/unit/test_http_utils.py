"""Unit tests for the shared HTTP rate limiter and retry wrapper."""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from ingestion.sources.http_utils import (
    AsyncRateLimiter,
    RetryExhaustedError,
    request_with_retry,
)


class TestAsyncRateLimiter:
    """Behavioural tests for the token-bucket limiter."""

    async def test_allows_burst_up_to_capacity(self) -> None:
        limiter = AsyncRateLimiter(max_rate=5.0)
        start = time.monotonic()
        for _ in range(5):
            await limiter.acquire()
        assert time.monotonic() - start < 0.1

    async def test_throttles_beyond_capacity(self) -> None:
        limiter = AsyncRateLimiter(max_rate=50.0)
        start = time.monotonic()
        for _ in range(60):
            await limiter.acquire()
        # 10 acquisitions beyond capacity at 50/sec needs roughly 0.2 seconds.
        assert time.monotonic() - start >= 0.15

    def test_rejects_non_positive_rate(self) -> None:
        with pytest.raises(ValueError):
            AsyncRateLimiter(max_rate=0)


class TestRequestWithRetry:
    """Retry/backoff semantics against a mocked transport."""

    async def test_returns_successful_response(self, respx_mock: respx.MockRouter) -> None:
        respx_mock.get("https://api.test/ok").respond(200, json={"ok": True})
        async with httpx.AsyncClient() as client:
            response = await request_with_retry(client, "GET", "https://api.test/ok")
        assert response.json() == {"ok": True}

    async def test_retries_transient_status_then_succeeds(
        self, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.get("https://api.test/flaky")
        route.side_effect = [httpx.Response(503), httpx.Response(200, json={"ok": True})]
        async with httpx.AsyncClient() as client:
            response = await request_with_retry(
                client, "GET", "https://api.test/flaky", backoff_base=0.01
            )
        assert response.status_code == 200
        assert route.call_count == 2

    async def test_raises_after_exhausting_attempts(self, respx_mock: respx.MockRouter) -> None:
        route = respx_mock.get("https://api.test/down").respond(503)
        async with httpx.AsyncClient() as client:
            with pytest.raises(RetryExhaustedError):
                await request_with_retry(
                    client, "GET", "https://api.test/down", max_attempts=3, backoff_base=0.01
                )
        assert route.call_count == 3

    async def test_retries_transport_errors(self, respx_mock: respx.MockRouter) -> None:
        route = respx_mock.get("https://api.test/conn")
        route.side_effect = [httpx.ConnectError("boom"), httpx.Response(200)]
        async with httpx.AsyncClient() as client:
            response = await request_with_retry(
                client, "GET", "https://api.test/conn", backoff_base=0.01
            )
        assert response.status_code == 200

    async def test_does_not_retry_client_errors(self, respx_mock: respx.MockRouter) -> None:
        route = respx_mock.get("https://api.test/missing").respond(404)
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await request_with_retry(client, "GET", "https://api.test/missing")
        assert route.call_count == 1
