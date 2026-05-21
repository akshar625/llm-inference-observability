from app.providers.openai_provider import OpenAIProvider
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.http_client import BaseLLMProvider
from app.config.settings import settings

PROVIDER_MAP = {
    "openai": lambda: OpenAIProvider(api_key=settings.OPENAI_API_KEY),
    "anthropic": lambda: AnthropicProvider(api_key=settings.ANTHROPIC_API_KEY),
}


def get_provider(name: str) -> BaseLLMProvider:
    provider_fn = PROVIDER_MAP.get(name.lower())
    if not provider_fn:
        raise ValueError(f"Unsupported provider: '{name}'. Supported: {list(PROVIDER_MAP.keys())}")
    return provider_fn()
