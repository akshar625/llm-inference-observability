import asyncio
import json
import time
from typing import Optional
from uuid import UUID

from app.services.redis_client import redis_client

ACTIVE_STREAMS_KEY = "active_streams:{request_id}"
CANCELLATION_FLAGS_KEY = "cancellation_flags:{request_id}"
STREAM_TTL_SECONDS = 3600


class StreamManager:
    """
    In-flight stream registry + cancellation signaling.

    Two layers:
    - In-memory task map: request_id → asyncio.Task (fast local cancel)
    - Redis keyspaces:
        active_streams:{id}     → JSON metadata, TTL 1h (dashboard visibility)
        cancellation_flags:{id} → "1", TTL 1h (cancel signal for polling fallback)

    Cancellation flow (pub/sub pattern):
    - /cancel endpoint publishes request_id to Redis `cancellations` channel
    - Each replica's subscriber calls stream_manager.cancel() locally
    - The replica that owns the task cancels it; others no-op silently

    Failure mode: Redis errors never propagate to the chat path.
    If Redis is down, cancellation degrades gracefully — chat still works.
    """

    def __init__(self):
        self._tasks: dict[UUID, asyncio.Task] = {}

    def register_task(self, request_id: UUID, task: asyncio.Task) -> None:
        self._tasks[request_id] = task

    def cancel(self, request_id: UUID) -> bool:
        """Cancel local task. Returns True if this replica owned it."""
        task = self._tasks.pop(request_id, None)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def unregister_task(self, request_id: UUID) -> None:
        self._tasks.pop(request_id, None)

    async def register(
        self,
        request_id: UUID,
        provider: str,
        model: str,
        conversation_id: Optional[UUID] = None,
    ) -> None:
        try:
            await redis_client.set(
                ACTIVE_STREAMS_KEY.format(request_id=request_id),
                json.dumps({
                    "started_at": time.time(),
                    "provider": provider,
                    "model": model,
                    "conversation_id": str(conversation_id) if conversation_id else None,
                }),
                ex=STREAM_TTL_SECONDS,
            )
        except Exception:
            pass

    async def unregister(self, request_id: UUID) -> None:
        self.unregister_task(request_id)
        try:
            await redis_client.delete(
                ACTIVE_STREAMS_KEY.format(request_id=request_id),
                CANCELLATION_FLAGS_KEY.format(request_id=request_id),
            )
        except Exception:
            pass

    async def list_active(self) -> list[dict]:
        try:
            keys = await redis_client.keys("active_streams:*")
            if not keys:
                return []
            values = await redis_client.mget(keys)
            return [
                {**json.loads(v), "request_id": k.split(":", 1)[1]}
                for k, v in zip(keys, values)
                if v
            ]
        except Exception:
            return []


stream_manager = StreamManager()
