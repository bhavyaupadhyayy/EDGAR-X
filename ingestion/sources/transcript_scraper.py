"""Async scraper for earnings-call transcripts from Motley Fool public pages.

Parses the article into speaker-attributed segments and splits prepared
remarks from the Q&A session. Scraping is throttled to 1 request/second as a
politeness cap and identifies itself with the EDGAR-X User-Agent.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Literal

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field

from core.config import get_settings
from core.logging import get_logger
from ingestion.sources.http_utils import AsyncRateLimiter, IngestionError, request_with_retry

logger = get_logger(__name__)

#: e.g. "Apple (AAPL) Q1 2026 Earnings Call Transcript"
_TITLE_RE = re.compile(
    r"^(?P<company>.+?)\s*\((?:[A-Z]+:\s*)?(?P<ticker>[A-Z.]{1,6})\)\s+"
    r"Q(?P<quarter>[1-4])\s+(?P<year>\d{4})\s+Earnings\s+Call",
    re.IGNORECASE,
)
_QA_HEADING_RE = re.compile(r"questions?\s*(?:&|and)\s*answers?", re.IGNORECASE)

SectionKind = Literal["prepared_remarks", "qa"]


class TranscriptParseError(IngestionError):
    """Raised when a transcript page cannot be parsed into segments."""


class TranscriptSegment(BaseModel):
    """One speaker turn in an earnings call."""

    model_config = ConfigDict(frozen=True)

    speaker: str
    role: str | None = None
    section: SectionKind
    text: str


class EarningsTranscript(BaseModel):
    """A parsed earnings-call transcript."""

    company_name: str
    ticker: str | None = None
    quarter: int | None = None
    fiscal_year: int | None = None
    url: str
    segments: list[TranscriptSegment] = Field(default_factory=list)

    def to_kafka_payload(self) -> dict[str, Any]:
        """Render this transcript as a dict conforming to ``transcript.avsc``."""
        return {
            "company_name": self.company_name,
            "ticker": self.ticker,
            "quarter": self.quarter,
            "fiscal_year": self.fiscal_year,
            "url": self.url,
            "segments": [segment.model_dump() for segment in self.segments],
            "ingested_at": datetime.now(UTC),
        }


class TranscriptScraper:
    """Async scraper for Motley Fool earnings-call transcript pages.

    Usage::

        async with TranscriptScraper() as scraper:
            transcript = await scraper.fetch_transcript(url)
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        requests_per_second: float = 1.0,
        max_attempts: int = 3,
        backoff_base: float = 0.5,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Initialise the scraper.

        Args:
            client: Optional pre-built ``httpx.AsyncClient`` (owned by caller).
            requests_per_second: Politeness rate cap (default 1/sec).
            max_attempts: Retry attempts per request.
            backoff_base: Base seconds for exponential backoff.
            timeout_seconds: Per-request timeout for the default client.
        """
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds, follow_redirects=True
        )
        self._rate_limiter = AsyncRateLimiter(max_rate=requests_per_second)
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._user_agent = get_settings().edgar_user_agent

    async def __aenter__(self) -> TranscriptScraper:
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

    async def fetch_transcript(self, url: str) -> EarningsTranscript:
        """Fetch and parse one transcript page.

        Args:
            url: Absolute URL of the Motley Fool transcript article.

        Returns:
            The parsed transcript.

        Raises:
            TranscriptParseError: If the page lacks a recognisable article body.
        """
        response = await request_with_retry(
            self._client,
            "GET",
            url,
            rate_limiter=self._rate_limiter,
            max_attempts=self._max_attempts,
            backoff_base=self._backoff_base,
            headers={"User-Agent": self._user_agent},
        )
        transcript = self.parse_html(response.text, url=url)
        logger.info(
            "transcript_fetched",
            url=url,
            ticker=transcript.ticker,
            segments=len(transcript.segments),
        )
        return transcript

    @classmethod
    def parse_html(cls, html: str, *, url: str) -> EarningsTranscript:
        """Parse transcript HTML into a structured transcript.

        The Motley Fool article layout uses ``<h2>`` headings for the
        "Prepared Remarks" / "Questions & Answers" sections and ``<strong>``
        (or ``<b>``) elements naming each speaker, followed by paragraphs of
        their remarks. An optional ``<em>`` after the speaker carries their
        role/title.

        Args:
            html: Raw page HTML.
            url: Source URL recorded on the transcript.

        Returns:
            The parsed transcript.

        Raises:
            TranscriptParseError: If no article body or speakers are found.
        """
        soup = BeautifulSoup(html, "lxml")
        title_text = soup.find("h1").get_text(strip=True) if soup.find("h1") else ""
        company_name, ticker, quarter, fiscal_year = cls._parse_title(title_text)

        body = soup.find("article") or soup.find("div", class_="article-body")
        if body is None:
            raise TranscriptParseError(f"no article body found at {url}")

        segments: list[TranscriptSegment] = []
        section: SectionKind = "prepared_remarks"
        current_speaker: str | None = None
        current_role: str | None = None
        current_text: list[str] = []

        def flush() -> None:
            if current_speaker and current_text:
                segments.append(
                    TranscriptSegment(
                        speaker=current_speaker,
                        role=current_role,
                        section=section,
                        text=" ".join(current_text).strip(),
                    )
                )

        for element in body.find_all(["h2", "p"]):
            if element.name == "h2":
                if _QA_HEADING_RE.search(element.get_text()):
                    flush()
                    current_speaker, current_role, current_text = None, None, []
                    section = "qa"
                continue
            speaker_tag = element.find(["strong", "b"])
            if speaker_tag is not None and len(element.get_text(strip=True)) < 120:
                flush()
                current_speaker = speaker_tag.get_text(strip=True).rstrip(":")
                role_tag = element.find("em")
                current_role = role_tag.get_text(strip=True) if role_tag else None
                current_text = []
            elif current_speaker is not None:
                text = element.get_text(" ", strip=True)
                if text:
                    current_text.append(text)
        flush()

        if not segments:
            raise TranscriptParseError(f"no speaker segments parsed at {url}")
        return EarningsTranscript(
            company_name=company_name or title_text or "unknown",
            ticker=ticker,
            quarter=quarter,
            fiscal_year=fiscal_year,
            url=url,
            segments=segments,
        )

    @staticmethod
    def _parse_title(title: str) -> tuple[str, str | None, int | None, int | None]:
        """Extract company, ticker, quarter, and fiscal year from the headline."""
        match = _TITLE_RE.match(title)
        if match is None:
            return title, None, None, None
        return (
            match.group("company").strip(),
            match.group("ticker").upper(),
            int(match.group("quarter")),
            int(match.group("year")),
        )
