"""Hourly ingestion of SEC EDGAR filings into the ``filings.raw`` topic.

For each ticker in the universe, lists filings from the last day, fetches and
parses each document, and publishes it as Avro. Failures alert via the shared
callbacks; serialization/delivery failures land in ``filings.raw.dlq``.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
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


def ingest_filings(**context: Any) -> int:
    """Fetch and publish recent filings for the whole universe.

    Returns:
        The number of filings published (pushed to XCom).
    """
    from ingestion.kafka.producer import producer_for_stream
    from ingestion.sources.edgar_client import EdgarClient

    async def _run() -> int:
        producer = producer_for_stream("filing")
        published = 0
        async with EdgarClient() as client:
            for ticker in ticker_universe():
                filings = await client.get_filings(
                    ticker, start_date=date.today() - timedelta(days=1)
                )
                for metadata in filings:
                    filing = await client.fetch_filing(metadata)
                    if producer.produce(filing.to_kafka_payload(), key=metadata.accession_number):
                        published += 1
        producer.flush()
        return published

    return asyncio.run(_run())


with DAG(
    dag_id="edgar_ingestion",
    description="Ingest SEC EDGAR filings into Kafka",
    schedule="@hourly",
    start_date=START_DATE,
    catchup=False,
    default_args=DEFAULT_ARGS,
    sla_miss_callback=sla_miss_callback,
    tags=["ingestion", "edgar"],
) as dag:
    ingest = PythonOperator(
        task_id="ingest_filings",
        python_callable=ingest_filings,
        sla=timedelta(minutes=45),
    )
    verify = PythonOperator(
        task_id="verify_publish",
        python_callable=make_verify_callable("ingest_filings"),
    )
    ingest >> verify
