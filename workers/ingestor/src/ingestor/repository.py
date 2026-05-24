import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import asyncpg

from shared import LogEvent


def _epoch_to_dt(epoch: Optional[float]) -> Optional[datetime]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


class InferenceLogRepository:
    """Inserts events into inference_logs. Idempotent on event_id —
    duplicate deliveries from Kafka are no-ops, not duplicate rows."""

    def __init__(self, conn: asyncpg.Connection):
        self.conn = conn

    async def insert(self, event: LogEvent) -> None:
        await self.conn.execute(
            """
            INSERT INTO inference_logs (
                id,
                event_id, request_id, conversation_id, provider, model,
                started_at, first_token_at, completed_at,
                duration_ms, ttft_ms, tokens_per_second,
                streamed, stream_chunks,
                tokens_in, tokens_out, estimated_cost_usd,
                status, error_code, error_message,
                prompt_preview, response_preview,
                pii_detected, blocked, block_reason, metadata
            ) VALUES (
                $1,
                $2, $3, $4, $5, $6,
                $7, $8, $9,
                $10, $11, $12,
                $13, $14,
                $15, $16, $17,
                $18, $19, $20,
                $21, $22,
                $23, $24, $25, $26::jsonb
            )
            ON CONFLICT (event_id) DO NOTHING
            """,
            uuid4(),
            event.event_id,
            event.request_id,
            event.conversation_id,
            event.provider,
            event.model,
            _epoch_to_dt(event.started_at),
            _epoch_to_dt(event.first_token_at),
            _epoch_to_dt(event.completed_at),
            event.duration_ms,
            event.ttft_ms,
            float(event.tokens_per_second) if event.tokens_per_second is not None else None,
            event.streamed,
            event.stream_chunks,
            event.tokens_in,
            event.tokens_out,
            float(event.estimated_cost_usd) if event.estimated_cost_usd is not None else None,
            event.status,
            event.error_code,
            event.error_message,
            event.prompt_preview,
            event.response_preview,
            bool(event.metadata.get("pii_detected", False)),
            event.blocked,
            event.block_reason,
            json.dumps(event.metadata, default=str),
        )


class AggregatedMetricsRepository:
    """Incremental hour-bucketed aggregation. One UPSERT per event.

    Sums (latency, tokens, cost) and counters are incrementally combinable.
    Percentiles are computed live from inference_logs in the dashboard query.
    """

    def __init__(self, conn: asyncpg.Connection):
        self.conn = conn

    async def upsert(self, event: LogEvent) -> None:
        if event.completed_at is None:
            return

        hour_bucket = _epoch_to_dt(event.completed_at).replace(
            minute=0, second=0, microsecond=0
        )
        error_delta = 1 if event.status == "error" else 0
        cancelled_delta = 1 if event.status == "cancelled" else 0

        await self.conn.execute(
            """
            INSERT INTO aggregated_metrics (
                hour_bucket, provider, model,
                request_count, total_latency_ms,
                error_count, cancelled_count,
                total_tokens_in, total_tokens_out, total_cost_usd
            ) VALUES (
                $1, $2, $3,
                1, $4,
                $5, $6,
                $7, $8, $9
            )
            ON CONFLICT (hour_bucket, provider, model) DO UPDATE SET
                request_count    = aggregated_metrics.request_count + EXCLUDED.request_count,
                total_latency_ms = aggregated_metrics.total_latency_ms + EXCLUDED.total_latency_ms,
                error_count      = aggregated_metrics.error_count + EXCLUDED.error_count,
                cancelled_count  = aggregated_metrics.cancelled_count + EXCLUDED.cancelled_count,
                total_tokens_in  = aggregated_metrics.total_tokens_in + EXCLUDED.total_tokens_in,
                total_tokens_out = aggregated_metrics.total_tokens_out + EXCLUDED.total_tokens_out,
                total_cost_usd   = aggregated_metrics.total_cost_usd + EXCLUDED.total_cost_usd
            """,
            hour_bucket,
            event.provider,
            event.model,
            event.duration_ms or 0,
            error_delta,
            cancelled_delta,
            event.tokens_in or 0,
            event.tokens_out or 0,
            float(event.estimated_cost_usd or 0),
        )
