import json
from typing import AsyncGenerator
from app.config.constants import Constants, HttpMethods
from app.providers.base_provider import BaseLLMProvider
from app.schemas.chat import StreamChunk


class GeminiProvider(BaseLLMProvider):

    # Gemini auth is via query param (key=), not Authorization header.
    MODELS = {
        "gemini-2.5-flash-preview-05-20": {"max_tokens_default": 1024, "supports_streaming": True, "context_window": 1_048_576},
        "gemini-2.0-flash":               {"max_tokens_default": 1024, "supports_streaming": True, "context_window": 1_048_576},
        "gemini-flash-latest":            {"max_tokens_default": 1024, "supports_streaming": True, "context_window": 1_048_576},
    }

    def __init__(self, api_key: str, timeout: int = 30):
        '''
        API Doc: https://ai.google.dev/gemini-api/docs/interactions/streaming
        '''
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.timeout = min(max(int(timeout), 15), 120)

    async def ping(self) -> dict:
        url = f"{self.base_url}/models"
        return await self.test_connection(url=f"{url}?key={self.api_key}", headers=self.headers, timeout=self.timeout)

    async def generate(self, messages: list, model: str, temperature: float = 0.7, max_tokens: int = 1024) -> dict:
        url = f"{self.base_url}/models/{model}:generateContent"
        payload = {
            "contents": self._to_gemini_messages(messages),
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}
        }

        response = await self.request_handler(
            method=HttpMethods.POST.value,
            url=url,
            payload_json=payload,
            query_params={"key": self.api_key},
            headers=self.headers,
            timeout=self.timeout,
            retry_count=3,
            retry_wait=5
        )

        if response[Constants.ACTION_STATUS] == Constants.SUCCESS:
            raw = response[Constants.ACTION_RESULT][Constants.RESPONSE]
            content = raw["candidates"][0]["content"]["parts"][0]["text"]
            usage = raw.get("usageMetadata", {})
            response[Constants.ACTION_RESULT][Constants.RESPONSE] = {
                "content": content,
                "input_tokens": usage.get("promptTokenCount", 0),
                "output_tokens": usage.get("candidatesTokenCount", 0),
                "model": model
            }

        return response

    async def stream(self, messages: list, model: str, temperature: float = 0.7, max_tokens: int = 1024) -> AsyncGenerator[StreamChunk, None]:
        # Gemini can emit text AND finishReason in the same chunk,
        # so we yield multiple StreamChunks per SSE line instead of using _normalize_chunk.
        url = f"{self.base_url}/models/{model}:streamGenerateContent?key={self.api_key}&alt=sse"
        payload = {
            "contents": self._to_gemini_messages(messages),
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}
        }

        async for line in self.make_stream_request(url=url, payload_json=payload, headers=self.headers, timeout=self.timeout):
            if not line.startswith("data: "):
                continue
            try:
                data = json.loads(line[len("data: "):])
            except (json.JSONDecodeError, TypeError):
                continue

            candidates = data.get("candidates", [])
            if candidates:
                candidate = candidates[0]
                parts = candidate.get("content", {}).get("parts", [])
                text = parts[0].get("text", "") if parts else ""
                if text:
                    yield StreamChunk(type="token", content=text)

                if candidate.get("finishReason") in ("STOP", "MAX_TOKENS"):
                    usage = data.get("usageMetadata", {})
                    if usage:
                        yield StreamChunk(type="metadata", metadata={
                            "input_tokens": usage.get("promptTokenCount"),
                            "output_tokens": usage.get("candidatesTokenCount"),
                        })
                    yield StreamChunk(type="done")
            else:
                usage = data.get("usageMetadata", {})
                if usage:
                    yield StreamChunk(type="metadata", metadata={
                        "input_tokens": usage.get("promptTokenCount"),
                        "output_tokens": usage.get("candidatesTokenCount"),
                    })

    def _to_gemini_messages(self, messages: list) -> list:
        role_map = {"user": "user", "assistant": "model"}
        return [
            {"role": role_map.get(m["role"], "user"), "parts": [{"text": m["content"]}]}
            for m in messages
            if m["role"] in role_map
        ]
