import re
from shared import LogEvent

PII_PATTERNS = {
    "EMAIL":   re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "PHONE":   re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?\(?\d{3,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}\b"),
    "CARD":    re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "AADHAAR": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "SSN":     re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
}


def _redact(text: str) -> tuple[str, bool]:
    redacted = text
    found = False
    for label, pattern in PII_PATTERNS.items():
        if pattern.search(redacted):
            found = True
            redacted = pattern.sub(f"<{label}_REDACTED>", redacted)
    return redacted, found


class PIIRedactorEnricher:
    """Regex-based PII redaction on prompt_preview and response_preview.
    Production swap: replace with Microsoft Presidio behind the same interface."""

    async def enrich(self, event: LogEvent) -> LogEvent:
        pii_detected = False

        if event.prompt_preview:
            event.prompt_preview, found = _redact(event.prompt_preview)
            pii_detected = pii_detected or found

        if event.response_preview:
            event.response_preview, found = _redact(event.response_preview)
            pii_detected = pii_detected or found

        if pii_detected:
            event.metadata = {**event.metadata, "pii_detected": True}

        return event
