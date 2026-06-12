"""Snowflake sink for the raw landing tables.

Connects with key-pair (JWT) authentication and bulk-loads rows via
``write_pandas``. Table DDL here is the single source of truth for the RAW
landing contract; each schema mirrors exactly the columns the corresponding
dbt staging model selects (see ``transforms/dbt/models/staging/stg_*.sql``).

Identifiers are deliberately unquoted (Snowflake-uppercase) so the dbt
models' unquoted references resolve to the same tables.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol

from core.config import get_settings
from core.logging import get_logger
from ingestion.sources.http_utils import ConfigurationError

logger = get_logger(__name__)

#: RAW table name -> ordered column -> Snowflake type. Must stay in lockstep
#: with the dbt staging models and (in dev) the dbt seed contracts.
RAW_TABLE_SCHEMAS: dict[str, dict[str, str]] = {
    "RAW_COMPANIES": {
        "TICKER": "VARCHAR",
        "CIK": "VARCHAR",
        "COMPANY_NAME": "VARCHAR",
        "SECTOR": "VARCHAR",
        "INDUSTRY": "VARCHAR",
    },
    "RAW_FILINGS": {
        "ACCESSION_NUMBER": "VARCHAR",
        "CIK": "VARCHAR",
        "TICKER": "VARCHAR",
        "COMPANY_NAME": "VARCHAR",
        "FORM_TYPE": "VARCHAR",
        "FILING_DATE": "DATE",
        "DOCUMENT_URL": "VARCHAR",
        "MDNA_TEXT": "VARCHAR",
        "RISK_FACTORS_TEXT": "VARCHAR",
        "INGESTED_AT": "TIMESTAMP_TZ",
    },
    "RAW_FUNDAMENTALS": {
        "TICKER": "VARCHAR",
        "FISCAL_YEAR": "NUMBER(38,0)",
        "FISCAL_QUARTER": "NUMBER(38,0)",
        "PERIOD_END_DATE": "DATE",
        "REVENUE": "FLOAT",
        "COST_OF_REVENUE": "FLOAT",
        "NET_INCOME": "FLOAT",
        "TOTAL_ASSETS": "FLOAT",
        "TOTAL_LIABILITIES": "FLOAT",
        "TOTAL_EQUITY": "FLOAT",
        "TOTAL_DEBT": "FLOAT",
        "SHARES_OUTSTANDING": "FLOAT",
        "CLOSE_PRICE": "FLOAT",
    },
    "RAW_MACRO_OBSERVATIONS": {
        "SERIES_ID": "VARCHAR",
        "OBSERVATION_DATE": "DATE",
        "VALUE": "FLOAT",
        "INGESTED_AT": "TIMESTAMP_TZ",
    },
    "RAW_OPTIONS_ACTIVITY": {
        "UNDERLYING": "VARCHAR",
        "CONTRACT_TICKER": "VARCHAR",
        "CONTRACT_TYPE": "VARCHAR",
        "STRIKE": "FLOAT",
        "EXPIRATION": "DATE",
        "DAY_VOLUME": "NUMBER(38,0)",
        "OPEN_INTEREST": "NUMBER(38,0)",
        "VOLUME_OI_RATIO": "FLOAT",
        "IMPLIED_VOLATILITY": "FLOAT",
        "DETECTED_AT": "TIMESTAMP_TZ",
    },
    "RAW_SENTIMENT_MENTIONS": {
        "POST_ID": "VARCHAR",
        "SUBREDDIT": "VARCHAR",
        "TICKER": "VARCHAR",
        "TITLE": "VARCHAR",
        "SCORE": "NUMBER(38,0)",
        "NUM_COMMENTS": "NUMBER(38,0)",
        "CREATED_AT": "TIMESTAMP_TZ",
        "INGESTED_AT": "TIMESTAMP_TZ",
    },
    "RAW_TRANSCRIPT_SEGMENTS": {
        "URL": "VARCHAR",
        "TICKER": "VARCHAR",
        "COMPANY_NAME": "VARCHAR",
        "FISCAL_YEAR": "NUMBER(38,0)",
        "FISCAL_QUARTER": "NUMBER(38,0)",
        "SEGMENT_INDEX": "NUMBER(38,0)",
        "SPEAKER": "VARCHAR",
        "ROLE": "VARCHAR",
        "SECTION": "VARCHAR",
        "TEXT": "VARCHAR",
        "INGESTED_AT": "TIMESTAMP_TZ",
    },
}


class ConnectionLike(Protocol):
    """Minimal connection interface (subset of ``SnowflakeConnection``)."""

    def cursor(self) -> Any:
        """Return a cursor."""
        ...

    def close(self) -> None:
        """Close the connection."""
        ...


def load_private_key_der(path: str, passphrase: str | None = None) -> bytes:
    """Load a PKCS#8 PEM private key and return DER bytes for the connector.

    Args:
        path: Filesystem path to the ``.p8`` key file.
        passphrase: Key passphrase, if encrypted.

    Returns:
        The key serialized as unencrypted PKCS#8 DER, as the Snowflake
        connector expects.

    Raises:
        ConfigurationError: If the key file does not exist.
    """
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415 - heavy import

    key_path = Path(path).expanduser()
    if not key_path.exists():
        raise ConfigurationError(f"Snowflake private key not found at {key_path}")
    key = serialization.load_pem_private_key(
        key_path.read_bytes(),
        password=passphrase.encode() if passphrase else None,
    )
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _default_connection() -> ConnectionLike:
    """Open a real Snowflake connection via key-pair (JWT) auth.

    Raises:
        ConfigurationError: If required SNOWFLAKE_* settings are missing.
    """
    import snowflake.connector  # noqa: PLC0415 - deferred: heavy optional import

    settings = get_settings()
    missing = [
        name
        for name, value in {
            "SNOWFLAKE_ACCOUNT": settings.snowflake_account,
            "SNOWFLAKE_USER": settings.snowflake_user,
            "SNOWFLAKE_PRIVATE_KEY_PATH": settings.snowflake_private_key_path,
            "SNOWFLAKE_WAREHOUSE": settings.snowflake_warehouse,
        }.items()
        if not value
    ]
    if missing:
        raise ConfigurationError(f"missing Snowflake settings: {', '.join(missing)}")
    private_key = load_private_key_der(
        settings.snowflake_private_key_path or "",
        settings.snowflake_private_key_passphrase,
    )
    return snowflake.connector.connect(  # type: ignore[no-any-return]
        account=settings.snowflake_account,
        user=settings.snowflake_user,
        private_key=private_key,
        authenticator="SNOWFLAKE_JWT",
        database=settings.snowflake_database,
        warehouse=settings.snowflake_warehouse,
        schema=settings.snowflake_raw_schema,
    )


def _default_write_pandas(conn: ConnectionLike, df: Any, **kwargs: Any) -> tuple[bool, int, int]:
    """Call the real ``write_pandas`` helper (deferred heavy import)."""
    from snowflake.connector.pandas_tools import write_pandas  # noqa: PLC0415

    success, _chunks, nrows, _output = write_pandas(conn, df, **kwargs)
    return success, _chunks, nrows


class SnowflakeWriter:
    """Creates and bulk-loads the RAW landing tables.

    Usage::

        with SnowflakeWriter() as writer:
            writer.create_raw_tables()
            writer.write_rows("RAW_COMPANIES", rows)
    """

    def __init__(
        self,
        *,
        connection: ConnectionLike | None = None,
        write_pandas_fn: Callable[..., tuple[bool, int, int]] | None = None,
        database: str | None = None,
        schema: str | None = None,
    ) -> None:
        """Initialise the writer.

        Args:
            connection: Optional injected connection (tests). When omitted, a
                real key-pair-auth connection is opened lazily on first use.
            write_pandas_fn: Optional injected bulk-load function (tests).
            database: Target database; falls back to settings.
            schema: Target schema; falls back to settings (RAW).
        """
        settings = get_settings()
        self._connection = connection
        self._owns_connection = connection is None
        self._write_pandas = write_pandas_fn or _default_write_pandas
        self._database = database or settings.snowflake_database
        self._schema = schema or settings.snowflake_raw_schema

    def __enter__(self) -> SnowflakeWriter:
        """Enter the context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the connection if this instance owns it."""
        self.close()

    def _conn(self) -> ConnectionLike:
        """Return the connection, opening the default one on first use."""
        if self._connection is None:
            self._connection = _default_connection()
        return self._connection

    def _qualified(self, table: str) -> str:
        """Return the fully qualified table name."""
        return f"{self._database}.{self._schema}.{table}"

    def create_raw_tables(self) -> list[str]:
        """Create every RAW landing table if it does not already exist.

        Returns:
            The list of fully qualified table names ensured.
        """
        ensured: list[str] = []
        cursor = self._conn().cursor()
        for table, columns in RAW_TABLE_SCHEMAS.items():
            ddl_columns = ", ".join(f"{name} {sql_type}" for name, sql_type in columns.items())
            cursor.execute(
                f"create table if not exists {self._qualified(table)} ({ddl_columns})"
            )
            ensured.append(self._qualified(table))
        logger.info("snowflake_raw_tables_ensured", tables=len(ensured))
        return ensured

    def truncate_table(self, table: str) -> None:
        """Truncate one RAW table (idempotent backfills).

        Args:
            table: RAW table name, e.g. ``"RAW_FILINGS"``.

        Raises:
            KeyError: If the table is not a known RAW table.
        """
        if table not in RAW_TABLE_SCHEMAS:
            raise KeyError(f"unknown RAW table {table!r}")
        self._conn().cursor().execute(f"truncate table if exists {self._qualified(table)}")
        logger.info("snowflake_table_truncated", table=table)

    def delete_rows(self, table: str, *, column: str, value: str) -> None:
        """Delete rows matching one column value (per-company idempotent loads).

        The column name is validated against the table contract, so only the
        value travels as a bind parameter.

        Args:
            table: RAW table name, e.g. ``"RAW_FILINGS"``.
            column: Column to filter on, e.g. ``"TICKER"``.
            value: Value whose rows are deleted.

        Raises:
            KeyError: If the table or column is not part of the RAW contract.
        """
        if table not in RAW_TABLE_SCHEMAS:
            raise KeyError(f"unknown RAW table {table!r}")
        if column.upper() not in RAW_TABLE_SCHEMAS[table]:
            raise KeyError(f"column {column!r} not in {table}")
        self._conn().cursor().execute(
            f"delete from {self._qualified(table)} where {column.upper()} = %s",
            (value,),
        )

    def write_rows(self, table: str, rows: Sequence[Mapping[str, Any]]) -> int:
        """Bulk-insert rows into one RAW table via ``write_pandas``.

        Row keys are matched case-insensitively against the table contract;
        missing columns load as NULL, unknown keys are rejected.

        Args:
            table: RAW table name, e.g. ``"RAW_FUNDAMENTALS"``.
            rows: Records to insert.

        Returns:
            The number of rows written.

        Raises:
            KeyError: If the table is unknown or a row has unknown columns.
            RuntimeError: If the bulk load reports failure.
        """
        if table not in RAW_TABLE_SCHEMAS:
            raise KeyError(f"unknown RAW table {table!r}")
        if not rows:
            return 0
        import pandas as pd  # noqa: PLC0415 - deferred: heavy optional import

        columns = list(RAW_TABLE_SCHEMAS[table])
        normalised: list[dict[str, Any]] = []
        for row in rows:
            upper = {key.upper(): value for key, value in row.items()}
            unknown = set(upper) - set(columns)
            if unknown:
                raise KeyError(f"row has columns not in {table}: {sorted(unknown)}")
            normalised.append({column: upper.get(column) for column in columns})

        frame = pd.DataFrame(normalised, columns=columns)
        success, _chunks, nrows = self._write_pandas(
            self._conn(),
            frame,
            table_name=table,
            database=self._database,
            schema=self._schema,
            quote_identifiers=False,
            auto_create_table=False,
            use_logical_type=True,
        )
        if not success:
            raise RuntimeError(f"write_pandas reported failure loading {table}")
        logger.info("snowflake_rows_written", table=table, rows=nrows)
        return int(nrows)

    def close(self) -> None:
        """Close the connection if this instance owns it."""
        if self._owns_connection and self._connection is not None:
            self._connection.close()
            self._connection = None
