from datetime import datetime
from typing import Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class LogEvent(BaseModel):
    """Canonical inference log payload.

    SDK emits this. Kafka transports it. Ingestor reads it. DB stores it.
    Same shape end-to-end — define once, use everywhere.
    """

    # Identity
    event_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    conversation_id: Optional[UUID] = None

    # Provider / Model
    provider: str
    model: str

    # Timing (epoch seconds; ms-derived fields below)
    started_at: float
    first_token_at: Optional[float] = None
    completed_at: Optional[float] = None

    # Derived
    duration_ms: Optional[int] = None
    ttft_ms: Optional[int] = None
    tokens_per_second: Optional[float] = None

    # Streaming
    streamed: bool = False
    stream_chunks: int = 0

    # Usage
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    estimated_cost_usd: Optional[float] = None  # populated at ingestion time

    # Status
    status: Literal["success", "error", "cancelled", "timeout"] = "success"
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    # Content previews (PII redaction happens at ingestion, not here)
    prompt_preview: str = ""
    response_preview: str = ""

    # Governance (Phase 8/9)
    blocked: bool = False
    block_reason: Optional[str] = None

    # Free-form
    metadata: dict = Field(default_factory=dict)

    def compute_derived(self) -> None:
        if self.completed_at and self.started_at:
            self.duration_ms = int((self.completed_at - self.started_at) * 1000)
        if self.first_token_at and self.started_at:
            self.ttft_ms = int((self.first_token_at - self.started_at) * 1000)
        if self.duration_ms and self.tokens_out and self.duration_ms > 0:
            self.tokens_per_second = round((self.tokens_out / self.duration_ms) * 1000, 2)
