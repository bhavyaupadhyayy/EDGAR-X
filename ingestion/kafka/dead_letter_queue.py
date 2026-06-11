"""Dead letter queue for failed Kafka messages.

Any message that fails serialization, delivery, deserialization, or handler
processing is republished as JSON to ``<source_topic><suffix>`` (default
suffix ``.dlq``) with full error context so it can be replayed or inspected.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from core.config import get_settings
from core.logging import get_logger

logger = get_logger(__name__)


class ProducerLike(Protocol):
    """Minimal producer interface (subset of ``confluent_kafka.Producer``)."""

    def produce(self, topic: str, value: bytes, key: bytes | None = None) -> None:
        """Enqueue a message for delivery."""
        ...

    def poll(self, timeout: float) -> int:
        """Serve delivery callbacks."""
        ...

    def flush(self, timeout: float) -> int:
        """Block until all enqueued messages are delivered."""
        ...


def _default_producer(bootstrap_servers: str) -> ProducerLike:
    """Build a real confluent-kafka producer (deferred heavy import)."""
    from confluent_kafka import Producer  # noqa: PLC0415 - deferred: heavy optional import

    return Producer({"bootstrap.servers": bootstrap_servers})  # type: ignore[no-any-return]


class DeadLetterQueue:
    """Publishes failed messages to a per-topic dead letter topic."""

    def __init__(
        self,
        *,
        producer: ProducerLike | None = None,
        bootstrap_servers: str | None = None,
        topic_suffix: str = ".dlq",
    ) -> None:
        """Initialise the DLQ.

        Args:
            producer: Optional injected producer (used as-is; ideal for tests).
            bootstrap_servers: Kafka bootstrap servers for the default producer.
            topic_suffix: Suffix appended to the source topic name.
        """
        servers = bootstrap_servers or get_settings().kafka_bootstrap_servers
        self._producer = producer or _default_producer(servers)
        self._topic_suffix = topic_suffix

    def send(
        self,
        source_topic: str,
        *,
        key: str | None,
        raw_value: bytes | None,
        error: Exception,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        """Publish a failed message to the dead letter topic.

        Never raises: a DLQ publish failure is logged at error level so the
        original pipeline error is not masked.

        Args:
            source_topic: Topic the message was destined for / consumed from.
            key: Message key, if any.
            raw_value: Original message bytes (base64-encoded in the DLQ
                record); pass ``None`` when serialization failed pre-encode.
            error: The exception that routed this message here.
            context: Extra diagnostic fields (e.g. ticker, agent name).
        """
        dlq_topic = f"{source_topic}{self._topic_suffix}"
        record = {
            "source_topic": source_topic,
            "key": key,
            "payload_b64": base64.b64encode(raw_value).decode() if raw_value else None,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "failed_at": datetime.now(UTC).isoformat(),
            "context": dict(context or {}),
        }
        try:
            self._producer.produce(
                dlq_topic,
                value=json.dumps(record).encode("utf-8"),
                key=key.encode("utf-8") if key else None,
            )
            self._producer.poll(0)
        except (BufferError, OSError, ValueError) as dlq_error:
            logger.error(
                "dlq_publish_failed",
                dlq_topic=dlq_topic,
                original_error=str(error),
                dlq_error=str(dlq_error),
            )
            return
        logger.warning(
            "message_dead_lettered",
            dlq_topic=dlq_topic,
            key=key,
            error_type=record["error_type"],
            error_message=record["error_message"],
        )

    def flush(self, timeout: float = 10.0) -> None:
        """Flush any in-flight DLQ messages.

        Args:
            timeout: Maximum seconds to wait.
        """
        self._producer.flush(timeout)
