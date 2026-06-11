"""Daily ingestion of FRED macro indicators into the ``macro.raw`` topic.

Fetches the last 7 days of observations for every tracked series (FEDFUNDS,
CPIAUCSL, UNRATE, GDP, DGS10, T10Y2Y) and publishes each observation as Avro.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

from airflow import DAG
from airflow.operators.python import PythonOperator

from ingestion.airflow.dags._common import DEFAULT_ARGS, START_DATE, make_verify_callable
from ingestion.airflow.dags.alerts import sla_miss_callback


def ingest_macro(**context: Any) -> int:
    """Fetch and publish recent observations for all tracked FRED series.

    Returns:
        The number of observations published (pushed to XCom).
    """
    from ingestion.kafka.producer import producer_for_stream
    from ingestion.sources.fred_client import FredClient

    async def _run() -> int:
        producer = producer_for_stream("macro")
        published = 0
        async with FredClient() as client:
            all_series = await client.get_all_tracked_series(
                start_date=date.today() - timedelta(days=7)
            )
            for series in all_series.values():
                for observation in series.observations:
                    payload = {
                        "series_id": observation.series_id,
                        "observation_date": observation.timestamp,
                        "value": observation.value,
                        "ingested_at": datetime.now(UTC),
                    }
                    key = f"{observation.series_id}:{observation.timestamp.isoformat()}"
                    if producer.produce(payload, key=key):
                        published += 1
        producer.flush()
        return published

    return asyncio.run(_run())


with DAG(
    dag_id="macro_ingestion",
    description="Ingest FRED macro indicators into Kafka",
    schedule="0 6 * * *",
    start_date=START_DATE,
    catchup=False,
    default_args=DEFAULT_ARGS,
    sla_miss_callback=sla_miss_callback,
    tags=["ingestion", "macro"],
) as dag:
    ingest = PythonOperator(
        task_id="ingest_macro",
        python_callable=ingest_macro,
        sla=timedelta(minutes=30),
    )
    verify = PythonOperator(
        task_id="verify_publish",
        python_callable=make_verify_callable("ingest_macro"),
    )
    ingest >> verify
