import asyncio
import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.provider_factory import get_provider
from app.schemas.chat import ChatStreamRequest, StreamChunk
from app.services.conversation_service import ConversationService
from app.services.stream_manager import stream_manager

logger = logging.getLogger(__name__)


class ChatService:
    async def stream_chat(self, req: ChatStreamRequest, session: AsyncSession) -> AsyncIterator[str]:
        provider = get_provider(req.provider)
        conv_service = ConversationService(session)

        conversation_id = await conv_service.ensure_conversation(req.conversation_id)
        llm_messages = await conv_service.build_llm_messages(conversation_id, req.content)

        await stream_manager.register(
            request_id=req.request_id,
            provider=req.provider,
            model=req.model,
            conversation_id=conversation_id,
        )

        current_task = asyncio.current_task()
        if current_task:
            stream_manager.register_task(req.request_id, current_task)

        yield self._sse(StreamChunk(
            type="stream_start",
            metadata={
                "request_id": str(req.request_id),
                "conversation_id": str(conversation_id),
                "provider": req.provider,
                "model": req.model,
            },
        ))

        assistant_buffer = ""
        try:
            async for chunk in provider.stream(
                messages=llm_messages,
                model=req.model,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
                log_context={"request_id": req.request_id, "conversation_id": conversation_id},
            ):
                if chunk.type == "token" and chunk.content:
                    assistant_buffer += chunk.content
                yield self._sse(chunk)

        except asyncio.CancelledError:
            yield self._sse(StreamChunk(
                type="cancelled",
                metadata={"request_id": str(req.request_id)},
            ))
        except Exception as e:
            yield self._sse(StreamChunk(type="error", error=str(e)))
        finally:
            try:
                if assistant_buffer:
                    await conv_service.persist_assistant_message(conversation_id, assistant_buffer)
                await session.commit()
            except Exception as e:
                logger.error("Failed to persist conversation state: %s", e)
                try:
                    await session.rollback()
                except Exception:
                    pass
            await stream_manager.unregister(req.request_id)

    def _sse(self, chunk: StreamChunk) -> str:
        return f"data: {chunk.model_dump_json()}\n\n"


chat_service = ChatService()
