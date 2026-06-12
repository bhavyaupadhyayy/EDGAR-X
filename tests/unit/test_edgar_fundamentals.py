"""Unit tests for the EDGAR XBRL companyfacts fundamentals method."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
import respx

from ingestion.sources.edgar_client import EdgarClient
from ingestion.sources.http_utils import IngestionError

TICKER_MAP = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"


def _usd_concept(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"units": {"USD": entries}}


def _annual(end: str, val: float, fy: int, filed: str = "2025-11-01") -> dict[str, Any]:
    return {"end": end, "val": val, "fy": fy, "fp": "FY", "form": "10-K", "filed": filed}


def _quarterly(end: str, val: float, fy: int, fp: str) -> dict[str, Any]:
    return {"end": end, "val": val, "fy": fy, "fp": fp, "form": "10-Q", "filed": end}


COMPANYFACTS = {
    "facts": {
        "us-gaap": {
            # Newer revenue tag present -> takes priority over "Revenues".
            "RevenueFromContractWithCustomerExcludingAssessedTax": _usd_concept(
                [
                    _annual("2024-09-28", 391_035_000_000, 2024, filed="2024-11-01"),
                    _annual("2025-09-27", 416_161_000_000, 2025, filed="2025-11-01"),
                    _quarterly("2025-12-27", 124_300_000_000, 2026, "Q1"),
                ]
            ),
            "Revenues": _usd_concept([_annual("2025-09-27", 1.0, 2025)]),
            "CostOfGoodsAndServicesSold": _usd_concept(
                [_annual("2025-09-27", 218_817_000_000, 2025)]
            ),
            "NetIncomeLoss": _usd_concept([_annual("2025-09-27", 102_089_000_000, 2025)]),
            "Assets": _usd_concept([_annual("2025-09-27", 344_085_000_000, 2025)]),
            "Liabilities": _usd_concept([_annual("2025-09-27", 277_327_000_000, 2025)]),
            "StockholdersEquity": _usd_concept([_annual("2025-09-27", 66_758_000_000, 2025)]),
            "LongTermDebt": _usd_concept([_annual("2025-09-27", 96_700_000_000, 2025)]),
        },
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {
                    "shares": [
                        _annual("2025-10-17", 15_022_073_000, 2025),
                        _quarterly("2026-01-16", 14_998_000_000, 2026, "Q1"),
                    ]
                }
            }
        },
    }
}


def _mock_endpoints(respx_mock: respx.MockRouter, facts: dict[str, Any]) -> None:
    respx_mock.get(EdgarClient.TICKER_MAP_URL).respond(200, json=TICKER_MAP)
    respx_mock.get(COMPANYFACTS_URL).respond(200, json=facts)


def _annual_period(
    start: str, end: str, val: float, fy: int, filed: str
) -> dict[str, Any]:
    return {
        "start": start, "end": end, "val": val, "fy": fy,
        "fp": "FY", "form": "10-K", "filed": filed,
    }


HISTORY_FACTS = {
    "facts": {
        "us-gaap": {
            "Revenues": _usd_concept(
                [
                    # FY2024 as originally reported in the FY2024 10-K.
                    _annual_period("2023-10-01", "2024-09-28", 380_000_000_000, 2024, "2024-11-01"),
                    # FY2024 restated as a comparative in the FY2025 10-K
                    # (note fy=2025): the later-filed value must win.
                    _annual_period("2023-10-01", "2024-09-28", 381_000_000_000, 2025, "2025-11-01"),
                    # FY2025 primary fact.
                    _annual_period("2024-09-29", "2025-09-27", 416_000_000_000, 2025, "2025-11-01"),
                    # A quarterly comparative carried under fp=FY: too short,
                    # must be filtered out, not treated as a fiscal year.
                    _annual_period("2025-06-29", "2025-09-27", 102_000_000_000, 2025, "2025-11-01"),
                ]
            ),
            "Assets": _usd_concept(
                [
                    _annual("2024-09-28", 364_980_000_000, 2024, filed="2024-11-01"),
                    _annual("2025-09-27", 344_085_000_000, 2025, filed="2025-11-01"),
                ]
            ),
        },
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {
                    "shares": [
                        _annual("2024-10-18", 15_115_823_000, 2024, filed="2024-11-01"),
                        _annual("2025-10-17", 15_022_073_000, 2025, filed="2025-11-01"),
                    ]
                }
            }
        },
    }
}


class TestGetFundamentalsHistory:
    """Multi-year extraction keyed by period end date."""

    async def test_one_row_per_fiscal_year(self, respx_mock: respx.MockRouter) -> None:
        _mock_endpoints(respx_mock, HISTORY_FACTS)
        async with EdgarClient() as client:
            history = await client.get_fundamentals_history("AAPL")
        assert [h.fiscal_year for h in history] == [2024, 2025]
        assert history[0].period_end_date == date(2024, 9, 28)
        assert history[1].period_end_date == date(2025, 9, 27)

    async def test_restated_comparative_wins(self, respx_mock: respx.MockRouter) -> None:
        _mock_endpoints(respx_mock, HISTORY_FACTS)
        async with EdgarClient() as client:
            history = await client.get_fundamentals_history("AAPL")
        # FY2024 revenue must be the restated value from the later filing.
        assert history[0].revenue == 381_000_000_000

    async def test_short_duration_facts_filtered(self, respx_mock: respx.MockRouter) -> None:
        _mock_endpoints(respx_mock, HISTORY_FACTS)
        async with EdgarClient() as client:
            history = await client.get_fundamentals_history("AAPL")
        assert all(h.revenue > 300_000_000_000 for h in history)

    async def test_balance_sheet_and_shares_matched_per_year(
        self, respx_mock: respx.MockRouter
    ) -> None:
        _mock_endpoints(respx_mock, HISTORY_FACTS)
        async with EdgarClient() as client:
            history = await client.get_fundamentals_history("AAPL")
        assert history[0].total_assets == 364_980_000_000
        assert history[1].total_assets == 344_085_000_000
        assert history[0].shares_outstanding == 15_115_823_000
        assert history[1].shares_outstanding == 15_022_073_000

    async def test_no_revenue_returns_empty(self, respx_mock: respx.MockRouter) -> None:
        _mock_endpoints(respx_mock, {"facts": {"us-gaap": {}, "dei": {}}})
        async with EdgarClient() as client:
            assert await client.get_fundamentals_history("AAPL") == []


class TestGetCompanyFundamentals:
    """Extraction of the most recent annual period from companyfacts."""

    async def test_extracts_latest_annual_period(self, respx_mock: respx.MockRouter) -> None:
        _mock_endpoints(respx_mock, COMPANYFACTS)
        async with EdgarClient() as client:
            fundamentals = await client.get_company_fundamentals("aapl")
        assert fundamentals.ticker == "AAPL"
        assert fundamentals.fiscal_year == 2025
        assert fundamentals.fiscal_quarter == 4
        assert fundamentals.period_end_date == date(2025, 9, 27)
        # FY2025 value chosen over FY2024 and the Q1 quarterly fact.
        assert fundamentals.revenue == 416_161_000_000
        assert fundamentals.cost_of_revenue == 218_817_000_000
        assert fundamentals.net_income == 102_089_000_000
        assert fundamentals.total_assets == 344_085_000_000
        assert fundamentals.total_liabilities == 277_327_000_000
        assert fundamentals.total_equity == 66_758_000_000
        assert fundamentals.total_debt == 96_700_000_000
        assert fundamentals.shares_outstanding == 15_022_073_000
        assert fundamentals.close_price is None

    async def test_quarterly_facts_are_ignored(self, respx_mock: respx.MockRouter) -> None:
        _mock_endpoints(respx_mock, COMPANYFACTS)
        async with EdgarClient() as client:
            fundamentals = await client.get_company_fundamentals("AAPL")
        # Q1 2026 facts have later end dates but must not be selected.
        assert fundamentals.revenue != 124_300_000_000
        assert fundamentals.shares_outstanding != 14_998_000_000

    async def test_falls_back_to_revenues_tag(self, respx_mock: respx.MockRouter) -> None:
        facts = {
            "facts": {
                "us-gaap": {
                    "Revenues": _usd_concept([_annual("2025-12-31", 42_768_000_000, 2025)]),
                    "NetIncomeLoss": _usd_concept(
                        [_annual("2025-12-31", 14_005_000_000, 2025)]
                    ),
                },
                "dei": {},
            }
        }
        _mock_endpoints(respx_mock, facts)
        async with EdgarClient() as client:
            fundamentals = await client.get_company_fundamentals("AAPL")
        assert fundamentals.revenue == 42_768_000_000
        assert fundamentals.total_assets is None
        assert fundamentals.shares_outstanding is None

    async def test_stale_priority_tag_loses_to_current_fallback_tag(
        self, respx_mock: respx.MockRouter
    ) -> None:
        """Regression: NVIDIA-style tag switch.

        The filer stopped using the contract-revenue tag after FY2022 and now
        reports under ``Revenues``. The current ``Revenues`` fact must win
        despite its lower priority, or income-statement and balance-sheet
        fields end up anchored to different fiscal years.
        """
        facts = {
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": _usd_concept(
                        [_annual("2022-01-30", 26_914_000_000, 2022, filed="2022-03-01")]
                    ),
                    "Revenues": _usd_concept(
                        [_annual("2026-01-25", 198_000_000_000, 2026, filed="2026-03-01")]
                    ),
                    "NetIncomeLoss": _usd_concept(
                        [_annual("2026-01-25", 120_067_000_000, 2026, filed="2026-03-01")]
                    ),
                },
                "dei": {},
            }
        }
        _mock_endpoints(respx_mock, facts)
        async with EdgarClient() as client:
            fundamentals = await client.get_company_fundamentals("AAPL")
        assert fundamentals.revenue == 198_000_000_000
        assert fundamentals.fiscal_year == 2026
        assert fundamentals.period_end_date == date(2026, 1, 25)

    async def test_missing_revenue_raises(self, respx_mock: respx.MockRouter) -> None:
        facts = {
            "facts": {
                "us-gaap": {
                    "NetIncomeLoss": _usd_concept([_annual("2025-12-31", 1.0, 2025)])
                }
            }
        }
        _mock_endpoints(respx_mock, facts)
        async with EdgarClient() as client:
            with pytest.raises(IngestionError, match="no annual revenue fact"):
                await client.get_company_fundamentals("AAPL")

    async def test_to_raw_row_matches_landing_contract(
        self, respx_mock: respx.MockRouter
    ) -> None:
        _mock_endpoints(respx_mock, COMPANYFACTS)
        async with EdgarClient() as client:
            row = (await client.get_company_fundamentals("AAPL")).to_raw_row()
        assert set(row) == {
            "ticker",
            "fiscal_year",
            "fiscal_quarter",
            "period_end_date",
            "revenue",
            "cost_of_revenue",
            "net_income",
            "total_assets",
            "total_liabilities",
            "total_equity",
            "total_debt",
            "shares_outstanding",
            "close_price",
        }
