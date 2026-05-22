import json
from typing import AsyncGenerator, Optional
from app.config.constants import Constants, HttpMethods
from app.providers.http_client import BaseLLMProvider
from app.schemas.chat import StreamChunk


class LlamaProvider(BaseLLMProvider):

    MODELS = {
        "llama3.1-70b": {"max_tokens_default": 1024, "supports_streaming": True, "context_window": 128_000},
        "llama3.1-8b":  {"max_tokens_default": 1024, "supports_streaming": True, "context_window": 128_000},
    }

    def __init__(self, api_key: str, timeout: int = 30):
        self.base_url = "https://api.llama-api.com"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.timeout = min(max(int(timeout), 15), 120)

    async def ping(self) -> dict:
        url = f"{self.base_url}/models"
        return await self.test_connection(url=url, headers=self.headers, timeout=self.timeout)

    async def generate(self, messages: list, model: str, temperature: float = 0.7, max_tokens: int = 1024) -> dict:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
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
            content = raw["choices"][0]["message"]["content"]
            usage = raw.get("usage", {})
            response[Constants.ACTION_RESULT][Constants.RESPONSE] = {
                "content": content,
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "model": raw.get("model", model)
            }

        return response

    async def stream(self, messages: list, model: str, temperature: float = 0.7, max_tokens: int = 1024) -> AsyncGenerator[StreamChunk, None]:
        url = f"{self.base_url}/chat/completions"
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
        if raw_line.strip() == "[DONE]":
            return StreamChunk(type="done")

        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, TypeError):
            return None

        choice = (data.get("choices") or [{}])[0]
        token = choice.get("delta", {}).get("content")

        if token:
            return StreamChunk(type="token", content=token)

        if choice.get("finish_reason"):
            return StreamChunk(type="done")

        return None
