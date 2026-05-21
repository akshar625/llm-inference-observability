from typing import AsyncGenerator
from app.config.constants import Constants, HttpMethods
from app.providers.http_client import BaseLLMProvider


class AnthropicProvider(BaseLLMProvider):

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

    async def stream(self, messages: list, model: str, temperature: float = 0.7, max_tokens: int = 1024) -> AsyncGenerator[str, None]:
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
                data = line[len("data: "):]
                yield data
