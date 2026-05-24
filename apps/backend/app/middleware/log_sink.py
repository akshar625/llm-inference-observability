import asyncio
import json
import logging
from typing import Protocol

from shared import LogEvent

logger = logging.getLogger(__name__)


class LogSink(Protocol):
    async def emit(self, event: LogEvent) -> None: ...


class ConsoleSink:
    """Pretty-prints events to stdout."""
    async def emit(self, event: LogEvent) -> None:
        print(f"[LOG] {event.model_dump(mode='json')}")


class InMemorySink:
    """Ring buffer of recent events. Used by /debug/logs/recent and tests."""
    def __init__(self, max_events: int = 200):
        self.events: list[LogEvent] = []
        self.max_events = max_events

    async def emit(self, event: LogEvent) -> None:
        self.events.append(event)
        if len(self.events) > self.max_events:
            self.events.pop(0)


class CompositeSink:
    """Fans out one event to multiple sinks. Per-sink failures don't affect others."""
    def __init__(self, *sinks: LogSink):
        self.sinks = sinks

    async def emit(self, event: LogEvent) -> None:
        for sink in self.sinks:
            try:
                await sink.emit(event)
            except Exception as e:
                print(f"[LogSink:{sink.__class__.__name__}] emit failed: {e}")


class KafkaSink:
    """Async Kafka producer for LogEvents.

    Lazy-initializes the producer on first emit so app startup doesn't fail
    if Kafka is briefly unavailable. Emit failures are caught and logged —
    never propagated to the chat path. The chatbot stays up if Kafka is down.
    """

    def __init__(self, bootstrap_servers: str, topic: str = "inference-events"):
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._producer = None
        self._init_lock = asyncio.Lock()

    async def _ensure_producer(self):
        if self._producer:
            return self._producer
        async with self._init_lock:
            if self._producer:
                return self._producer
            try:
                from aiokafka import AIOKafkaProducer
                producer = AIOKafkaProducer(
                    bootstrap_servers=self._bootstrap_servers,
                    value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
                    acks=1,
                    enable_idempotence=False,
                )
                await producer.start()
                self._producer = producer
                logger.info("KafkaSink connected to %s topic=%s", self._bootstrap_servers, self._topic)
                return self._producer
            except Exception as e:
                logger.error("KafkaSink failed to connect: %s", e)
                return None

    async def emit(self, event: LogEvent) -> None:
        producer = await self._ensure_producer()
        if producer is None:
            return  # fail-open: Kafka down → chat unaffected
        try:
            await producer.send_and_wait(
                self._topic,
                value=event.model_dump(mode="json"),
                key=str(event.event_id).encode("utf-8"),
            )
        except Exception as e:
            logger.error("KafkaSink emit failed for %s: %s", event.event_id, e)

    async def close(self) -> None:
        if self._producer is not None:
            try:
                await self._producer.stop()
            finally:
                self._producer = None
