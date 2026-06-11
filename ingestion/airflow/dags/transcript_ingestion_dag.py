"""Daily ingestion of earnings-call transcripts into ``transcripts.raw``.

Transcript URLs for the day are read from the ``edgar_x_transcript_urls``
Airflow Variable (JSON list) until the Layer 2 earnings-calendar mart can
drive discovery automatically. Each transcript is scraped, parsed into
speaker segments, and published as Avro.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any

from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator

from ingestion.airflow.dags._common import DEFAULT_ARGS, START_DATE, make_verify_callable
from ingestion.airflow.dags.alerts import sla_miss_callback


def ingest_transcripts(**context: Any) -> int:
    """Scrape and publish every transcript URL queued for today.

    Returns:
        The number of transcripts published (pushed to XCom).
    """
    from ingestion.kafka.producer import producer_for_stream
    from ingestion.sources.transcript_scraper import TranscriptParseError, TranscriptScraper

    urls: list[str] = json.loads(Variable.get("edgar_x_transcript_urls", default_var="[]"))

    async def _run() -> int:
        producer = producer_for_stream("transcript")
        published = 0
        async with TranscriptScraper() as scraper:
            for url in urls:
                try:
                    transcript = await scraper.fetch_transcript(url)
                except TranscriptParseError:
                    # Parse failures are logged by the scraper; skip and move on.
                    continue
                if producer.produce(transcript.to_kafka_payload(), key=url):
                    published += 1
        producer.flush()
        return published

    return asyncio.run(_run())


with DAG(
    dag_id="transcript_ingestion",
    description="Scrape earnings-call transcripts into Kafka",
    schedule="0 22 * * 1-5",
    start_date=START_DATE,
    catchup=False,
    default_args=DEFAULT_ARGS,
    sla_miss_callback=sla_miss_callback,
    tags=["ingestion", "transcripts"],
) as dag:
    ingest = PythonOperator(
        task_id="ingest_transcripts",
        python_callable=ingest_transcripts,
        sla=timedelta(hours=1),
    )
    verify = PythonOperator(
        task_id="verify_publish",
        python_callable=make_verify_callable("ingest_transcripts"),
    )
    ingest >> verify
