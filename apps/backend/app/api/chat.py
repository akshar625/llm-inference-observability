from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.chat import ChatStreamRequest
from app.services.chat_service import chat_service
from app.services.stream_manager import stream_manager
from app.services.redis_client import redis_client
from app.services.cancellation_subscriber import CANCELLATION_CHANNEL

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/stream")
async def stream_chat(req: ChatStreamRequest):
    return StreamingResponse(
        chat_service.stream_chat(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/cancel/{request_id}")
async def cancel_stream(request_id: UUID):
    """
    Broadcast cancellation to all backend replicas via Redis pub/sub.
    The replica owning the task cancels it; all others no-op silently.
    Falls back to local-only cancel if Redis is unreachable.
    """
    try:
        receivers = await redis_client.publish(CANCELLATION_CHANNEL, str(request_id))
        return {
            "status": "cancellation_requested",
            "scope": "broadcast",
            "replicas_notified": receivers,
        }
    except Exception:
        cancelled = stream_manager.cancel(request_id)
        if cancelled:
            return {"status": "cancellation_requested", "scope": "local_fallback"}
        raise HTTPException(503, "Cancellation unavailable: Redis down and stream not local")


@router.get("/active")
async def list_active_streams():
    return {"active_streams": await stream_manager.list_active()}
