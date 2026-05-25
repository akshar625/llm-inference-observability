import re
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.stream_manager import stream_manager


_WINDOW_PATTERN = re.compile(r"^(\d+)([hmd])$")
_UNIT_MAP = {"h": "hours", "m": "minutes", "d": "days"}


def parse_window_to_interval(window: str) -> str:
    """Convert '24h' / '7d' / '15m' → PostgreSQL interval string."""
    m = _WINDOW_PATTERN.match(window)
    if not m:
        raise ValueError(f"Invalid window '{window}'. Use formats like '1h', '24h', '7d'.")
    return f"{m.group(1)} {_UNIT_MAP[m.group(2)]}"


class MetricsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def overview(self, window: str) -> dict:
        interval = parse_window_to_interval(window)
        result = await self.session.execute(
            text(f"""
                SELECT
                    COALESCE(SUM(request_count), 0)    AS total_requests,
                    COALESCE(SUM(error_count), 0)      AS total_errors,
                    COALESCE(SUM(cancelled_count), 0)  AS total_cancelled,
                    COALESCE(SUM(total_latency_ms), 0) AS total_latency_ms,
                    COALESCE(SUM(total_cost_usd), 0)   AS total_cost_usd,
                    COALESCE(SUM(total_tokens_in), 0)  AS total_tokens_in,
                    COALESCE(SUM(total_tokens_out), 0) AS total_tokens_out
                FROM aggregated_metrics
                WHERE hour_bucket > now() - interval '{interval}'
            """),
        )
        row = result.mappings().one()
        total = int(row["total_requests"])
        avg_latency = (row["total_latency_ms"] / total) if total > 0 else 0
        active_streams = len(await stream_manager.list_active())

        return {
            "window": window,
            "total_requests": total,
            "total_errors": int(row["total_errors"]),
            "total_cancelled": int(row["total_cancelled"]),
            "success_rate": round(1 - (row["total_errors"] + row["total_cancelled"]) / total, 4) if total else 0,
            "error_rate": round(row["total_errors"] / total, 4) if total else 0,
            "cancellation_rate": round(row["total_cancelled"] / total, 4) if total else 0,
            "avg_latency_ms": round(avg_latency, 2),
            "total_cost_usd": float(row["total_cost_usd"]),
            "total_tokens_in": int(row["total_tokens_in"]),
            "total_tokens_out": int(row["total_tokens_out"]),
            "active_streams": active_streams,
        }

    async def timeseries(self, window: str) -> dict:
        interval = parse_window_to_interval(window)
        result = await self.session.execute(
            text(f"""
                SELECT
                    hour_bucket,
                    SUM(request_count)   AS requests,
                    SUM(error_count)     AS errors,
                    SUM(cancelled_count) AS cancelled,
                    CASE WHEN SUM(request_count) > 0
                         THEN SUM(total_latency_ms)::float / SUM(request_count)
                         ELSE 0 END      AS avg_latency_ms,
                    SUM(total_cost_usd)  AS total_cost_usd,
                    SUM(total_tokens_out) AS tokens_out
                FROM aggregated_metrics
                WHERE hour_bucket > now() - interval '{interval}'
                GROUP BY hour_bucket
                ORDER BY hour_bucket ASC
            """),
        )
        buckets = [
            {
                "timestamp": row["hour_bucket"].isoformat(),
                "requests": int(row["requests"]),
                "errors": int(row["errors"]),
                "cancelled": int(row["cancelled"]),
                "avg_latency_ms": round(float(row["avg_latency_ms"]), 2),
                "total_cost_usd": float(row["total_cost_usd"]),
                "tokens_out": int(row["tokens_out"]),
            }
            for row in result.mappings().all()
        ]
        return {"window": window, "interval": "1h", "buckets": buckets}

    async def percentiles(self, window: str) -> dict:
        """Live percentiles from inference_logs.

        Percentiles aren't incrementally aggregatable, so this scans raw rows.
        Bounded window caps scan cost.
        """
        interval = parse_window_to_interval(window)
        result = await self.session.execute(
            text(f"""
                SELECT
                    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms) AS dur_p50,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS dur_p95,
                    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) AS dur_p99,
                    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY ttft_ms)
                        FILTER (WHERE ttft_ms IS NOT NULL) AS ttft_p50,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ttft_ms)
                        FILTER (WHERE ttft_ms IS NOT NULL) AS ttft_p95,
                    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY ttft_ms)
                        FILTER (WHERE ttft_ms IS NOT NULL) AS ttft_p99,
                    AVG(tokens_per_second) AS avg_tps,
                    COUNT(*) AS sample_size
                FROM inference_logs
                WHERE created_at > now() - interval '{interval}'
                  AND status = 'success'
                  AND duration_ms IS NOT NULL
            """),
        )
        row = result.mappings().one()

        def _round(v):
            return round(float(v), 2) if v is not None else None

        return {
            "window": window,
            "duration_ms": {
                "p50": _round(row["dur_p50"]),
                "p95": _round(row["dur_p95"]),
                "p99": _round(row["dur_p99"]),
            },
            "ttft_ms": {
                "p50": _round(row["ttft_p50"]),
                "p95": _round(row["ttft_p95"]),
                "p99": _round(row["ttft_p99"]),
            },
            "avg_tokens_per_second": _round(row["avg_tps"]),
            "sample_size": int(row["sample_size"]),
        }

    async def by_provider(self, window: str) -> dict:
        interval = parse_window_to_interval(window)
        result = await self.session.execute(
            text(f"""
                SELECT
                    provider, model,
                    SUM(request_count)   AS requests,
                    SUM(error_count)     AS errors,
                    SUM(cancelled_count) AS cancelled,
                    CASE WHEN SUM(request_count) > 0
                         THEN SUM(total_latency_ms)::float / SUM(request_count)
                         ELSE 0 END      AS avg_latency_ms,
                    SUM(total_cost_usd)  AS total_cost_usd,
                    SUM(total_tokens_in) AS tokens_in,
                    SUM(total_tokens_out) AS tokens_out
                FROM aggregated_metrics
                WHERE hour_bucket > now() - interval '{interval}'
                GROUP BY provider, model
                ORDER BY requests DESC
            """),
        )
        return {
            "window": window,
            "breakdown": [
                {
                    "provider": row["provider"],
                    "model": row["model"],
                    "requests": int(row["requests"]),
                    "errors": int(row["errors"]),
                    "cancelled": int(row["cancelled"]),
                    "error_rate": round(row["errors"] / row["requests"], 4) if row["requests"] else 0,
                    "avg_latency_ms": round(float(row["avg_latency_ms"]), 2),
                    "total_cost_usd": float(row["total_cost_usd"]),
                    "tokens_in": int(row["tokens_in"]),
                    "tokens_out": int(row["tokens_out"]),
                }
                for row in result.mappings().all()
            ],
        }
