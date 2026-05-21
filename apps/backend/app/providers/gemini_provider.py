from typing import AsyncGenerator
import json
from app.config.constants import Constants, HttpMethods
from app.providers.http_client import BaseLLMProvider


class GeminiProvider(BaseLLMProvider):
    """
    Gemini auth is via query param (key=), not Authorization header.
    Streaming endpoint is streamGenerateContent with alt=sse.
    """

    def __init__(self, api_key: str, timeout: int = 30):
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
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
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

    async def stream(self, messages: list, model: str, temperature: float = 0.7, max_tokens: int = 1024) -> AsyncGenerator[str, None]:
        url = f"{self.base_url}/models/{model}:streamGenerateContent?key={self.api_key}&alt=sse"
        payload = {
            "contents": self._to_gemini_messages(messages),
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }

        async for line in self.make_stream_request(url=url, payload_json=payload, headers=self.headers, timeout=self.timeout):
            if line.startswith("data: "):
                data = line[len("data: "):]
                try:
                    parsed = json.loads(data)
                    token = parsed["candidates"][0]["content"]["parts"][0].get("text", "")
                    if token:
                        yield token
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass

    def _to_gemini_messages(self, messages: list) -> list:
        """Convert OpenAI-style messages to Gemini contents format."""
        role_map = {"user": "user", "assistant": "model"}
        return [
            {
                "role": role_map.get(m["role"], "user"),
                "parts": [{"text": m["content"]}]
            }
            for m in messages
            if m["role"] in role_map
        ]
