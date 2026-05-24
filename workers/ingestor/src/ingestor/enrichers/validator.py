from shared import LogEvent


class ValidatorEnricher:
    """Schema validation already happens at LogEvent.model_validate.
    Reserved for future business-rule validation (required fields, value ranges)."""

    async def enrich(self, event: LogEvent) -> LogEvent:
        return event
