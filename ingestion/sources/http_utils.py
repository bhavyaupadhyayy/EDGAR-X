"""Shared async HTTP plumbing for all ingestion source clients.

Provides a token-bucket rate limiter and an exponential-backoff retry wrapper
used by every external API client so that throttling and retry semantics are
consistent (and tested) in one place.
"""

from __future__ import annotations

import asyncio
import random
import time

import httpx

from core.logging import get_logger

logger = get_logger(__name__)

#: HTTP status codes that are worth retrying (throttling / transient server errors).
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class IngestionError(Exception):
    """Base class for all ingestion-layer errors."""


class ConfigurationError(IngestionError):
    """Raised when a client is constructed without required configuration."""


class TransientHTTPError(IngestionError):
    """Raised internally for retryable HTTP status codes.

    Attributes:
        status_code: The HTTP status code that triggered the retry.
        url: The request URL.
    """

    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"transient HTTP {status_code} from {url}")
        self.status_code = status_code
        self.url = url


class RetryExhaustedError(IngestionError):
    """Raised when all retry attempts for a request have failed."""


class AsyncRateLimiter:
    """Token-bucket rate limiter for asyncio code.

    Allows at most ``max_rate`` acquisitions per ``time_period`` seconds,
    smoothing bursts across concurrent tasks.
    """

    def __init__(self, max_rate: float, time_period: float = 1.0) -> None:
        """Initialise the bucket.

        Args:
            max_rate: Maximum number of acquisitions per ``time_period``.
            time_period: Window length in seconds (default one second).

        Raises:
            ValueError: If ``max_rate`` or ``time_period`` is not positive.
        """
        if max_rate <= 0 or time_period <= 0:
            raise ValueError("max_rate and time_period must be positive")
        self._max_rate = max_rate
        self._time_period = time_period
        self._tokens = max_rate
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available, then consume it."""
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated_at
                refill_rate = self._max_rate / self._time_period
                self._tokens = min(self._max_rate, self._tokens + elapsed * refill_rate)
                self._updated_at = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                await asyncio.sleep((1.0 - self._tokens) / refill_rate)


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    rate_limiter: AsyncRateLimiter | None = None,
    max_attempts: int = 3,
    backoff_base: float = 0.5,
    **kwargs: object,
) -> httpx.Response:
    """Issue an HTTP request with rate limiting and exponential-backoff retries.

    Retries on transport errors and on :data:`RETRYABLE_STATUS_CODES`.
    Non-retryable 4xx responses raise :class:`httpx.HTTPStatusError` immediately.

    Args:
        client: The shared ``httpx.AsyncClient`` to issue the request with.
        method: HTTP method, e.g. ``"GET"``.
        url: Absolute request URL.
        rate_limiter: Optional limiter acquired before every attempt.
        max_attempts: Total attempts including the first (default 3).
        backoff_base: Base delay in seconds; attempt *n* waits
            ``backoff_base * 2**(n-1)`` plus jitter.
        **kwargs: Passed through to ``httpx.AsyncClient.request``.

    Returns:
        The successful ``httpx.Response``.

    Raises:
        RetryExhaustedError: When every attempt failed with a retryable error.
        httpx.HTTPStatusError: For non-retryable HTTP error statuses.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        if rate_limiter is not None:
            await rate_limiter.acquire()
        try:
            response = await client.request(method, url, **kwargs)  # type: ignore[arg-type]
            if response.status_code in RETRYABLE_STATUS_CODES:
                raise TransientHTTPError(response.status_code, url)
            response.raise_for_status()
            return response
        except (httpx.TransportError, TransientHTTPError) as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            delay = backoff_base * 2 ** (attempt - 1) + random.uniform(0, backoff_base / 10)
            logger.warning(
                "http_retry",
                url=url,
                method=method,
                attempt=attempt,
                max_attempts=max_attempts,
                delay_seconds=round(delay, 3),
                error=str(exc),
            )
            await asyncio.sleep(delay)
    logger.error("http_retry_exhausted", url=url, method=method, error=str(last_error))
    raise RetryExhaustedError(
        f"{method} {url} failed after {max_attempts} attempts"
    ) from last_error
