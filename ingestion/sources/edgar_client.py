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
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        # REITs frequently report only real-estate / lease revenue concepts
        # (ASC 842 lease income is outside ASC 606 contract revenue). These
        # are components, so the max_value rule keeps them subordinate to a
        # total-revenue tag whenever one exists for the same period.
        "RealEstateRevenueNet",
        "OperatingLeaseLeaseIncome",
        "OperatingLeasesIncomeStatementLeaseRevenue",
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
        payload = response.json()
        filings_block = payload.get("filings", {})
        batches: list[dict[str, Any]] = [filings_block.get("recent", {})]

        # The "recent" window holds only the latest ~1000 filings; for
        # high-volume filers that can span under 3 years. Older filings live
        # in paginated archive files — fetch those whose date range overlaps
        # the requested window.
        if start_date is not None:
            for archive in filings_block.get("files", []):
                filing_to = archive.get("filingTo")
                if filing_to and date.fromisoformat(filing_to) < start_date:
                    continue
                if end_date is not None:
                    filing_from = archive.get("filingFrom")
                    if filing_from and date.fromisoformat(filing_from) > end_date:
                        continue
                archive_response = await self._request(
                    "GET", f"{self.DATA_BASE_URL}/submissions/{archive['name']}"
                )
                batches.append(archive_response.json())

        results: list[FilingMetadata] = []
        for batch in batches:
            rows = zip(
                batch.get("accessionNumber", []),
                batch.get("form", []),
                batch.get("filingDate", []),
                batch.get("primaryDocument", []),
                strict=True,
            )
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

        results.sort(key=lambda metadata: metadata.filing_date, reverse=True)
        if limit is not None:
            results = results[:limit]
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

    async def resolve_ticker(self, ticker: str) -> tuple[str, str]:
        """Resolve a ticker to its zero-padded CIK and EDGAR company title.

        Args:
            ticker: Exchange ticker symbol, case-insensitive.

        Returns:
            Tuple of (10-digit zero-padded CIK, company title).

        Raises:
            KeyError: If the ticker is unknown to EDGAR.
        """
        return await self._resolve_ticker(ticker)

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
        """Fetch core fundamentals for the most recent annual (FY) period.

        Thin wrapper over :meth:`get_fundamentals_history` so single-period
        and historical extraction share one set of tag-resolution semantics.

        Args:
            ticker: Exchange ticker symbol.

        Returns:
            The most recent annual fundamentals.

        Raises:
            KeyError: If the ticker is unknown to EDGAR.
            IngestionError: If no annual revenue fact can be located.
        """
        history = await self.get_fundamentals_history(ticker)
        if not history:
            raise IngestionError(f"no annual revenue fact in companyfacts for {ticker!r}")
        return history[-1]

    async def get_fundamentals_history(self, ticker: str) -> list[CompanyFundamentals]:
        """Fetch annual fundamentals for every available fiscal year.

        Periods are keyed by their END date, not the report's ``fy`` field:
        each 10-K restates prior years as comparatives under its own ``fy``,
        so grouping by ``fy`` would collapse distinct periods. For each period
        end the latest-filed fact wins (restatements beat originals). The
        fiscal-year label is the calendar year of the period end, matching
        filer convention (AAPL FY2025 ends 2025-09; NVDA FY2026 ends 2026-01).

        Only years with a revenue fact are returned; other fields are matched
        to the same period end and may be ``None``. Shares outstanding (a
        cover-page fact with its own date) is matched by calendar year.

        Args:
            ticker: Exchange ticker symbol.

        Returns:
            One :class:`CompanyFundamentals` per fiscal year, oldest first.
            Empty if the company has no annual revenue facts.

        Raises:
            KeyError: If the ticker is unknown to EDGAR.
        """
        cik, _company_name = await self._resolve_ticker(ticker)
        url = f"{self.DATA_BASE_URL}/api/xbrl/companyfacts/CIK{cik}.json"
        response = await self._request("GET", url)
        facts = response.json().get("facts", {})
        gaap = facts.get("us-gaap", {})

        series: dict[str, dict[str, dict[str, Any]]] = {
            field: self._collect_annual_series(
                gaap,
                concepts,
                unit="USD",
                # Revenue tags are components of total revenue (REITs tag
                # ASC 606 contract revenue separately from lease revenue),
                # so the largest candidate per period is the total.
                prefer="max_value" if field == "revenue" else "priority",
                # Net income and equity are legitimately negative; the other
                # fields are magnitudes and a negative fact is a filer error.
                non_negative=field not in ("net_income", "total_equity"),
            )
            for field, concepts in _FUNDAMENTALS_CONCEPTS.items()
        }
        shares_series = self._collect_annual_series(
            facts.get("dei", {}),
            ("EntityCommonStockSharesOutstanding",),
            unit="shares",
            non_negative=True,
        ) or self._collect_annual_series(
            gaap, ("CommonStockSharesOutstanding",), unit="shares", non_negative=True
        )
        shares_by_year = {
            date.fromisoformat(end).year: fact
            for end, fact in sorted(shares_series.items())
        }

        # One period per fiscal-year label; the latest end within a year wins
        # (guards against 52/53-week quirks and fiscal-calendar changes).
        period_by_year: dict[int, str] = {}
        for end in sorted(series["revenue"]):
            period_by_year[date.fromisoformat(end).year] = end

        history: list[CompanyFundamentals] = []
        for fiscal_year, end in sorted(period_by_year.items()):
            def value_at(field: str, period_end: str = end) -> float | None:
                fact = series[field].get(period_end)
                return float(fact["val"]) if fact is not None else None

            shares_fact = shares_by_year.get(fiscal_year)
            history.append(
                CompanyFundamentals(
                    ticker=ticker.upper(),
                    fiscal_year=fiscal_year,
                    period_end_date=date.fromisoformat(end),
                    revenue=float(series["revenue"][end]["val"]),
                    cost_of_revenue=value_at("cost_of_revenue"),
                    net_income=value_at("net_income"),
                    total_assets=value_at("total_assets"),
                    total_liabilities=value_at("total_liabilities"),
                    total_equity=value_at("total_equity"),
                    total_debt=value_at("total_debt"),
                    shares_outstanding=float(shares_fact["val"]) if shares_fact else None,
                )
            )
        logger.info(
            "edgar_fundamentals_history_fetched",
            ticker=ticker,
            years=len(history),
            span=(
                f"{history[0].fiscal_year}-{history[-1].fiscal_year}" if history else None
            ),
        )
        return history

    @staticmethod
    def _collect_annual_series(
        taxonomy: dict[str, Any],
        concepts: tuple[str, ...],
        *,
        unit: str,
        prefer: str = "priority",
        non_negative: bool = False,
    ) -> dict[str, dict[str, Any]]:
        """Collect annual facts across concept tags, keyed by period end date.

        Facts qualify when reported on a 10-K with fiscal period ``FY``.
        Duration facts shorter than ~10 months are excluded (10-Ks carry
        quarterly comparatives under ``FY`` too).

        Within one concept, the latest-filed fact per period end wins, so
        restatements beat originals. Across concepts for the same period end,
        the winner depends on ``prefer``:

        * ``"priority"`` — first concept in the list wins (balance-sheet and
          income items, where tags are synonyms).
        * ``"max_value"`` — the largest value wins. Used for revenue, where
          tags are COMPONENTS, not synonyms: a REIT's ASC 606 contract
          revenue legitimately excludes lease revenue and can be a thousandth
          of total ``Revenues`` for the same period. No tag ordering is
          universally correct, but a component can never exceed the total.

        Args:
            taxonomy: One taxonomy block of the companyfacts payload.
            concepts: Concept tags to consider, in priority order.
            unit: Unit key inside the concept (``"USD"`` or ``"shares"``).
            prefer: Cross-concept winner rule (``"priority"``/``"max_value"``).
            non_negative: Reject facts with negative values. Used for fields
                that are non-negative by definition (debt, assets, revenue):
                filers occasionally restate them with sign errors — DuPont's
                FY2019 10-K tagged LongTermDebt as -$15.6B — and a bogus
                restatement must not displace a valid original.

        Returns:
            Mapping of ISO period-end date to the winning fact dict.
        """
        best: dict[str, tuple[tuple[float, str] | tuple[int, str], dict[str, Any]]] = {}
        for priority, concept in enumerate(concepts):
            per_end: dict[str, dict[str, Any]] = {}
            for entry in taxonomy.get(concept, {}).get("units", {}).get(unit, []):
                if entry.get("form") != "10-K" or entry.get("fp") != "FY":
                    continue
                if entry.get("val") is None or not entry.get("end"):
                    continue
                if non_negative and float(entry["val"]) < 0:
                    continue
                start = entry.get("start")
                if start is not None:
                    duration = date.fromisoformat(entry["end"]) - date.fromisoformat(start)
                    if duration.days < 300:
                        continue
                end = entry["end"]
                if (
                    end not in per_end
                    or entry.get("filed", "") > per_end[end].get("filed", "")
                ):
                    per_end[end] = entry
            for end, entry in per_end.items():
                key: tuple[float, str] | tuple[int, str]
                if prefer == "max_value":
                    key = (float(entry["val"]), entry.get("filed", ""))
                else:
                    key = (-priority, entry.get("filed", ""))
                if end not in best or key > best[end][0]:
                    best[end] = (key, entry)
        return {end: fact for end, (_key, fact) in best.items()}

