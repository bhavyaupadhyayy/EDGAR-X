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
from ingestion.sources.http_utils import AsyncRateLimiter, IngestionError, request_with_retry

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


class CompanyInfo(BaseModel):
    """Company identity and SIC classification from the submissions API."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    cik: str
    company_name: str
    sic: str | None = None
    sic_description: str | None = None


#: SIC division ranges -> coarse sector label.
_SIC_SECTORS: tuple[tuple[int, int, str], ...] = (
    (100, 999, "Agriculture"),
    (1000, 1499, "Mining & Energy"),
    (1500, 1799, "Construction"),
    (2000, 3999, "Manufacturing"),
    (4000, 4999, "Transportation & Utilities"),
    (5000, 5199, "Wholesale Trade"),
    (5200, 5999, "Retail Trade"),
    (6000, 6799, "Financials"),
    (7000, 8999, "Services"),
    (9100, 9999, "Public Administration"),
)


def sector_from_sic(sic: str | None) -> str:
    """Map a SIC code to its coarse SIC-division sector label.

    Args:
        sic: Four-digit SIC code as reported by EDGAR (may be ``None``).

    Returns:
        The sector label, or ``"Unknown"`` when the code is missing/invalid.
    """
    try:
        code = int(sic or "")
    except ValueError:
        return "Unknown"
    for low, high, label in _SIC_SECTORS:
        if low <= code <= high:
            return label
    return "Unknown"


class CompanyFundamentals(BaseModel):
    """Core fundamentals for one company's most recent annual (FY) period.

    Field names match the ``raw_fundamentals`` landing-table contract read by
    the dbt ``stg_fundamentals`` model. ``close_price`` is always ``None``
    here — price comes from the market-data source, not EDGAR.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    fiscal_year: int
    fiscal_quarter: int = 4
    period_end_date: date
    revenue: float
    cost_of_revenue: float | None = None
    net_income: float | None = None
    total_assets: float | None = None
    total_liabilities: float | None = None
    total_equity: float | None = None
    total_debt: float | None = None
    shares_outstanding: float | None = None
    close_price: float | None = None

    def to_raw_row(self) -> dict[str, Any]:
        """Render this record as a dict matching the RAW_FUNDAMENTALS columns."""
        return self.model_dump()


#: us-gaap concept tags tried in order for each fundamentals field. XBRL tag
#: usage varies by filer, so each field lists its common synonyms.
_FUNDAMENTALS_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "cost_of_revenue": ("CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfSales"),
    "net_income": ("NetIncomeLoss",),
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "total_equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "total_debt": ("LongTermDebt", "LongTermDebtNoncurrent"),
}


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

    async def get_company_info(self, ticker: str) -> CompanyInfo:
        """Fetch company identity and SIC classification.

        Args:
            ticker: Exchange ticker symbol.

        Returns:
            Company info from the submissions API.

        Raises:
            KeyError: If the ticker is unknown to EDGAR.
        """
        cik, fallback_name = await self._resolve_ticker(ticker)
        response = await self._request("GET", f"{self.DATA_BASE_URL}/submissions/CIK{cik}.json")
        payload = response.json()
        return CompanyInfo(
            ticker=ticker.upper(),
            cik=cik,
            company_name=payload.get("name") or fallback_name,
            sic=payload.get("sic") or None,
            sic_description=payload.get("sicDescription") or None,
        )

    async def get_company_fundamentals(self, ticker: str) -> CompanyFundamentals:
        """Fetch core fundamentals from the XBRL companyfacts API.

        Extracts revenue, cost of revenue, net income, total assets, total
        liabilities, stockholders' equity, long-term debt, and shares
        outstanding for the most recent annual (10-K / FY) period. Each
        concept is resolved independently to its latest annual fact, since
        instant (balance sheet) and duration (income statement) facts carry
        different period boundaries; the fiscal year and period end are
        anchored to the revenue fact.

        Args:
            ticker: Exchange ticker symbol.

        Returns:
            The most recent annual fundamentals.

        Raises:
            KeyError: If the ticker is unknown to EDGAR.
            IngestionError: If no annual revenue fact can be located.
        """
        cik, _company_name = await self._resolve_ticker(ticker)
        url = f"{self.DATA_BASE_URL}/api/xbrl/companyfacts/CIK{cik}.json"
        response = await self._request("GET", url)
        facts = response.json().get("facts", {})
        gaap = facts.get("us-gaap", {})

        values: dict[str, float | None] = {}
        anchor: dict[str, Any] | None = None
        for field, concepts in _FUNDAMENTALS_CONCEPTS.items():
            fact = self._latest_annual_fact(gaap, concepts, unit="USD")
            values[field] = fact["val"] if fact is not None else None
            if field == "revenue":
                anchor = fact
        if anchor is None or values["revenue"] is None:
            raise IngestionError(f"no annual revenue fact in companyfacts for {ticker!r}")

        shares_fact = self._latest_annual_fact(
            facts.get("dei", {}),
            ("EntityCommonStockSharesOutstanding",),
            unit="shares",
        ) or self._latest_annual_fact(
            gaap, ("CommonStockSharesOutstanding",), unit="shares"
        )

        fundamentals = CompanyFundamentals(
            ticker=ticker.upper(),
            fiscal_year=int(anchor["fy"]),
            period_end_date=date.fromisoformat(anchor["end"]),
            revenue=float(values["revenue"]),
            cost_of_revenue=values["cost_of_revenue"],
            net_income=values["net_income"],
            total_assets=values["total_assets"],
            total_liabilities=values["total_liabilities"],
            total_equity=values["total_equity"],
            total_debt=values["total_debt"],
            shares_outstanding=float(shares_fact["val"]) if shares_fact else None,
        )
        logger.info(
            "edgar_fundamentals_fetched",
            ticker=ticker,
            fiscal_year=fundamentals.fiscal_year,
            period_end=str(fundamentals.period_end_date),
            missing=[k for k, v in fundamentals.model_dump().items() if v is None],
        )
        return fundamentals

    @staticmethod
    def _latest_annual_fact(
        taxonomy: dict[str, Any],
        concepts: tuple[str, ...],
        *,
        unit: str,
    ) -> dict[str, Any] | None:
        """Return the latest annual fact across all candidate concept tags.

        A fact qualifies as annual when it was reported on a 10-K with fiscal
        period ``FY``. All concepts are evaluated and the fact with the
        greatest period end date wins (then filing date, so amended values
        beat originals; then concept priority order). Filers switch tags over
        time — e.g. NVIDIA moved from the contract-revenue tag back to
        ``Revenues`` — so a stale fact under a higher-priority tag must never
        shadow a current fact under a lower-priority one.

        Args:
            taxonomy: One taxonomy block of the companyfacts payload
                (e.g. ``facts["us-gaap"]`` or ``facts["dei"]``).
            concepts: Concept tags to consider, in priority order.
            unit: Unit key inside the concept (``"USD"`` or ``"shares"``).

        Returns:
            The winning fact dict, or ``None`` if no concept has an annual fact.
        """
        best: dict[str, Any] | None = None
        best_key: tuple[str, str, int] | None = None
        for priority, concept in enumerate(concepts):
            entries = taxonomy.get(concept, {}).get("units", {}).get(unit, [])
            annual = [
                entry
                for entry in entries
                if entry.get("form") == "10-K"
                and entry.get("fp") == "FY"
                and entry.get("val") is not None
                and entry.get("fy") is not None
            ]
            if not annual:
                continue
            candidate = max(annual, key=lambda e: (e["end"], e.get("filed", "")))
            key = (candidate["end"], candidate.get("filed", ""), -priority)
            if best_key is None or key > best_key:
                best, best_key = candidate, key
        return best
