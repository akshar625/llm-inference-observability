from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/recent")
async def recent_logs(
    limit: int = Query(50, ge=1, le=500),
    status_filter: str | None = Query(None, alias="status"),
    provider: str | None = None,
    conversation_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    where_clauses = []
    params: dict = {"limit": limit}
    if status_filter:
        where_clauses.append("status = :status")
        params["status"] = status_filter
    if provider:
        where_clauses.append("provider = :provider")
        params["provider"] = provider
    if conversation_id:
        where_clauses.append("conversation_id = :conv_id")
        params["conv_id"] = conversation_id
    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    result = await session.execute(
        text(f"""
            SELECT
                event_id, request_id, conversation_id,
                provider, model,
                started_at, first_token_at, completed_at,
                duration_ms, ttft_ms, tokens_per_second,
                streamed, stream_chunks,
                tokens_in, tokens_out, estimated_cost_usd,
                status, error_code, error_message,
                prompt_preview, response_preview,
                pii_detected, blocked, block_reason,
                created_at
            FROM inference_logs
            {where}
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        params,
    )

    def _serialize(row: dict) -> dict:
        out = {}
        for k, v in row.items():
            if v is None:
                out[k] = None
            elif hasattr(v, "isoformat"):
                out[k] = v.isoformat()
            elif hasattr(v, "hex"):  # UUID
                out[k] = str(v)
            else:
                out[k] = float(v) if k in {"tokens_per_second", "estimated_cost_usd"} and v is not None else v
        return out

    rows = [_serialize(dict(r)) for r in result.mappings().all()]
    return {"count": len(rows), "events": rows}
