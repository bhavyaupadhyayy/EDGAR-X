"""Validate every Avro schema parses and round-trips a representative record."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime
from typing import Any

import fastavro
import pytest

from ingestion.kafka.producer import TOPICS, schema_path

NOW = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)

SAMPLE_RECORDS: dict[str, dict[str, Any]] = {
    "filing": {
        "accession_number": "0000320193-26-000010",
        "cik": "0000320193",
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "form_type": "10-Q",
        "filing_date": date(2026, 5, 1),
        "document_url": "https://www.sec.gov/Archives/...",
        "raw_text": "Item 1. Business ...",
        "sections": {"business": "We design ..."},
        "ingested_at": NOW,
    },
    "transcript": {
        "company_name": "Apple",
        "ticker": "AAPL",
        "quarter": 2,
        "fiscal_year": 2026,
        "url": "https://www.fool.com/...",
        "segments": [
            {"speaker": "Tim Cook", "role": "CEO", "section": "prepared_remarks", "text": "Hi"}
        ],
        "ingested_at": NOW,
    },
    "macro": {
        "series_id": "FEDFUNDS",
        "observation_date": date(2026, 5, 1),
        "value": 5.25,
        "ingested_at": NOW,
    },
    "options": {
        "underlying": "AAPL",
        "contract_ticker": "O:AAPL260717C00200000",
        "contract_type": "call",
        "strike": 200.0,
        "expiration": date(2026, 7, 17),
        "day_volume": 5000,
        "open_interest": 1000,
        "volume_oi_ratio": 5.0,
        "implied_volatility": 0.42,
        "detected_at": NOW,
    },
    "sentiment": {
        "post_id": "p1",
        "subreddit": "wallstreetbets",
        "title": "$GME",
        "body": "to the moon",
        "score": 100,
        "num_comments": 10,
        "tickers": ["GME"],
        "created_at": NOW,
        "ingested_at": NOW,
    },
}


@pytest.mark.parametrize("stream", sorted(TOPICS))
def test_schema_parses_and_roundtrips(stream: str) -> None:
    """Each .avsc must be valid Avro and accept its representative record."""
    schema = fastavro.schema.load_schema(str(schema_path(stream)))
    buffer = io.BytesIO()
    fastavro.schemaless_writer(buffer, schema, SAMPLE_RECORDS[stream])
    buffer.seek(0)
    decoded = fastavro.schemaless_reader(buffer, schema)
    assert decoded["ingested_at" if "ingested_at" in decoded else "detected_at"] is not None
