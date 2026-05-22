import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.providers.provider_factory import get_provider
from app.config.constants import Constants

MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "gemini": "gemini-2.0-flash",
    # "openai": "gpt-4o-mini",
    # "llama": "llama3.1-70b",
}


async def test_provider(name: str, model: str):
    print(f"\n=== {name} ({model}) ===")
    provider = get_provider(name)

    print("generate -> ", end="", flush=True)
    resp = await provider.generate(
        messages=[{"role": "user", "content": "Say hi in 5 words."}],
        model=model,
    )

    if resp[Constants.ACTION_STATUS] == Constants.SUCCESS:
        result = resp[Constants.ACTION_RESULT][Constants.RESPONSE]
        print(result["content"])
        print(f"         tokens: {result['input_tokens']} in / {result['output_tokens']} out")
    else:
        print(f"FAILED: {resp[Constants.ACTION_RESULT]}")
        return

    print("stream   -> ", end="", flush=True)
    async for chunk in provider.stream(
        messages=[{"role": "user", "content": "Count from 1 to 5."}],
        model=model,
    ):
        if chunk.type == "token":
            print(chunk.content, end="", flush=True)
        elif chunk.type == "stream_start":
            print(f"[stream_start: {chunk.metadata}]", flush=True)
        elif chunk.type == "metadata":
            print(f"\n[metadata: {chunk.metadata}]", end="", flush=True)
        elif chunk.type == "done":
            print("\n[done]")
        elif chunk.type == "error":
            print(f"\n[error: {chunk.error}]")


async def main():
    for name, model in MODELS.items():
        try:
            await test_provider(name, model)
        except Exception as e:
            print(f"\n[{name}] ERROR: {e}")


if __name__ == "__main__":
    asyncio.run(main())
