import asyncio
from typing import AsyncIterator

from app.providers.provider_factory import get_provider
from app.schemas.chat import ChatStreamRequest, StreamChunk
from app.services.stream_manager import stream_manager


class ChatService:
    async def stream_chat(self, req: ChatStreamRequest) -> AsyncIterator[str]:
        provider = get_provider(req.provider)

        await stream_manager.register(
            request_id=req.request_id,
            provider=req.provider,
            model=req.model,
            conversation_id=req.conversation_id,
        )

        # Register this coroutine's task so the subscriber can cancel it
        current_task = asyncio.current_task()
        if current_task:
            stream_manager.register_task(req.request_id, current_task)

        yield self._sse(StreamChunk(
            type="stream_start",
            metadata={
                "request_id": str(req.request_id),
                "provider": req.provider,
                "model": req.model,
            },
        ))

        try:
            async for chunk in provider.stream(
                messages=[m.model_dump() for m in req.messages],
                model=req.model,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
            ):
                yield self._sse(chunk)

        except asyncio.CancelledError:
            yield self._sse(StreamChunk(
                type="cancelled",
                metadata={"request_id": str(req.request_id), "reason": "user_requested"},
            ))
            raise
        except Exception as e:
            yield self._sse(StreamChunk(type="error", error=str(e)))
        finally:
            await stream_manager.unregister(req.request_id)

    def _sse(self, chunk: StreamChunk) -> str:
        return f"data: {chunk.model_dump_json()}\n\n"


chat_service = ChatService()
