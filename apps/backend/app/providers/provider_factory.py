from app.providers.anthropic import AnthropicProvider
from app.providers.openai import OpenAIProvider
from app.providers.gemini import GeminiProvider
from app.providers.llama import LlamaProvider

from app.middleware.logging_provider import LoggingProvider
from app.middleware.log_sink import CompositeSink, ConsoleSink, InMemorySink, KafkaSink
from app.config.settings import settings

in_memory_sink = InMemorySink()
kafka_sink = KafkaSink(
    bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
    topic="inference-events",
)
log_sink = CompositeSink(ConsoleSink(), in_memory_sink, kafka_sink)

PROVIDER_MAP = {
    "openai":    lambda: OpenAIProvider(api_key=settings.OPENAI_API_KEY),
    "anthropic": lambda: AnthropicProvider(api_key=settings.ANTHROPIC_API_KEY),
    "gemini":    lambda: GeminiProvider(api_key=settings.GEMINI_API_KEY),
    "llama":     lambda: LlamaProvider(api_key=settings.LLAMA_API_KEY),
}


def get_provider(name: str) -> LoggingProvider:
    provider_fn = PROVIDER_MAP.get(name.lower())
    if not provider_fn:
        raise ValueError(f"Unsupported provider: '{name}'. Supported: {list(PROVIDER_MAP.keys())}")
    return LoggingProvider(provider_fn(), sink=log_sink)
