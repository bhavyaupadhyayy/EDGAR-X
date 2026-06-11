"""Shared helpers for EDGAR-X ingestion DAGs (universe, defaults, verification)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from ingestion.airflow.dags.alerts import on_failure_callback

#: Common default_args applied to every ingestion DAG.
DEFAULT_ARGS: dict[str, Any] = {
    "owner": "edgar-x",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "on_failure_callback": on_failure_callback,
}

#: Common start date for all DAGs (catchup disabled everywhere).
START_DATE = datetime(2026, 1, 1, tzinfo=UTC)


def ticker_universe() -> list[str]:
    """Return the ticker universe from ``EDGAR_X_UNIVERSE``.

    Interim mechanism until the Layer 2 universe mart provides the full
    ~6,000-company list.
    """
    raw = os.environ.get("EDGAR_X_UNIVERSE", "AAPL,MSFT,NVDA,AMZN,GOOGL")
    return [token.strip().upper() for token in raw.split(",") if token.strip()]


def make_verify_callable(upstream_task_id: str) -> Any:
    """Build a verification callable asserting the upstream task published records.

    Args:
        upstream_task_id: Task id whose XCom return value is the publish count.

    Returns:
        A python_callable for a ``PythonOperator``.
    """

    def _verify(**context: Any) -> int:
        published = context["ti"].xcom_pull(task_ids=upstream_task_id)
        if published is None:
            raise ValueError(f"no publish count reported by task {upstream_task_id!r}")
        return int(published)

    return _verify
