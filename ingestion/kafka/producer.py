"""Avro-serialising Kafka producer with Schema Registry integration.

Serialization failures and broker delivery failures are routed to the
dead letter queue instead of crashing the pipeline. The underlying producer
and serializer are injectable so unit tests run without a broker.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.config import get_settings
from core.logging import get_logger
from ingestion.kafka.dead_letter_queue import DeadLetterQueue, ProducerLike

logger = get_logger(__name__)

#: Directory containing the canonical .avsc schema files.
SCHEMA_DIR = Path(__file__).parent / "schemas"

#: Canonical topic names per stream.
TOPICS: dict[str, str] = {
    "filing": "filings.raw",
    "transcript": "transcripts.raw",
    "macro": "macro.raw",
    "options": "options.unusual_activity",
    "sentiment": "sentiment.raw",
}


def schema_path(name: str) -> Path:
    """Return the path of a named Avro schema.

    Args:
        name: Schema stem, e.g. ``"filing"``.

    Raises:
        FileNotFoundError: If no such schema file exists.
    """
    path = SCHEMA_DIR / f"{name}.avsc"
    if not path.exists():
        raise FileNotFoundError(f"no Avro schema named {name!r} in {SCHEMA_DIR}")
    return path


@dataclass(frozen=True)
class MessageContext:
    """Duck-typed stand-in for ``confluent_kafka.serialization.SerializationContext``.

    Carries the attributes Avro serializers/deserializers actually read
    (``topic``, ``field``, ``headers``), without requiring confluent-kafka
    at import time.
    """

    topic: str
    field: str = "value"
    headers: Any = None


SerializerFn = Callable[[dict[str, Any], MessageContext], bytes | None]


def _default_serializer(schema_file: Path, schema_registry_url: str) -> SerializerFn:
    """Build a real Schema Registry AvroSerializer (deferred heavy import)."""
    from confluent_kafka.schema_registry import (  # noqa: PLC0415 - deferred import
        SchemaRegistryClient,
    )
    from confluent_kafka.schema_registry.avro import AvroSerializer  # noqa: PLC0415

    registry = SchemaRegistryClient({"url": schema_registry_url})
    return AvroSerializer(registry, schema_file.read_text())  # type: ignore[no-any-return]


def _default_producer(bootstrap_servers: str) -> ProducerLike:
    """Build a real confluent-kafka producer (deferred heavy import)."""
    from confluent_kafka import Producer  # noqa: PLC0415 - deferred: heavy optional import

    return Producer(  # type: ignore[no-any-return]
        {
            "bootstrap.servers": bootstrap_servers,
            "enable.idempotence": True,
            "acks": "all",
        }
    )


class KafkaAvroProducer:
    """Produces Avro-encoded records to one topic, dead-lettering failures."""

    def __init__(
        self,
        topic: str,
        schema_file: Path,
        *,
        bootstrap_servers: str | None = None,
        schema_registry_url: str | None = None,
        producer: ProducerLike | None = None,
        serializer: SerializerFn | None = None,
        dlq: DeadLetterQueue | None = None,
    ) -> None:
        """Initialise the producer.

        Args:
            topic: Destination topic name.
            schema_file: Path to the ``.avsc`` value schema.
            bootstrap_servers: Kafka bootstrap servers; falls back to settings.
            schema_registry_url: Schema Registry URL; falls back to settings.
            producer: Optional injected producer (tests / custom config).
            serializer: Optional injected value serializer.
            dlq: Optional dead letter queue; one is built lazily on first
                failure when omitted and a real producer is in use.
        """
        settings = get_settings()
        servers = bootstrap_servers or settings.kafka_bootstrap_servers
        registry_url = schema_registry_url or settings.schema_registry_url
        self._topic = topic
        self._producer = producer or _default_producer(servers)
        self._serializer = serializer or _default_serializer(schema_file, registry_url)
        self._dlq = dlq or DeadLetterQueue(producer=self._producer)

    @property
    def topic(self) -> str:
        """The destination topic name."""
        return self._topic

    def produce(self, value: Mapping[str, Any], key: str) -> bool:
        """Serialize and enqueue one record.

        Args:
            value: Record dict conforming to the topic's Avro schema.
            key: Message key (UTF-8 encoded).

        Returns:
            True if the record was enqueued; False if it was dead-lettered.
        """
        context = MessageContext(topic=self._topic)
        try:
            payload = self._serializer(dict(value), context)
        except (ValueError, TypeError, KeyError) as exc:
            logger.error("avro_serialization_failed", topic=self._topic, key=key, error=str(exc))
            self._dlq.send(
                self._topic,
                key=key,
                raw_value=None,
                error=exc,
                context={"stage": "serialization"},
            )
            return False
        try:
            self._producer.produce(self._topic, value=payload or b"", key=key.encode("utf-8"))
            self._producer.poll(0)
        except BufferError as exc:
            logger.warning("producer_queue_full_flushing", topic=self._topic, key=key)
            self._producer.flush(10.0)
            try:
                self._producer.produce(self._topic, value=payload or b"", key=key.encode("utf-8"))
            except (BufferError, OSError) as retry_exc:
                self._dlq.send(
                    self._topic,
                    key=key,
                    raw_value=payload,
                    error=retry_exc,
                    context={"stage": "delivery", "first_error": str(exc)},
                )
                return False
        return True

    def flush(self, timeout: float = 30.0) -> None:
        """Block until all enqueued records are delivered.

        Args:
            timeout: Maximum seconds to wait.
        """
        self._producer.flush(timeout)


def producer_for_stream(stream: str) -> KafkaAvroProducer:
    """Build the canonical producer for a named stream.

    Args:
        stream: One of :data:`TOPICS` keys (``filing``, ``transcript``,
            ``macro``, ``options``, ``sentiment``).

    Raises:
        KeyError: If the stream name is unknown.
    """
    topic = TOPICS[stream]
    return KafkaAvroProducer(topic=topic, schema_file=schema_path(stream))
