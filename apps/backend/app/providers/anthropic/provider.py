import json
from typing import AsyncGenerator, Optional
from app.config.constants import Constants, HttpMethods
from app.providers.http_client import BaseLLMProvider
from app.schemas.chat import StreamChunk


class AnthropicProvider(BaseLLMProvider):

    MODELS = {
        "claude-haiku-4-5-20251001": {"max_tokens_default": 1024, "supports_streaming": True, "context_window": 200_000},
        "claude-sonnet-4-6":         {"max_tokens_default": 1024, "supports_streaming": True, "context_window": 200_000},
        "claude-opus-4-7":           {"max_tokens_default": 1024, "supports_streaming": True, "context_window": 200_000},
    }

    def __init__(self, api_key: str, timeout: int = 30, anthropic_version: str = "2023-06-01"):
        self.base_url = "https://api.anthropic.com/v1"
        self.headers = {
            "x-api-key": api_key,
            "anthropic-version": anthropic_version,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.timeout = min(max(int(timeout), 15), 120)

    async def ping(self) -> dict:
        url = f"{self.base_url}/models"
        return await self.test_connection(url=url, headers=self.headers, timeout=self.timeout)

    async def generate(self, messages: list, model: str, temperature: float = 0.7, max_tokens: int = 1024) -> dict:
        url = f"{self.base_url}/messages"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        response = await self.request_handler(
            method=HttpMethods.POST.value,
            url=url,
            payload_json=payload,
            headers=self.headers,
            timeout=self.timeout,
            retry_count=3,
            retry_wait=5
        )

        if response[Constants.ACTION_STATUS] == Constants.SUCCESS:
            raw = response[Constants.ACTION_RESULT][Constants.RESPONSE]
            content = raw["content"][0]["text"]
            usage = raw.get("usage", {})
            response[Constants.ACTION_RESULT][Constants.RESPONSE] = {
                "content": content,
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "model": raw.get("model", model)
            }

        return response

    async def stream(self, messages: list, model: str, temperature: float = 0.7, max_tokens: int = 1024) -> AsyncGenerator[StreamChunk, None]:
        url = f"{self.base_url}/messages"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True
        }

        async for line in self.make_stream_request(url=url, payload_json=payload, headers=self.headers, timeout=self.timeout):
            if line.startswith("data: "):
                chunk = self._normalize_chunk(line[len("data: "):])
                if chunk:
                    yield chunk

    def _normalize_chunk(self, raw_line: str) -> Optional[StreamChunk]:
        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, TypeError):
            return None

        event_type = data.get("type")

        if event_type == "content_block_delta":
            text = data.get("delta", {}).get("text")
            if text:
                return StreamChunk(type="token", content=text)

        if event_type == "message_delta":
            usage = data.get("usage", {})
            if usage:
                return StreamChunk(type="metadata", metadata={"output_tokens": usage.get("output_tokens")})

        if event_type == "message_stop":
            return StreamChunk(type="done")
        if event_type == "message_start":
            usage = data.get("message", {}).get("usage", {})
            if usage and usage.get("input_tokens") is not None:
                return StreamChunk(
                    type="metadata",
                    metadata={"input_tokens": usage.get("input_tokens")},
                )

        return None
