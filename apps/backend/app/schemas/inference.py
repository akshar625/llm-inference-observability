from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class InferenceEvent(BaseModel):
    request_id: str
    conversation_id: str

    provider: str
    model: str

    latency_ms: float
    first_token_latency_ms: Optional[float] = None

    input_tokens: int
    output_tokens: int

    estimated_cost: float

    status: str
    cancelled: bool
    streamed: bool

    prompt_preview: Optional[str] = None
    response_preview: Optional[str] = None

    created_at: datetime
