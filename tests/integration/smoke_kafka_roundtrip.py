"""End-to-end smoke test against the live docker-compose stack.

Produces a real Avro record through Schema Registry into Kafka using the
project's own producer, consumes it back with the project's consumer, and
verifies the dead-letter path with an intentionally invalid record.

Run manually with the stack up:  python tests/integration/smoke_kafka_roundtrip.py
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, date, datetime

from confluent_kafka import Consumer

from core.logging import configure_logging, get_logger
from ingestion.kafka.consumer import KafkaAvroConsumer
from ingestion.kafka.producer import KafkaAvroProducer, schema_path

configure_logging()
logger = get_logger("smoke")

TOPIC = "macro.raw"


def main() -> int:
    """Run the round-trip and DLQ checks; return a process exit code."""
    run_id = uuid.uuid4().hex[:8]
    key = f"SMOKE:{run_id}"
    record = {
        "series_id": f"SMOKE_{run_id}",
        "observation_date": date.today(),
        "value": 5.25,
        "ingested_at": datetime.now(UTC),
    }

    producer = KafkaAvroProducer(topic=TOPIC, schema_file=schema_path("macro"))

    # 1. Happy path: Avro-serialise via Schema Registry and publish.
    assert producer.produce(record, key=key) is True, "produce() returned False"
    producer.flush()
    logger.info("smoke_produced", key=key)

    # 2. Consume it back with the project consumer. The fresh group starts at
    # ``earliest``, so scan past any records left over from previous runs.
    received: list[dict[str, object]] = []
    consumer = KafkaAvroConsumer(
        topic=TOPIC,
        schema_file=schema_path("macro"),
        group_id=f"smoke-{run_id}",
    )
    # Block for the first record (rides out the initial group rebalance,
    # where polls return None), then drain whatever else is on the topic.
    consumer.consume(received.append, max_messages=1, poll_timeout=2.0)
    consumer.consume(received.append, poll_timeout=2.0, stop_on_empty=True)
    consumer.close()
    assert received, "no message consumed"
    matches = [r for r in received if r["series_id"] == record["series_id"]]
    assert matches, f"own record not found among {len(received)} consumed"
    got = matches[0]
    assert got["value"] == 5.25
    logger.info("smoke_roundtrip_ok", record=str(got))

    # 3. DLQ path: a record violating the schema must land in macro.raw.dlq.
    bad = {"series_id": "SMOKE_BAD", "value": "not-a-float"}
    assert producer.produce(bad, key=f"{key}:bad") is False, "bad record was accepted"
    producer.flush()

    dlq_consumer = Consumer(
        {
            "bootstrap.servers": "localhost:9092",
            "group.id": f"smoke-dlq-{run_id}",
            "auto.offset.reset": "earliest",
        }
    )
    dlq_consumer.subscribe([f"{TOPIC}.dlq"])
    dlq_record: dict[str, object] | None = None
    for _ in range(15):
        message = dlq_consumer.poll(2.0)
        if message is None or message.error():
            continue
        candidate = json.loads(message.value())
        if candidate.get("key") == f"{key}:bad":
            dlq_record = candidate
            break
    dlq_consumer.close()
    assert dlq_record is not None, "dead-lettered record not found in macro.raw.dlq"
    assert dlq_record["context"] == {"stage": "serialization"}
    logger.info("smoke_dlq_ok", error_type=dlq_record["error_type"])

    print(f"SMOKE PASSED  run_id={run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
