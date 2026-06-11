"""Intraday detection of unusual options activity into ``options.unusual_activity``.

Runs every 15 minutes during US market hours (13:30–20:00 UTC, Mon–Fri),
scans the options chain of every universe ticker, and publishes flagged
contracts as Avro.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from airflow import DAG
from airflow.operators.python import PythonOperator

from ingestion.airflow.dags._common import (
    DEFAULT_ARGS,
    START_DATE,
    make_verify_callable,
    ticker_universe,
)
from ingestion.airflow.dags.alerts import sla_miss_callback


def ingest_options(**context: Any) -> int:
    """Detect and publish unusual options activity for the whole universe.

    Returns:
        The number of flagged contracts published (pushed to XCom).
    """
    from ingestion.kafka.producer import producer_for_stream
    from ingestion.sources.polygon_client import PolygonClient

    async def _run() -> int:
        producer = producer_for_stream("options")
        published = 0
        async with PolygonClient() as client:
            for ticker in ticker_universe():
                events = await client.detect_unusual_activity(ticker)
                for event in events:
                    key = event.contract.contract_ticker
                    if producer.produce(event.to_kafka_payload(), key=key):
                        published += 1
        producer.flush()
        return published

    return asyncio.run(_run())


with DAG(
    dag_id="options_ingestion",
    description="Detect unusual options activity via Polygon.io",
    schedule="*/15 13-20 * * 1-5",
    start_date=START_DATE,
    catchup=False,
    default_args=DEFAULT_ARGS,
    sla_miss_callback=sla_miss_callback,
    tags=["ingestion", "options"],
) as dag:
    ingest = PythonOperator(
        task_id="ingest_options",
        python_callable=ingest_options,
        sla=timedelta(minutes=10),
    )
    verify = PythonOperator(
        task_id="verify_publish",
        python_callable=make_verify_callable("ingest_options"),
    )
    ingest >> verify
