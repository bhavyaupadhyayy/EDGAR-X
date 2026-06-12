"""Unit tests for the Snowflake RAW-table writer (connector fully stubbed)."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ingestion.sinks.snowflake_writer import RAW_TABLE_SCHEMAS, SnowflakeWriter

SEED_DIR = Path(__file__).parents[2] / "transforms" / "dbt" / "seeds"


@dataclass
class FakeCursor:
    """Records every executed statement and its bind parameters."""

    statements: list[str] = field(default_factory=list)
    params: list[tuple[Any, ...] | None] = field(default_factory=list)

    def execute(self, sql: str, parameters: tuple[Any, ...] | None = None) -> FakeCursor:
        self.statements.append(sql)
        self.params.append(parameters)
        return self


@dataclass
class FakeConnection:
    """In-memory stand-in for a SnowflakeConnection."""

    cursor_obj: FakeCursor = field(default_factory=FakeCursor)
    closed: bool = False

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def close(self) -> None:
        self.closed = True


class FakeWritePandas:
    """Captures write_pandas calls and returns success."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.succeed = True

    def __call__(self, conn: Any, df: Any, **kwargs: Any) -> tuple[bool, int, int]:
        self.calls.append({"df": df, **kwargs})
        return self.succeed, 1, len(df)


@pytest.fixture()
def fake_conn() -> FakeConnection:
    return FakeConnection()


@pytest.fixture()
def fake_wp() -> FakeWritePandas:
    return FakeWritePandas()


@pytest.fixture()
def writer(fake_conn: FakeConnection, fake_wp: FakeWritePandas) -> SnowflakeWriter:
    return SnowflakeWriter(
        connection=fake_conn,
        write_pandas_fn=fake_wp,
        database="EDGAR_X",
        schema="RAW",
    )


class TestSchemaContract:
    """The writer DDL must match the dbt-side raw contracts."""

    def test_covers_all_seven_raw_tables(self) -> None:
        assert set(RAW_TABLE_SCHEMAS) == {
            "RAW_COMPANIES",
            "RAW_FILINGS",
            "RAW_FUNDAMENTALS",
            "RAW_MACRO_OBSERVATIONS",
            "RAW_OPTIONS_ACTIVITY",
            "RAW_SENTIMENT_MENTIONS",
            "RAW_TRANSCRIPT_SEGMENTS",
        }

    @pytest.mark.parametrize("table", sorted(RAW_TABLE_SCHEMAS))
    def test_columns_match_dbt_seed_contract(self, table: str) -> None:
        """Seed CSV headers are the dev landing contract; DDL must agree."""
        seed_file = SEED_DIR / f"{table.lower()}.csv"
        with seed_file.open() as handle:
            seed_columns = next(csv.reader(handle))
        assert [c.lower() for c in RAW_TABLE_SCHEMAS[table]] == seed_columns


class TestCreateRawTables:
    """DDL generation."""

    def test_creates_all_tables_if_not_exists(
        self, writer: SnowflakeWriter, fake_conn: FakeConnection
    ) -> None:
        ensured = writer.create_raw_tables()
        assert len(ensured) == 7
        statements = fake_conn.cursor_obj.statements
        assert len(statements) == 7
        assert all(s.startswith("create table if not exists EDGAR_X.RAW.") for s in statements)
        filings_ddl = next(s for s in statements if "RAW_FILINGS" in s)
        assert "FILING_DATE DATE" in filings_ddl
        assert "INGESTED_AT TIMESTAMP_TZ" in filings_ddl


class TestWriteRows:
    """Bulk-load behaviour."""

    def test_writes_rows_with_normalised_columns(
        self, writer: SnowflakeWriter, fake_wp: FakeWritePandas
    ) -> None:
        rows = [
            {"ticker": "AAPL", "cik": "0000320193", "company_name": "Apple Inc.",
             "sector": "Technology", "industry": "Consumer Electronics"},
        ]
        written = writer.write_rows("RAW_COMPANIES", rows)
        assert written == 1
        call = fake_wp.calls[0]
        assert call["table_name"] == "RAW_COMPANIES"
        assert call["schema"] == "RAW"
        assert call["quote_identifiers"] is False
        assert list(call["df"].columns) == list(RAW_TABLE_SCHEMAS["RAW_COMPANIES"])

    def test_missing_columns_become_null(
        self, writer: SnowflakeWriter, fake_wp: FakeWritePandas
    ) -> None:
        rows = [{"ticker": "AAPL", "fiscal_year": 2025, "fiscal_quarter": 4,
                 "period_end_date": date(2025, 9, 27), "revenue": 416.2e9}]
        writer.write_rows("RAW_FUNDAMENTALS", rows)
        frame = fake_wp.calls[0]["df"]
        assert frame["CLOSE_PRICE"].isna().all()
        assert frame["REVENUE"].iloc[0] == 416.2e9

    def test_unknown_column_rejected(self, writer: SnowflakeWriter) -> None:
        with pytest.raises(KeyError, match="not in RAW_COMPANIES"):
            writer.write_rows("RAW_COMPANIES", [{"ticker": "AAPL", "bogus": 1}])

    def test_unknown_table_rejected(self, writer: SnowflakeWriter) -> None:
        with pytest.raises(KeyError, match="unknown RAW table"):
            writer.write_rows("RAW_NOPE", [{"a": 1}])

    def test_empty_rows_short_circuit(
        self, writer: SnowflakeWriter, fake_wp: FakeWritePandas
    ) -> None:
        assert writer.write_rows("RAW_COMPANIES", []) == 0
        assert fake_wp.calls == []

    def test_load_failure_raises(
        self, writer: SnowflakeWriter, fake_wp: FakeWritePandas
    ) -> None:
        fake_wp.succeed = False
        with pytest.raises(RuntimeError, match="write_pandas reported failure"):
            writer.write_rows("RAW_COMPANIES", [{"ticker": "AAPL"}])


class TestLifecycle:
    """Truncation and connection ownership."""

    def test_truncate_known_table(
        self, writer: SnowflakeWriter, fake_conn: FakeConnection
    ) -> None:
        writer.truncate_table("RAW_MACRO_OBSERVATIONS")
        assert fake_conn.cursor_obj.statements == [
            "truncate table if exists EDGAR_X.RAW.RAW_MACRO_OBSERVATIONS"
        ]

    def test_truncate_unknown_table_rejected(self, writer: SnowflakeWriter) -> None:
        with pytest.raises(KeyError):
            writer.truncate_table("STAGING_SOMETHING")

    def test_delete_rows_parameterised(
        self, writer: SnowflakeWriter, fake_conn: FakeConnection
    ) -> None:
        writer.delete_rows("RAW_FILINGS", column="ticker", value="AAPL")
        assert fake_conn.cursor_obj.statements == [
            "delete from EDGAR_X.RAW.RAW_FILINGS where TICKER = %s"
        ]
        assert fake_conn.cursor_obj.params == [("AAPL",)]

    def test_delete_rows_rejects_unknown_column(self, writer: SnowflakeWriter) -> None:
        with pytest.raises(KeyError, match="not in RAW_FILINGS"):
            writer.delete_rows("RAW_FILINGS", column="bogus; drop table", value="x")

    def test_injected_connection_not_closed(
        self, writer: SnowflakeWriter, fake_conn: FakeConnection
    ) -> None:
        with writer:
            pass
        assert fake_conn.closed is False
