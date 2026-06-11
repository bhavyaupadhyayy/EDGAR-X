"""Avro-deserialising Kafka consumer with dead letter routing.

Messages that fail deserialization or handler processing are sent to the
dead letter queue and the offset is committed, so a single poison message
never blocks the partition. The underlying consumer and deserializer are
injectable so unit tests run without a broker.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from core.config import get_settings
from core.logging import get_logger
from ingestion.kafka.dead_letter_queue import DeadLetterQueue
from ingestion.kafka.producer import MessageContext

logger = get_logger(__name__)

DeserializerFn = Callable[[bytes | None, MessageContext], dict[str, Any] | None]
HandlerFn = Callable[[dict[str, Any]], None]


class MessageLike(Protocol):
    """Minimal message interface (subset of ``confluent_kafka.Message``)."""

    def error(self) -> object | None:
        """Return the message-level error, if any."""
        ...

    def key(self) -> bytes | None:
        """Return the message key bytes."""
        ...

    def value(self) -> bytes | None:
        """Return the message value bytes."""
        ...


class ConsumerLike(Protocol):
    """Minimal consumer interface (subset of ``confluent_kafka.Consumer``)."""

    def subscribe(self, topics: list[str]) -> None:
        """Subscribe to topics."""
        ...

    def poll(self, timeout: float) -> MessageLike | None:
        """Poll for the next message."""
        ...

    def commit(self, message: MessageLike) -> object:
        """Commit the offset of a processed message."""
        ...

    def close(self) -> None:
        """Close the consumer."""
        ...


def _default_consumer(bootstrap_servers: str, group_id: str) -> ConsumerLike:
    """Build a real confluent-kafka consumer (deferred heavy import)."""
    from confluent_kafka import Consumer  # noqa: PLC0415 - deferred: heavy optional import

    return Consumer(  # type: ignore[no-any-return]
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )


def _default_deserializer(schema_file: Path, schema_registry_url: str) -> DeserializerFn:
    """Build a real Schema Registry AvroDeserializer (deferred heavy import)."""
    from confluent_kafka.schema_registry import (  # noqa: PLC0415 - deferred import
        SchemaRegistryClient,
    )
    from confluent_kafka.schema_registry.avro import AvroDeserializer  # noqa: PLC0415

    registry = SchemaRegistryClient({"url": schema_registry_url})
    return AvroDeserializer(registry, schema_file.read_text())  # type: ignore[no-any-return]


class KafkaAvroConsumer:
    """Consumes Avro-encoded records from one topic, dead-lettering failures."""

    def __init__(
        self,
        topic: str,
        schema_file: Path,
        group_id: str,
        *,
        bootstrap_servers: str | None = None,
        schema_registry_url: str | None = None,
        consumer: ConsumerLike | None = None,
        deserializer: DeserializerFn | None = None,
        dlq: DeadLetterQueue | None = None,
    ) -> None:
        """Initialise the consumer and subscribe to the topic.

        Args:
            topic: Source topic name.
            schema_file: Path to the ``.avsc`` value schema.
            group_id: Kafka consumer group id.
            bootstrap_servers: Kafka bootstrap servers; falls back to settings.
            schema_registry_url: Schema Registry URL; falls back to settings.
            consumer: Optional injected consumer (tests / custom config).
            deserializer: Optional injected value deserializer.
            dlq: Optional dead letter queue used for poison messages.
        """
        settings = get_settings()
        servers = bootstrap_servers or settings.kafka_bootstrap_servers
        registry_url = schema_registry_url or settings.schema_registry_url
        self._topic = topic
        self._consumer = consumer or _default_consumer(servers, group_id)
        self._deserializer = deserializer or _default_deserializer(schema_file, registry_url)
        self._dlq = dlq or DeadLetterQueue(bootstrap_servers=servers)
        self._consumer.subscribe([topic])

    def consume(
        self,
        handler: HandlerFn,
        *,
        max_messages: int | None = None,
        poll_timeout: float = 1.0,
        stop_on_empty: bool = False,
    ) -> int:
        """Poll and process messages until stopped.

        Each successfully handled message is committed. Deserialization and
        handler failures are dead-lettered and committed so the partition
        keeps moving.

        Args:
            handler: Callback invoked with each decoded record dict.
            max_messages: Stop after successfully handling this many records
                (``None`` = run until interrupted / empty).
            poll_timeout: Seconds to block per poll.
            stop_on_empty: Return when a poll yields no message (useful for
                batch jobs and tests).

        Returns:
            The number of records successfully handled.
        """
        processed = 0
        while max_messages is None or processed < max_messages:
            message = self._consumer.poll(poll_timeout)
            if message is None:
                if stop_on_empty:
                    break
                continue
            if message.error() is not None:
                logger.error(
                    "consumer_message_error", topic=self._topic, error=str(message.error())
                )
                continue
            key_bytes = message.key()
            key = key_bytes.decode("utf-8", errors="replace") if key_bytes else None
            try:
                record = self._deserializer(message.value(), MessageContext(topic=self._topic))
            except (ValueError, TypeError, KeyError) as exc:
                self._dlq.send(
                    self._topic,
                    key=key,
                    raw_value=message.value(),
                    error=exc,
                    context={"stage": "deserialization"},
                )
                self._consumer.commit(message)
                continue
            if record is None:
                self._consumer.commit(message)
                continue
            try:
                handler(record)
            except Exception as exc:  # noqa: BLE001 - handler errors must not kill the loop
                logger.error(
                    "handler_failed", topic=self._topic, key=key, error=str(exc), exc_info=True
                )
                self._dlq.send(
                    self._topic,
                    key=key,
                    raw_value=message.value(),
                    error=exc,
                    context={"stage": "handler"},
                )
                self._consumer.commit(message)
                continue
            self._consumer.commit(message)
            processed += 1
        logger.info("consumer_batch_complete", topic=self._topic, processed=processed)
        return processed

    def close(self) -> None:
        """Close the underlying consumer."""
        self._consumer.close()
