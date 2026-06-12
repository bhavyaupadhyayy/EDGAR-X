"""Checkpointed S&P 500 backfill: companies, 10 years of 10-Ks, full fundamentals history.

For every member of ``scripts/sp500_universe.json`` this pulls, through the
rate-limited Layer 1 EDGAR client:

* company info (industry from SIC; sector comes from the GICS label in the
  universe file),
* all available annual fundamentals (one row per fiscal year),
* the last 10 years of 10-K filings with parsed MD&A / risk sections.

Rows stream to Snowflake per company with delete-before-insert, so a resumed
run can never duplicate a company. Progress is checkpointed to
``scripts/.backfill_checkpoint.json`` after each company; a crash mid-run
resumes where it left off.

Usage::

    set -a; source .env; set +a
    python scripts/backfill_universe.py --sample 20   # first N members
    python scripts/backfill_universe.py               # full universe (resumes)
    python scripts/backfill_universe.py --fresh       # clear checkpoint first
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from core.logging import configure_logging, get_logger
from ingestion.sinks.snowflake_writer import SnowflakeWriter
from ingestion.sources.edgar_client import EdgarClient
from ingestion.sources.http_utils import IngestionError, RetryExhaustedError

configure_logging()
logger = get_logger("backfill_universe")

UNIVERSE_PATH = Path(__file__).parent / "sp500_universe.json"
CHECKPOINT_PATH = Path(__file__).parent / ".backfill_checkpoint.json"

FILING_LOOKBACK_DAYS = 3650
MIN_FUNDAMENTAL_YEARS = 2  # fewer than this cannot ever produce a label


class Checkpoint:
    """JSON-file checkpoint: per-ticker status and row counts."""

    def __init__(self, path: Path = CHECKPOINT_PATH) -> None:
        """Load the checkpoint file if it exists.

        Args:
            path: Checkpoint file location.
        """
        self._path = path
        self.done: dict[str, dict[str, int]] = {}
        self.dropped: dict[str, str] = {}
        if path.exists():
            state = json.loads(path.read_text())
            self.done = state.get("done", {})
            self.dropped = state.get("dropped", {})

    def save(self) -> None:
        """Persist the checkpoint to disk."""
        self._path.write_text(
            json.dumps({"done": self.done, "dropped": self.dropped}, indent=1)
        )

    def clear(self) -> None:
        """Reset all progress."""
        self.done = {}
        self.dropped = {}
        if self._path.exists():
            self._path.unlink()


async def backfill_company(
    client: EdgarClient,
    writer: SnowflakeWriter,
    member: dict[str, Any],
) -> dict[str, int] | str:
    """Fetch and load one company; return row counts, or a drop reason.

    Args:
        client: Shared EDGAR client (rate limited).
        writer: Shared Snowflake writer.
        member: One entry from the universe file.

    Returns:
        Per-table row counts on success, or a drop-reason string.
    """
    ticker = member["edgar_ticker"]

    try:
        fundamentals = await client.get_fundamentals_history(ticker)
    except IngestionError as exc:
        return f"companyfacts error: {exc}"
    if len(fundamentals) < MIN_FUNDAMENTAL_YEARS:
        return f"only {len(fundamentals)} annual fundamentals year(s)"

    info = await client.get_company_info(ticker)
    company_row = {
        "ticker": info.ticker,
        "cik": info.cik,
        "company_name": info.company_name,
        "sector": member.get("gics_sector") or "Unknown",
        "industry": info.sic_description or "Unknown",
    }

    filing_metadata = await client.get_filings(
        ticker,
        form_types=("10-K",),
        start_date=date.today() - timedelta(days=FILING_LOOKBACK_DAYS),
    )
    if not filing_metadata:
        return "no 10-K filings in the lookback window"

    filing_rows: list[dict[str, Any]] = []
    for metadata in filing_metadata:
        filing = await client.fetch_filing(metadata)
        sections = filing.parsed_sections
        filing_rows.append(
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

    for table in ("RAW_COMPANIES", "RAW_FUNDAMENTALS", "RAW_FILINGS"):
        writer.delete_rows(table, column="TICKER", value=info.ticker)
    counts = {
        "RAW_COMPANIES": writer.write_rows("RAW_COMPANIES", [company_row]),
        "RAW_FUNDAMENTALS": writer.write_rows(
            "RAW_FUNDAMENTALS", [row.to_raw_row() for row in fundamentals]
        ),
        "RAW_FILINGS": writer.write_rows("RAW_FILINGS", filing_rows),
    }
    counts["sections_parsed"] = sum(
        1 for row in filing_rows if row["mdna_text"] or row["risk_factors_text"]
    )
    return counts


async def run(members: list[dict[str, Any]], checkpoint: Checkpoint) -> None:
    """Backfill all members not yet checkpointed.

    Args:
        members: Universe entries to process.
        checkpoint: Progress state, updated after every company.
    """
    pending = [
        m
        for m in members
        if m["edgar_ticker"] not in checkpoint.done
        and m["edgar_ticker"] not in checkpoint.dropped
    ]
    logger.info(
        "backfill_starting",
        total=len(members),
        already_done=len(members) - len(pending),
        pending=len(pending),
    )
    with SnowflakeWriter() as writer:
        writer.create_raw_tables()
        async with EdgarClient() as client:
            for index, member in enumerate(pending, start=1):
                ticker = member["edgar_ticker"]
                try:
                    result = await backfill_company(client, writer, member)
                except (RetryExhaustedError, KeyError) as exc:
                    result = f"fetch failed: {exc}"
                if isinstance(result, str):
                    checkpoint.dropped[ticker] = result
                    logger.warning("company_dropped", ticker=ticker, reason=result)
                else:
                    checkpoint.done[ticker] = result
                    logger.info(
                        "company_loaded",
                        ticker=ticker,
                        progress=f"{index}/{len(pending)}",
                        **{k: v for k, v in result.items()},
                    )
                checkpoint.save()


def main() -> int:
    """Parse arguments, run the backfill, and print the summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=None, help="only the first N members")
    parser.add_argument("--fresh", action="store_true", help="clear the checkpoint first")
    args = parser.parse_args()

    members: list[dict[str, Any]] = json.loads(UNIVERSE_PATH.read_text())["members"]
    if args.sample:
        members = members[: args.sample]

    checkpoint = Checkpoint()
    if args.fresh:
        checkpoint.clear()

    asyncio.run(run(members, checkpoint))

    totals: dict[str, int] = {}
    for counts in checkpoint.done.values():
        for table, count in counts.items():
            totals[table] = totals.get(table, 0) + count
    print(f"\nBackfill complete: {len(checkpoint.done)} companies loaded, "
          f"{len(checkpoint.dropped)} dropped")
    for table in ("RAW_COMPANIES", "RAW_FUNDAMENTALS", "RAW_FILINGS"):
        print(f"  {table:<20} {totals.get(table, 0):>7} rows")
    filings = totals.get("RAW_FILINGS", 0)
    parsed = totals.get("sections_parsed", 0)
    if filings:
        print(f"  section parse rate   {parsed}/{filings} ({100 * parsed / filings:.0f}%)")
    if checkpoint.dropped:
        print("\nDropped companies:")
        for ticker, reason in sorted(checkpoint.dropped.items()):
            print(f"  {ticker:<8} {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
