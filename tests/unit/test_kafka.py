"""Unit tests for the Kafka producer, consumer, and dead letter queue.

All confluent-kafka objects are replaced with in-memory fakes; no broker is
required.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from ingestion.kafka.consumer import KafkaAvroConsumer
from ingestion.kafka.dead_letter_queue import DeadLetterQueue
from ingestion.kafka.producer import (
    TOPICS,
    KafkaAvroProducer,
    MessageContext,
    schema_path,
)


@dataclass
class FakeProducer:
    """In-memory stand-in for confluent_kafka.Producer."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    flushed: int = 0

    def produce(self, topic: str, value: bytes, key: bytes | None = None) -> None:
        self.messages.append({"topic": topic, "value": value, "key": key})

    def poll(self, timeout: float) -> int:
        return 0

    def flush(self, timeout: float) -> int:
        self.flushed += 1
        return 0


@dataclass
class FakeMessage:
    """In-memory stand-in for confluent_kafka.Message."""

    _value: bytes | None
    _key: bytes | None = None
    _error: object | None = None

    def error(self) -> object | None:
        return self._error

    def key(self) -> bytes | None:
        return self._key

    def value(self) -> bytes | None:
        return self._value


class FakeConsumer:
    """In-memory stand-in for confluent_kafka.Consumer."""

    def __init__(self, messages: list[FakeMessage]) -> None:
        self._messages = list(messages)
        self.subscribed: list[str] = []
        self.committed: list[FakeMessage] = []
        self.closed = False

    def subscribe(self, topics: list[str]) -> None:
        self.subscribed = topics

    def poll(self, timeout: float) -> FakeMessage | None:
        return self._messages.pop(0) if self._messages else None

    def commit(self, message: FakeMessage) -> object:
        self.committed.append(message)
        return None

    def close(self) -> None:
        self.closed = True


def _json_serializer(value: dict[str, Any], ctx: MessageContext) -> bytes:
    return json.dumps(value).encode()


def _json_deserializer(value: bytes | None, ctx: MessageContext) -> dict[str, Any] | None:
    if value is None:
        return None
    return dict(json.loads(value))


class TestSchemaPath:
    """Schema file resolution."""

    def test_resolves_all_streams(self) -> None:
        for stream in TOPICS:
            assert schema_path(stream).exists()

    def test_unknown_schema_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            schema_path("nonexistent")


class TestKafkaAvroProducer:
    """Producer happy path and dead-letter routing."""

    def _build(self, fake: FakeProducer, dlq_fake: FakeProducer) -> KafkaAvroProducer:
        return KafkaAvroProducer(
            topic="filings.raw",
            schema_file=schema_path("filing"),
            producer=fake,
            serializer=_json_serializer,
            dlq=DeadLetterQueue(producer=dlq_fake),
        )

    def test_produce_serialises_and_enqueues(self) -> None:
        fake, dlq_fake = FakeProducer(), FakeProducer()
        producer = self._build(fake, dlq_fake)
        assert producer.produce({"a": 1}, key="k1") is True
        assert len(fake.messages) == 1
        assert fake.messages[0]["topic"] == "filings.raw"
        assert fake.messages[0]["key"] == b"k1"
        assert json.loads(fake.messages[0]["value"]) == {"a": 1}
        assert dlq_fake.messages == []

    def test_serialization_failure_routes_to_dlq(self) -> None:
        fake, dlq_fake = FakeProducer(), FakeProducer()

        def broken_serializer(value: dict[str, Any], ctx: MessageContext) -> bytes:
            raise ValueError("schema mismatch")

        producer = KafkaAvroProducer(
            topic="filings.raw",
            schema_file=schema_path("filing"),
            producer=fake,
            serializer=broken_serializer,
            dlq=DeadLetterQueue(producer=dlq_fake),
        )
        assert producer.produce({"bad": object}, key="k1") is False
        assert fake.messages == []
        assert len(dlq_fake.messages) == 1
        record = json.loads(dlq_fake.messages[0]["value"])
        assert record["source_topic"] == "filings.raw"
        assert record["error_type"] == "ValueError"
        assert record["context"]["stage"] == "serialization"
        assert dlq_fake.messages[0]["topic"] == "filings.raw.dlq"

    def test_flush_delegates(self) -> None:
        fake, dlq_fake = FakeProducer(), FakeProducer()
        producer = self._build(fake, dlq_fake)
        producer.flush()
        assert fake.flushed == 1


class TestDeadLetterQueue:
    """DLQ record shape and resilience."""

    def test_record_contains_error_context(self) -> None:
        fake = FakeProducer()
        dlq = DeadLetterQueue(producer=fake)
        dlq.send(
            "macro.raw",
            key="FEDFUNDS:2026-05-01",
            raw_value=b"\x00payload",
            error=RuntimeError("boom"),
            context={"ticker": "AAPL"},
        )
        record = json.loads(fake.messages[0]["value"])
        assert record["source_topic"] == "macro.raw"
        assert record["key"] == "FEDFUNDS:2026-05-01"
        assert record["error_type"] == "RuntimeError"
        assert record["error_message"] == "boom"
        assert record["context"] == {"ticker": "AAPL"}
        assert record["payload_b64"] is not None
        assert record["failed_at"].endswith("+00:00")

    def test_none_payload_allowed(self) -> None:
        fake = FakeProducer()
        DeadLetterQueue(producer=fake).send(
            "x", key=None, raw_value=None, error=ValueError("v")
        )
        record = json.loads(fake.messages[0]["value"])
        assert record["payload_b64"] is None

    def test_dlq_publish_failure_does_not_raise(self) -> None:
        class ExplodingProducer(FakeProducer):
            def produce(self, topic: str, value: bytes, key: bytes | None = None) -> None:
                raise BufferError("queue full")

        dlq = DeadLetterQueue(producer=ExplodingProducer())
        dlq.send("x", key="k", raw_value=b"v", error=ValueError("original"))


class TestKafkaAvroConsumer:
    """Consumer loop: happy path, poison messages, handler errors."""

    def _build(
        self, messages: list[FakeMessage], dlq_fake: FakeProducer
    ) -> tuple[KafkaAvroConsumer, FakeConsumer]:
        fake_consumer = FakeConsumer(messages)
        consumer = KafkaAvroConsumer(
            topic="filings.raw",
            schema_file=schema_path("filing"),
            group_id="test-group",
            consumer=fake_consumer,
            deserializer=_json_deserializer,
            dlq=DeadLetterQueue(producer=dlq_fake),
        )
        return consumer, fake_consumer

    def test_processes_and_commits_messages(self) -> None:
        messages = [
            FakeMessage(_value=json.dumps({"n": 1}).encode(), _key=b"k1"),
            FakeMessage(_value=json.dumps({"n": 2}).encode(), _key=b"k2"),
        ]
        dlq_fake = FakeProducer()
        consumer, fake = self._build(messages, dlq_fake)
        seen: list[dict[str, Any]] = []
        processed = consumer.consume(seen.append, stop_on_empty=True)
        assert processed == 2
        assert seen == [{"n": 1}, {"n": 2}]
        assert len(fake.committed) == 2
        assert fake.subscribed == ["filings.raw"]

    def test_max_messages_stops_early(self) -> None:
        messages = [
            FakeMessage(_value=json.dumps({"n": i}).encode()) for i in range(5)
        ]
        consumer, _ = self._build(messages, FakeProducer())
        assert consumer.consume(lambda _: None, max_messages=3) == 3

    def test_poison_message_dead_lettered_and_committed(self) -> None:
        messages = [
            FakeMessage(_value=b"not json", _key=b"bad"),
            FakeMessage(_value=json.dumps({"ok": True}).encode(), _key=b"good"),
        ]
        dlq_fake = FakeProducer()
        consumer, fake = self._build(messages, dlq_fake)
        processed = consumer.consume(lambda _: None, stop_on_empty=True)
        assert processed == 1
        assert len(dlq_fake.messages) == 1
        record = json.loads(dlq_fake.messages[0]["value"])
        assert record["context"]["stage"] == "deserialization"
        assert len(fake.committed) == 2  # poison message committed too

    def test_handler_failure_dead_lettered(self) -> None:
        messages = [FakeMessage(_value=json.dumps({"n": 1}).encode(), _key=b"k")]
        dlq_fake = FakeProducer()
        consumer, fake = self._build(messages, dlq_fake)

        def handler(record: dict[str, Any]) -> None:
            raise RuntimeError("handler exploded")

        processed = consumer.consume(handler, stop_on_empty=True)
        assert processed == 0
        record = json.loads(dlq_fake.messages[0]["value"])
        assert record["context"]["stage"] == "handler"
        assert record["error_message"] == "handler exploded"
        assert len(fake.committed) == 1

    def test_broker_error_message_skipped(self) -> None:
        messages = [FakeMessage(_value=None, _error="broker error")]
        dlq_fake = FakeProducer()
        consumer, fake = self._build(messages, dlq_fake)
        assert consumer.consume(lambda _: None, stop_on_empty=True) == 0
        assert dlq_fake.messages == []
        assert fake.committed == []

    def test_close_delegates(self) -> None:
        consumer, fake = self._build([], FakeProducer())
        consumer.close()
        assert fake.closed is True
