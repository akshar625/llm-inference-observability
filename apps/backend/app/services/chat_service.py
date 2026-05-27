import asyncio
import logging
import time
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session_maker
from app.providers.provider_factory import get_provider, log_sink
from app.schemas.chat import ChatStreamRequest, StreamChunk
from app.services.conversation_service import ConversationService
from app.services.governance import GovernanceService, GovernanceViolation
from app.services.stream_manager import stream_manager
from shared import LogEvent

logger = logging.getLogger(__name__)


class ChatService:
    async def stream_chat(self, req: ChatStreamRequest, session: AsyncSession) -> AsyncIterator[str]:
        provider = get_provider(req.provider)
        conv_service = ConversationService(session)

        conversation_id = await conv_service.ensure_conversation(req.conversation_id)
        llm_messages = await conv_service.build_llm_messages(conversation_id, req.content)
        await session.commit()  # persist user message before stream; survives any cancel path

        try:
            await GovernanceService.check(llm_messages, conversation_id)
        except GovernanceViolation as e:
            now = time.time()
            blocked_event = LogEvent(
                request_id=req.request_id,
                conversation_id=conversation_id,
                provider=req.provider,
                model=req.model,
                started_at=now,
                completed_at=now,
                status="error",
                streamed=False,
                blocked=True,
                block_reason=e.reason,
                prompt_preview=req.content[:200],
                error_message=e.message,
            )
            blocked_event.compute_derived()
            await session.commit()  # ensure conversation row exists before ingestor FK insert
            await log_sink.emit(blocked_event)
            yield self._sse(StreamChunk(type="error", error=e.message))
            return

        await stream_manager.register(
            request_id=req.request_id,
            provider=req.provider,
            model=req.model,
            conversation_id=conversation_id,
        )

        current_task = asyncio.current_task()
        if current_task:
            stream_manager.register_task(req.request_id, current_task)

        started_at = time.time()  # used as created_at for the assistant message (preserves ordering)
        assistant_buffer = ""

        async def _finalize(interrupted: bool, buf: str) -> None:
            logger.info(
                "_finalize: conv=%s buf_len=%d interrupted=%s",
                conversation_id, len(buf), interrupted,
            )
            async with async_session_maker() as s:
                try:
                    if buf or interrupted:
                        svc = ConversationService(s)
                        await svc.persist_assistant_message(
                            conversation_id,
                            buf,
                            status="interrupted" if interrupted else "completed",
                            started_at=started_at,
                        )
                    await s.commit()
                    logger.info("_finalize: commit OK for conv=%s", conversation_id)
                except Exception as exc:
                    logger.error("_finalize: persist failed: %s", exc)
                    try:
                        await s.rollback()
                    except Exception:
                        pass

        try:
            yield self._sse(StreamChunk(
                type="stream_start",
                metadata={
                    "request_id": str(req.request_id),
                    "conversation_id": str(conversation_id),
                    "provider": req.provider,
                    "model": req.model,
                },
            ))

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

            asyncio.ensure_future(_finalize(False, assistant_buffer))

        except asyncio.CancelledError:
            asyncio.ensure_future(_finalize(True, assistant_buffer))
            yield self._sse(StreamChunk(
                type="cancelled",
                metadata={"request_id": str(req.request_id)},
            ))
        except Exception as e:
            yield self._sse(StreamChunk(type="error", error=str(e)))
        finally:
            await stream_manager.unregister(req.request_id)

    def _sse(self, chunk: StreamChunk) -> str:
        return f"data: {chunk.model_dump_json()}\n\n"


chat_service = ChatService()
