"""Unit tests for the SEC EDGAR client (all HTTP mocked via respx)."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from ingestion.sources.edgar_client import EdgarClient, FilingMetadata

TICKER_MAP = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
}

SUBMISSIONS = {
    "name": "Apple Inc.",
    "sic": "3571",
    "sicDescription": "Electronic Computers",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000320193-26-000010",
                "0000320193-26-000005",
                "0000320193-25-000099",
            ],
            "form": ["10-Q", "8-K", "10-K"],
            "filingDate": ["2026-05-01", "2026-03-15", "2025-11-01"],
            "primaryDocument": [
                "aapl-10q.htm",
                "aapl-8k.htm",
                "aapl-10k.htm",
            ],
        }
    }
}

_PAD = "x" * 250

FILING_TEXT = f"""
TABLE OF CONTENTS
Item 1. Business
Item 1A. Risk Factors
Item 7. Management's Discussion and Analysis
Item 8. Financial Statements

Item 1. Business
We design, manufacture and market smartphones and related services. {_PAD}

Item 1A. Risk Factors
The Company's operations are subject to global macroeconomic conditions. {_PAD}

Item 7. Management's Discussion and Analysis of Financial Condition
Net sales increased due to strong product demand across all segments. {_PAD}

Item 8. Financial Statements and Supplementary Data
Consolidated balance sheets and statements of operations follow. {_PAD}

Notes to Consolidated Financial Statements
Note 1 — Summary of Significant Accounting Policies. {_PAD}
"""


def _mock_ticker_map(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(EdgarClient.TICKER_MAP_URL).respond(200, json=TICKER_MAP)


def _mock_submissions(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://data.sec.gov/submissions/CIK0000320193.json").respond(
        200, json=SUBMISSIONS
    )


class TestGetFilings:
    """Listing and filtering filings from the submissions API."""

    async def test_lists_filings_with_metadata(self, respx_mock: respx.MockRouter) -> None:
        _mock_ticker_map(respx_mock)
        _mock_submissions(respx_mock)
        async with EdgarClient() as client:
            filings = await client.get_filings("aapl")
        assert len(filings) == 3
        first = filings[0]
        assert first.cik == "0000320193"
        assert first.ticker == "AAPL"
        assert first.company_name == "Apple Inc."
        assert first.form_type == "10-Q"
        assert first.filing_date == date(2026, 5, 1)
        assert (
            first.document_url
            == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000010/aapl-10q.htm"
        )

    async def test_filters_by_form_type(self, respx_mock: respx.MockRouter) -> None:
        _mock_ticker_map(respx_mock)
        _mock_submissions(respx_mock)
        async with EdgarClient() as client:
            filings = await client.get_filings("AAPL", form_types=("10-K",))
        assert [f.form_type for f in filings] == ["10-K"]

    async def test_filters_by_date_range(self, respx_mock: respx.MockRouter) -> None:
        _mock_ticker_map(respx_mock)
        _mock_submissions(respx_mock)
        async with EdgarClient() as client:
            filings = await client.get_filings(
                "AAPL", start_date=date(2026, 1, 1), end_date=date(2026, 4, 1)
            )
        assert [f.form_type for f in filings] == ["8-K"]

    async def test_respects_limit(self, respx_mock: respx.MockRouter) -> None:
        _mock_ticker_map(respx_mock)
        _mock_submissions(respx_mock)
        async with EdgarClient() as client:
            filings = await client.get_filings("AAPL", limit=1)
        assert len(filings) == 1

    async def test_unknown_ticker_raises(self, respx_mock: respx.MockRouter) -> None:
        _mock_ticker_map(respx_mock)
        async with EdgarClient() as client:
            with pytest.raises(KeyError):
                await client.get_filings("ZZZZ")

    async def test_ticker_map_cached_across_calls(self, respx_mock: respx.MockRouter) -> None:
        map_route = respx_mock.get(EdgarClient.TICKER_MAP_URL).respond(200, json=TICKER_MAP)
        _mock_submissions(respx_mock)
        async with EdgarClient() as client:
            await client.get_filings("AAPL")
            await client.get_filings("AAPL")
        assert map_route.call_count == 1


class TestFetchFiling:
    """Downloading and section-parsing a filing document."""

    @pytest.fixture()
    def metadata(self) -> FilingMetadata:
        return FilingMetadata(
            accession_number="0000320193-25-000099",
            cik="0000320193",
            ticker="AAPL",
            company_name="Apple Inc.",
            form_type="10-K",
            filing_date=date(2025, 11, 1),
            primary_document="aapl-10k.htm",
            document_url=(
                "https://www.sec.gov/Archives/edgar/data/320193/000032019325000099/aapl-10k.htm"
            ),
        )

    async def test_parses_all_10k_sections(
        self, respx_mock: respx.MockRouter, metadata: FilingMetadata
    ) -> None:
        html = "<html><body>" + FILING_TEXT.replace("\n", "<br/>\n") + "</body></html>"
        respx_mock.get(metadata.document_url).respond(200, text=html)
        async with EdgarClient() as client:
            filing = await client.fetch_filing(metadata)
        sections = filing.parsed_sections
        assert "smartphones" in (sections.business or "")
        assert "macroeconomic" in (sections.risk_factors or "")
        assert "Net sales increased" in (sections.mdna or "")
        assert "Consolidated balance sheets" in (sections.financial_statements or "")
        assert "Significant Accounting Policies" in (sections.footnotes or "")
        assert sorted(sections.present()) == [
            "business",
            "financial_statements",
            "footnotes",
            "mdna",
            "risk_factors",
        ]

    async def test_toc_entries_are_skipped(
        self, respx_mock: respx.MockRouter, metadata: FilingMetadata
    ) -> None:
        respx_mock.get(metadata.document_url).respond(200, text=FILING_TEXT)
        async with EdgarClient() as client:
            filing = await client.fetch_filing(metadata)
        # The real section body, not the short TOC line, must be captured.
        assert "We design" in (filing.parsed_sections.business or "")

    async def test_retries_on_503(
        self, respx_mock: respx.MockRouter, metadata: FilingMetadata
    ) -> None:
        route = respx_mock.get(metadata.document_url)
        route.side_effect = [httpx.Response(503), httpx.Response(200, text=FILING_TEXT)]
        async with EdgarClient(backoff_base=0.01) as client:
            filing = await client.fetch_filing(metadata)
        assert route.call_count == 2
        assert filing.raw_text

    async def test_to_kafka_payload_matches_schema_fields(
        self, respx_mock: respx.MockRouter, metadata: FilingMetadata
    ) -> None:
        respx_mock.get(metadata.document_url).respond(200, text=FILING_TEXT)
        async with EdgarClient() as client:
            filing = await client.fetch_filing(metadata)
        payload = filing.to_kafka_payload()
        assert payload["accession_number"] == metadata.accession_number
        assert payload["filing_date"] == metadata.filing_date
        assert isinstance(payload["sections"], dict)
        assert all(isinstance(v, str) for v in payload["sections"].values())


class TestArchivedSubmissionPages:
    """High-volume filers overflow the 'recent' window into archive pages."""

    SUBMISSIONS_WITH_ARCHIVE = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-000010"],
                "form": ["10-K"],
                "filingDate": ["2026-05-01"],
                "primaryDocument": ["aapl-10k-2026.htm"],
            },
            "files": [
                {
                    "name": "CIK0000320193-submissions-001.json",
                    "filingFrom": "2015-01-01",
                    "filingTo": "2023-03-29",
                    "filingCount": 1619,
                }
            ],
        }
    }

    ARCHIVE_PAGE = {
        "accessionNumber": ["0000320193-20-000096", "0000320193-19-000119"],
        "form": ["10-K", "10-K"],
        "filingDate": ["2020-10-30", "2019-10-31"],
        "primaryDocument": ["aapl-10k-2020.htm", "aapl-10k-2019.htm"],
    }

    async def test_archive_pages_fetched_for_old_start_date(
        self, respx_mock: respx.MockRouter
    ) -> None:
        _mock_ticker_map(respx_mock)
        respx_mock.get("https://data.sec.gov/submissions/CIK0000320193.json").respond(
            200, json=self.SUBMISSIONS_WITH_ARCHIVE
        )
        archive_route = respx_mock.get(
            "https://data.sec.gov/submissions/CIK0000320193-submissions-001.json"
        ).respond(200, json=self.ARCHIVE_PAGE)
        async with EdgarClient() as client:
            filings = await client.get_filings(
                "AAPL", form_types=("10-K",), start_date=date(2019, 1, 1)
            )
        assert archive_route.call_count == 1
        assert [f.filing_date.year for f in filings] == [2026, 2020, 2019]

    async def test_archive_skipped_when_window_is_recent(
        self, respx_mock: respx.MockRouter
    ) -> None:
        _mock_ticker_map(respx_mock)
        respx_mock.get("https://data.sec.gov/submissions/CIK0000320193.json").respond(
            200, json=self.SUBMISSIONS_WITH_ARCHIVE
        )
        archive_route = respx_mock.get(
            "https://data.sec.gov/submissions/CIK0000320193-submissions-001.json"
        ).respond(200, json=self.ARCHIVE_PAGE)
        async with EdgarClient() as client:
            filings = await client.get_filings(
                "AAPL", form_types=("10-K",), start_date=date(2025, 1, 1)
            )
        assert archive_route.call_count == 0
        assert len(filings) == 1


class TestGetCompanyInfo:
    """Company identity and SIC classification."""

    async def test_returns_sic_classification(self, respx_mock: respx.MockRouter) -> None:
        _mock_ticker_map(respx_mock)
        _mock_submissions(respx_mock)
        async with EdgarClient() as client:
            info = await client.get_company_info("aapl")
        assert info.ticker == "AAPL"
        assert info.cik == "0000320193"
        assert info.company_name == "Apple Inc."
        assert info.sic == "3571"
        assert info.sic_description == "Electronic Computers"

    def test_sector_from_sic_divisions(self) -> None:
        from ingestion.sources.edgar_client import sector_from_sic

        assert sector_from_sic("3571") == "Manufacturing"
        assert sector_from_sic("5961") == "Retail Trade"
        assert sector_from_sic("6022") == "Financials"
        assert sector_from_sic("7372") == "Services"
        assert sector_from_sic(None) == "Unknown"
        assert sector_from_sic("not-a-code") == "Unknown"


class TestFullTextSearch:
    """The EDGAR full-text search endpoint."""

    async def test_parses_hits(self, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(EdgarClient.FULL_TEXT_SEARCH_URL).respond(
            200,
            json={
                "hits": {
                    "hits": [
                        {
                            "_id": "0000320193-26-000010:aapl-10q.htm",
                            "_source": {
                                "ciks": ["320193"],
                                "file_type": "10-Q",
                                "file_date": "2026-05-01",
                                "display_names": ["Apple Inc.  (AAPL)"],
                            },
                        }
                    ]
                }
            },
        )
        async with EdgarClient() as client:
            hits = await client.search_full_text("supply chain", form_types=("10-Q",))
        assert len(hits) == 1
        assert hits[0].accession_number == "0000320193-26-000010"
        assert hits[0].cik == "0000320193"
        assert hits[0].filing_date == date(2026, 5, 1)

    async def test_empty_results(self, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(EdgarClient.FULL_TEXT_SEARCH_URL).respond(200, json={"hits": {"hits": []}})
        async with EdgarClient() as client:
            assert await client.search_full_text("nothing") == []
