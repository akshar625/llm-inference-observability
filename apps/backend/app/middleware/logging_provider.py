import asyncio
import time
from typing import AsyncIterator
from uuid import uuid4

from app.middleware.log_sink import LogSink
from app.schemas.chat import StreamChunk
from shared import LogEvent


class LoggingProvider:
    """Decorator that wraps any LLM provider and emits a LogEvent per call.

    Every chunk flows through unchanged; the event is built up across the stream
    and emitted in the finally block — so cancellations and errors log just like
    successful calls. Sink failures never affect the chat response.
    """

    def __init__(self, inner, sink: LogSink):
        self.inner = inner
        self.sink = sink

    @property
    def provider_name(self) -> str:
        return self.inner.provider_name

    async def generate(self, messages: list[dict], model: str, **opts) -> dict:
        event = self._init_event(messages, model, streamed=False, **opts)
        inner_opts = {k: v for k, v in opts.items() if k != "log_context"}
        try:
            resp = await self.inner.generate(messages, model, **inner_opts)
            event.completed_at = time.time()
            event.status = "success"
            if isinstance(resp, dict):
                content = resp.get("content", "")
                event.response_preview = str(content)[:200]
                event.tokens_in = resp.get("input_tokens")
                event.tokens_out = resp.get("output_tokens")
            return resp
        except Exception as e:
            event.completed_at = time.time()
            event.status = "error"
            event.error_message = str(e)
            raise
        finally:
            event.compute_derived()
            await self.sink.emit(event)

    async def stream(self, messages: list[dict], model: str, **opts) -> AsyncIterator[StreamChunk]:
        event = self._init_event(messages, model, streamed=True, **opts)
        inner_opts = {k: v for k, v in opts.items() if k != "log_context"}
        response_buffer = ""

        try:
            async for chunk in self.inner.stream(messages, model, **inner_opts):
                if chunk.type == "token":
                    if event.first_token_at is None:
                        event.first_token_at = time.time()
                    if chunk.content:
                        if len(response_buffer) < 200:
                            response_buffer += chunk.content
                        event.stream_chunks += 1

                if chunk.type == "metadata" and chunk.metadata:
                    if "input_tokens" in chunk.metadata:
                        event.tokens_in = chunk.metadata["input_tokens"]
                    if "output_tokens" in chunk.metadata:
                        event.tokens_out = chunk.metadata["output_tokens"]

                yield chunk

            event.completed_at = time.time()
            event.status = "success"

        except asyncio.CancelledError:
            event.completed_at = time.time()
            event.status = "cancelled"
            raise
        except Exception as e:
            event.completed_at = time.time()
            event.status = "error"
            event.error_message = str(e)
            raise
        finally:
            event.response_preview = response_buffer[:200]
            event.compute_derived()
            await self.sink.emit(event)

    def _init_event(self, messages: list[dict], model: str, streamed: bool, **opts) -> LogEvent:
        log_context = opts.get("log_context") or {}
        last_user_msg = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        return LogEvent(
            request_id=log_context.get("request_id") or uuid4(),
            conversation_id=log_context.get("conversation_id"),
            provider=self.inner.provider_name,
            model=model,
            started_at=time.time(),
            streamed=streamed,
            prompt_preview=str(last_user_msg)[:200],
        )
