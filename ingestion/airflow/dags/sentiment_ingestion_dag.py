"""Hourly ingestion of Reddit retail sentiment into the ``sentiment.raw`` topic.

Pulls the hot listing from r/wallstreetbets, r/investing, and r/stocks,
extracts ticker mentions, and publishes each post as Avro.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from airflow import DAG
from airflow.operators.python import PythonOperator

from ingestion.airflow.dags._common import DEFAULT_ARGS, START_DATE, make_verify_callable
from ingestion.airflow.dags.alerts import sla_miss_callback


def ingest_sentiment(**context: Any) -> int:
    """Fetch and publish posts from all tracked subreddits.

    Returns:
        The number of posts published (pushed to XCom).
    """
    from ingestion.kafka.producer import producer_for_stream
    from ingestion.sources.reddit_client import RedditClient

    async def _run() -> int:
        producer = producer_for_stream("sentiment")
        published = 0
        async with RedditClient() as client:
            for post in await client.fetch_all_subreddits(limit=100):
                if producer.produce(post.to_kafka_payload(), key=post.post_id):
                    published += 1
        producer.flush()
        return published

    return asyncio.run(_run())


with DAG(
    dag_id="sentiment_ingestion",
    description="Ingest Reddit retail sentiment into Kafka",
    schedule="@hourly",
    start_date=START_DATE,
    catchup=False,
    default_args=DEFAULT_ARGS,
    sla_miss_callback=sla_miss_callback,
    tags=["ingestion", "sentiment"],
) as dag:
    ingest = PythonOperator(
        task_id="ingest_sentiment",
        python_callable=ingest_sentiment,
        sla=timedelta(minutes=30),
    )
    verify = PythonOperator(
        task_id="verify_publish",
        python_callable=make_verify_callable("ingest_sentiment"),
    )
    ingest >> verify
