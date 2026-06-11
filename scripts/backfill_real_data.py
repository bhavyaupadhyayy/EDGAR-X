"""Backfill real EDGAR and FRED data into the Snowflake RAW landing tables.

For the configured ticker universe this pulls, via the Layer 1 clients (which
enforce SEC's 10 req/sec cap and retry with backoff):

* company identity + SIC sector classification (EDGAR submissions API),
* the most recent 10-K filings with parsed MD&A / risk-factor sections,
* the latest annual fundamentals (EDGAR XBRL companyfacts API),
* the six tracked FRED macro series (last two years).

Everything is written to ``EDGAR_X.RAW`` via :class:`SnowflakeWriter`. The
four populated tables are truncated first so the backfill is idempotent; the
options / sentiment / transcript tables are created empty by design.

Usage::

    set -a; source .env; set +a
    python scripts/backfill_real_data.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from typing import Any

from core.logging import configure_logging, get_logger
from ingestion.sinks.snowflake_writer import SnowflakeWriter
from ingestion.sources.edgar_client import EdgarClient, sector_from_sic
from ingestion.sources.fred_client import FredClient
from ingestion.sources.http_utils import IngestionError

configure_logging()
logger = get_logger("backfill")

UNIVERSE: tuple[str, ...] = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL")

#: How many of the most recent 10-K filings to ingest per company.
FILINGS_PER_COMPANY = 2

#: How far back to pull macro observations.
MACRO_LOOKBACK_DAYS = 730


RowList = list[dict[str, Any]]


async def collect_edgar() -> tuple[RowList, RowList, RowList]:
    """Pull companies, 10-K filings, and fundamentals for the universe.

    Returns:
        Row dicts for (RAW_COMPANIES, RAW_FILINGS, RAW_FUNDAMENTALS).
    """
    companies: list[dict[str, Any]] = []
    filings: list[dict[str, Any]] = []
    fundamentals: list[dict[str, Any]] = []

    async with EdgarClient() as client:
        for ticker in UNIVERSE:
            info = await client.get_company_info(ticker)
            companies.append(
                {
                    "ticker": info.ticker,
                    "cik": info.cik,
                    "company_name": info.company_name,
                    "sector": sector_from_sic(info.sic),
                    "industry": info.sic_description or "Unknown",
                }
            )

            metadata_list = await client.get_filings(
                ticker, form_types=("10-K",), limit=FILINGS_PER_COMPANY
            )
            for metadata in metadata_list:
                filing = await client.fetch_filing(metadata)
                sections = filing.parsed_sections
                filings.append(
                    {
                        "accession_number": metadata.accession_number,
                        "cik": metadata.cik,
                        "ticker": metadata.ticker,
                        "company_name": metadata.company_name,
                        "form_type": metadata.form_type,
                        "filing_date": metadata.filing_date,
                        "document_url": metadata.document_url,
                        "mdna_text": sections.mdna,
                        "risk_factors_text": sections.risk_factors,
                        "ingested_at": datetime.now(UTC),
                    }
                )
                logger.info(
                    "filing_collected",
                    ticker=ticker,
                    accession=metadata.accession_number,
                    sections=sections.present(),
                )

            try:
                fundamentals.append(
                    (await client.get_company_fundamentals(ticker)).to_raw_row()
                )
            except IngestionError as exc:
                logger.error("fundamentals_unavailable", ticker=ticker, error=str(exc))

    return companies, filings, fundamentals


async def collect_macro() -> list[dict[str, Any]]:
    """Pull all tracked FRED series for the lookback window.

    Returns:
        Row dicts for RAW_MACRO_OBSERVATIONS.
    """
    rows: list[dict[str, Any]] = []
    async with FredClient() as client:
        all_series = await client.get_all_tracked_series(
            start_date=date.today() - timedelta(days=MACRO_LOOKBACK_DAYS)
        )
    for series in all_series.values():
        for observation in series.observations:
            rows.append(
                {
                    "series_id": observation.series_id,
                    "observation_date": observation.timestamp,
                    "value": observation.value,
                    "ingested_at": datetime.now(UTC),
                }
            )
    return rows


def main() -> int:
    """Run the backfill and print a per-table row summary."""
    companies, filings, fundamentals = asyncio.run(collect_edgar())
    macro = asyncio.run(collect_macro())

    loads: dict[str, list[dict[str, Any]]] = {
        "RAW_COMPANIES": companies,
        "RAW_FILINGS": filings,
        "RAW_FUNDAMENTALS": fundamentals,
        "RAW_MACRO_OBSERVATIONS": macro,
    }

    with SnowflakeWriter() as writer:
        writer.create_raw_tables()
        written: dict[str, int] = {}
        for table, rows in loads.items():
            writer.truncate_table(table)
            written[table] = writer.write_rows(table, rows)

    print("\nBackfill summary (rows written):")
    for table, count in written.items():
        print(f"  {table:<28} {count:>6}")
    print(
        "  RAW_OPTIONS_ACTIVITY / RAW_SENTIMENT_MENTIONS / RAW_TRANSCRIPT_SEGMENTS"
        "  created empty (deliberate)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
