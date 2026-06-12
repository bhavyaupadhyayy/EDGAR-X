"""Build the S&P 500 training universe and resolve every ticker to a CIK.

Fetches the current constituent table from Wikipedia, normalises share-class
tickers to EDGAR's convention (``BRK.B`` -> ``BRK-B``), resolves each ticker
through the EDGAR company-ticker map, and writes the result to
``scripts/sp500_universe.json``. Tickers that fail resolution are logged and
recorded in the output file rather than crashing the run.

Usage::

    set -a; source .env; set +a
    python scripts/build_universe.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

from core.config import get_settings
from core.logging import configure_logging, get_logger
from ingestion.sources.edgar_client import EdgarClient

configure_logging()
logger = get_logger("build_universe")

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
OUTPUT_PATH = Path(__file__).parent / "sp500_universe.json"


class UniverseMember(BaseModel):
    """One resolved S&P 500 constituent."""

    ticker: str
    edgar_ticker: str
    company_name: str
    cik: str
    gics_sector: str | None = None


def parse_constituents(html: str) -> list[dict[str, Any]]:
    """Parse the constituents table from the Wikipedia page.

    Args:
        html: Raw page HTML.

    Returns:
        Dicts with ``ticker``, ``company_name``, and ``gics_sector``.

    Raises:
        ValueError: If the constituents table cannot be located.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="constituents") or soup.find("table", class_="wikitable")
    if table is None:
        raise ValueError("could not locate the S&P 500 constituents table")
    rows: list[dict[str, Any]] = []
    for tr in table.find_all("tr")[1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 3 or not cells[0]:
            continue
        rows.append(
            {"ticker": cells[0], "company_name": cells[1], "gics_sector": cells[2] or None}
        )
    return rows


async def build_universe() -> tuple[list[UniverseMember], list[dict[str, str]]]:
    """Fetch constituents and resolve each to a CIK.

    Returns:
        Tuple of (resolved members, unresolved entries with reasons).
    """
    headers = {"User-Agent": get_settings().edgar_user_agent}
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
        response = await http.get(WIKIPEDIA_URL, headers=headers)
        response.raise_for_status()
    constituents = parse_constituents(response.text)
    logger.info("constituents_parsed", count=len(constituents))

    resolved: list[UniverseMember] = []
    unresolved: list[dict[str, str]] = []
    async with EdgarClient() as client:
        for row in constituents:
            ticker = row["ticker"]
            # EDGAR's ticker map uses dashes for share classes (BRK-B, BF-B).
            edgar_ticker = ticker.replace(".", "-").upper()
            try:
                cik, _title = await client.resolve_ticker(edgar_ticker)
            except KeyError:
                logger.warning("ticker_unresolved", ticker=ticker)
                unresolved.append({"ticker": ticker, "reason": "not in EDGAR ticker map"})
                continue
            resolved.append(
                UniverseMember(
                    ticker=ticker,
                    edgar_ticker=edgar_ticker,
                    company_name=row["company_name"],
                    cik=cik,
                    gics_sector=row["gics_sector"],
                )
            )
    return resolved, unresolved


def main() -> int:
    """Build the universe file and print a summary."""
    resolved, unresolved = asyncio.run(build_universe())
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": WIKIPEDIA_URL,
        "resolved_count": len(resolved),
        "unresolved": unresolved,
        "members": [member.model_dump() for member in resolved],
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"\nS&P 500 universe: {len(resolved)} resolved, {len(unresolved)} unresolved")
    for entry in unresolved:
        print(f"  unresolved: {entry['ticker']} ({entry['reason']})")
    print(f"written to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
