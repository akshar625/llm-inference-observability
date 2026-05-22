from pydantic import BaseModel
from typing import Optional


class LatencyMetrics(BaseModel):
    provider: str
    avg_first_token_latency_ms: float
    avg_completion_latency_ms: float
    p95_latency_ms: float


class TokenMetrics(BaseModel):
    provider: str
    total_input_tokens: int
    total_output_tokens: int
    avg_tokens_per_request: float
    tokens_per_second: Optional[float] = None


class CostMetrics(BaseModel):
    provider: str
    total_cost: float
    avg_cost_per_request: float


class StreamMetrics(BaseModel):
    active_streams: int
    cancelled_streams: int
    avg_stream_duration_ms: float


class RequestMetrics(BaseModel):
    total_requests: int
    success_count: int
    failure_count: int
    cancelled_count: int
    success_rate: float
