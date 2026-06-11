"""Async client for the SEC EDGAR APIs.

Covers three public endpoints:

* ``https://www.sec.gov/files/company_tickers.json`` — ticker → CIK mapping.
* ``https://data.sec.gov/submissions/CIK{cik}.json`` — filing index per company.
* ``https://efts.sec.gov/LATEST/search-index`` — EDGAR full-text search.

The SEC fair-access policy caps clients at 10 requests/second and requires a
descriptive ``User-Agent`` containing a contact email; both are enforced here.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from types import TracebackType
from typing import Any, ClassVar

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field

from core.config import get_settings
from core.logging import get_logger
from ingestion.sources.http_utils import AsyncRateLimiter, request_with_retry

logger = get_logger(__name__)

#: Form types ingested by default.
DEFAULT_FORM_TYPES: tuple[str, ...] = ("10-K", "10-Q", "8-K", "DEF 14A", "S-1")

#: Minimum body length for a parsed section — filters out table-of-contents hits.
_MIN_SECTION_LENGTH = 200

#: Item-number → canonical section name, per form type (best effort).
_SECTION_MAPS: dict[str, dict[str, str]] = {
    "10-K": {
        "1": "business",
        "1A": "risk_factors",
        "7": "mdna",
        "8": "financial_statements",
    },
    # 10-Q part I: item 1 = financial statements, item 2 = MD&A;
    # part II item 1A = risk factors. Item numbers repeat across parts, so
    # this mapping is best-effort on the flattened document text.
    "10-Q": {
        "1": "financial_statements",
        "1A": "risk_factors",
        "2": "mdna",
    },
}

_ITEM_HEADER_RE = re.compile(r"(?im)^\s*item\s+(\d{1,2}A?)\s*[.:—-]?\s")
_FOOTNOTES_RE = re.compile(
    r"(?i)notes\s+to\s+(?:the\s+)?(?:condensed\s+)?consolidated\s+financial\s+statements"
)


class FilingMetadata(BaseModel):
    """Identifying metadata for a single EDGAR filing."""

    model_config = ConfigDict(frozen=True)

    accession_number: str
    cik: str = Field(description="Zero-padded 10-digit CIK")
    ticker: str | None = None
    company_name: str
    form_type: str
    filing_date: date
    primary_document: str
    document_url: str


class FilingSections(BaseModel):
    """Best-effort parsed sections of a filing. Missing sections are ``None``."""

    business: str | None = None
    risk_factors: str | None = None
    mdna: str | None = None
    financial_statements: str | None = None
    footnotes: str | None = None

    def present(self) -> list[str]:
        """Return the names of sections that were successfully parsed."""
        return [name for name, value in self.model_dump().items() if value]


class Filing(BaseModel):
    """A fetched filing: metadata, full plain text, and parsed sections."""

    metadata: FilingMetadata
    raw_text: str
    parsed_sections: FilingSections

    def to_kafka_payload(self) -> dict[str, Any]:
        """Render this filing as a dict conforming to ``filing.avsc``."""
        sections = {
            name: value
            for name, value in self.parsed_sections.model_dump().items()
            if value is not None
        }
        return {
            "accession_number": self.metadata.accession_number,
            "cik": self.metadata.cik,
            "ticker": self.metadata.ticker,
            "company_name": self.metadata.company_name,
            "form_type": self.metadata.form_type,
            "filing_date": self.metadata.filing_date,
            "document_url": self.metadata.document_url,
            "raw_text": self.raw_text,
            "sections": sections,
            "ingested_at": datetime.now(UTC),
        }


class FullTextSearchHit(BaseModel):
    """A single hit from the EDGAR full-text search API."""

    accession_number: str
    cik: str
    form_type: str | None = None
    filing_date: date | None = None
    display_names: list[str] = Field(default_factory=list)


class EdgarClient:
    """Async SEC EDGAR client with rate limiting and retry.

    Usage::

        async with EdgarClient() as client:
            filings = await client.get_filings("AAPL", start_date=date(2026, 1, 1))
            filing = await client.fetch_filing(filings[0])
    """

    TICKER_MAP_URL: ClassVar[str] = "https://www.sec.gov/files/company_tickers.json"
    DATA_BASE_URL: ClassVar[str] = "https://data.sec.gov"
    ARCHIVES_BASE_URL: ClassVar[str] = "https://www.sec.gov"
    FULL_TEXT_SEARCH_URL: ClassVar[str] = "https://efts.sec.gov/LATEST/search-index"

    def __init__(
        self,
        user_agent: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        requests_per_second: float = 10.0,
        max_attempts: int = 3,
        backoff_base: float = 0.5,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Initialise the client.

        Args:
            user_agent: SEC-compliant User-Agent; falls back to settings.
            client: Optional pre-built ``httpx.AsyncClient`` (owned by caller).
            requests_per_second: Rate cap (SEC maximum is 10/sec).
            max_attempts: Retry attempts per request.
            backoff_base: Base seconds for exponential backoff.
            timeout_seconds: Per-request timeout for the default client.
        """
        settings = get_settings()
        self._user_agent = user_agent or settings.edgar_user_agent
        if user_agent is None and settings.edgar_user_agent_is_placeholder():
            logger.warning("edgar_user_agent_placeholder", hint="set EDGAR_USER_AGENT in .env")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._rate_limiter = AsyncRateLimiter(max_rate=min(requests_per_second, 10.0))
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._ticker_map: dict[str, tuple[str, str]] | None = None

    async def __aenter__(self) -> EdgarClient:
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

    async def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        """Issue a rate-limited, retried request with the SEC User-Agent header."""
        headers = {"User-Agent": self._user_agent, "Accept-Encoding": "gzip, deflate"}
        return await request_with_retry(
            self._client,
            method,
            url,
            rate_limiter=self._rate_limiter,
            max_attempts=self._max_attempts,
            backoff_base=self._backoff_base,
            headers=headers,
            **kwargs,
        )

    async def _resolve_ticker(self, ticker: str) -> tuple[str, str]:
        """Resolve a ticker to a zero-padded CIK and company name.

        Args:
            ticker: Exchange ticker symbol, case-insensitive.

        Returns:
            Tuple of (10-digit zero-padded CIK, company title).

        Raises:
            KeyError: If the ticker is unknown to EDGAR.
        """
        if self._ticker_map is None:
            response = await self._request("GET", self.TICKER_MAP_URL)
            payload: dict[str, dict[str, Any]] = response.json()
            self._ticker_map = {
                entry["ticker"].upper(): (str(entry["cik_str"]).zfill(10), entry["title"])
                for entry in payload.values()
            }
            logger.info("edgar_ticker_map_loaded", tickers=len(self._ticker_map))
        key = ticker.upper()
        if key not in self._ticker_map:
            raise KeyError(f"ticker {ticker!r} not found in EDGAR company map")
        return self._ticker_map[key]

    async def get_filings(
        self,
        ticker: str,
        *,
        form_types: tuple[str, ...] = DEFAULT_FORM_TYPES,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int | None = None,
    ) -> list[FilingMetadata]:
        """List filings for a ticker filtered by form type and date range.

        Args:
            ticker: Exchange ticker symbol.
            form_types: Form types to include (default: the five core forms).
            start_date: Inclusive lower bound on filing date.
            end_date: Inclusive upper bound on filing date.
            limit: Maximum number of filings to return (newest first).

        Returns:
            Filing metadata sorted newest-first as EDGAR returns them.
        """
        cik, company_name = await self._resolve_ticker(ticker)
        url = f"{self.DATA_BASE_URL}/submissions/CIK{cik}.json"
        response = await self._request("GET", url)
        recent = response.json().get("filings", {}).get("recent", {})
        rows = zip(
            recent.get("accessionNumber", []),
            recent.get("form", []),
            recent.get("filingDate", []),
            recent.get("primaryDocument", []),
            strict=True,
        )
        results: list[FilingMetadata] = []
        for accession, form, filing_date_raw, primary_doc in rows:
            if form not in form_types:
                continue
            filing_date = date.fromisoformat(filing_date_raw)
            if start_date is not None and filing_date < start_date:
                continue
            if end_date is not None and filing_date > end_date:
                continue
            accession_nodash = accession.replace("-", "")
            results.append(
                FilingMetadata(
                    accession_number=accession,
                    cik=cik,
                    ticker=ticker.upper(),
                    company_name=company_name,
                    form_type=form,
                    filing_date=filing_date,
                    primary_document=primary_doc,
                    document_url=(
                        f"{self.ARCHIVES_BASE_URL}/Archives/edgar/data/"
                        f"{int(cik)}/{accession_nodash}/{primary_doc}"
                    ),
                )
            )
            if limit is not None and len(results) >= limit:
                break
        logger.info("edgar_filings_listed", ticker=ticker, count=len(results))
        return results

    async def fetch_filing(self, metadata: FilingMetadata) -> Filing:
        """Download a filing document and parse its sections.

        Args:
            metadata: Filing metadata from :meth:`get_filings`.

        Returns:
            The filing with plain text and best-effort parsed sections.
        """
        response = await self._request("GET", metadata.document_url)
        if metadata.primary_document.lower().endswith((".htm", ".html")):
            raw_text = self._html_to_text(response.text)
        else:
            raw_text = response.text
        sections = self._parse_sections(raw_text, metadata.form_type)
        logger.info(
            "edgar_filing_fetched",
            accession_number=metadata.accession_number,
            form_type=metadata.form_type,
            chars=len(raw_text),
            sections=sections.present(),
        )
        return Filing(metadata=metadata, raw_text=raw_text, parsed_sections=sections)

    async def search_full_text(
        self,
        query: str,
        *,
        form_types: tuple[str, ...] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FullTextSearchHit]:
        """Run an EDGAR full-text search query.

        Args:
            query: Search phrase (quoted phrases supported by EDGAR).
            form_types: Optional form-type filter.
            start_date: Inclusive lower bound on filing date.
            end_date: Inclusive upper bound on filing date.

        Returns:
            Parsed search hits (may be empty).
        """
        params: dict[str, str] = {"q": query}
        if form_types:
            params["forms"] = ",".join(form_types)
        if start_date:
            params["startdt"] = start_date.isoformat()
        if end_date:
            params["enddt"] = end_date.isoformat()
        response = await self._request("GET", self.FULL_TEXT_SEARCH_URL, params=params)
        hits_raw = response.json().get("hits", {}).get("hits", [])
        hits: list[FullTextSearchHit] = []
        for hit in hits_raw:
            source = hit.get("_source", {})
            accession = str(hit.get("_id", "")).split(":", 1)[0]
            ciks = source.get("ciks") or [""]
            file_date_raw = source.get("file_date")
            hits.append(
                FullTextSearchHit(
                    accession_number=accession,
                    cik=str(ciks[0]).zfill(10),
                    form_type=source.get("file_type"),
                    filing_date=date.fromisoformat(file_date_raw) if file_date_raw else None,
                    display_names=list(source.get("display_names", [])),
                )
            )
        logger.info("edgar_full_text_search", query=query, hits=len(hits))
        return hits

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convert filing HTML to newline-separated plain text."""
        soup = BeautifulSoup(html, "lxml")
        return soup.get_text(separator="\n")

    @staticmethod
    def _parse_sections(text: str, form_type: str) -> FilingSections:
        """Extract canonical sections from filing plain text.

        Splits on ``Item N`` headers and maps item numbers to section names
        per form type. Bodies shorter than :data:`_MIN_SECTION_LENGTH` are
        treated as table-of-contents entries and skipped. Footnotes are
        located by their standard heading regardless of form type.

        Args:
            text: Plain text of the filing.
            form_type: EDGAR form type, e.g. ``"10-K"``.

        Returns:
            Parsed sections; any section that cannot be located is ``None``.
        """
        section_map = _SECTION_MAPS.get(form_type, {})
        found: dict[str, str] = {}
        matches = list(_ITEM_HEADER_RE.finditer(text))
        for index, match in enumerate(matches):
            item = match.group(1).upper()
            name = section_map.get(item)
            if name is None or name in found:
                continue
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[match.end() : end].strip()
            if len(body) >= _MIN_SECTION_LENGTH:
                found[name] = body
        footnotes_match = _FOOTNOTES_RE.search(text)
        if footnotes_match is not None:
            body = text[footnotes_match.start() :].strip()
            if len(body) >= _MIN_SECTION_LENGTH:
                found["footnotes"] = body
        return FilingSections(**found)
