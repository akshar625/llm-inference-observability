from typing import Protocol
from app.schemas.log_event import LogEvent


class LogSink(Protocol):
    async def emit(self, event: LogEvent) -> None: ...


class ConsoleSink:
    """Pretty-prints events to stdout. Phase 6 default; Phase 7 swaps for KafkaSink."""
    async def emit(self, event: LogEvent) -> None:
        import json
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
