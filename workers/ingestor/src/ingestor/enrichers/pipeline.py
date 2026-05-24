from typing import Protocol
from shared import LogEvent


class Enricher(Protocol):
    async def enrich(self, event: LogEvent) -> LogEvent: ...


class EnricherPipeline:
    """Chain of Responsibility: each enricher transforms the event in turn."""

    def __init__(self, enrichers: list[Enricher]):
        self.enrichers = enrichers

    async def process(self, event: LogEvent) -> LogEvent:
        for enricher in self.enrichers:
            event = await enricher.enrich(event)
        return event
