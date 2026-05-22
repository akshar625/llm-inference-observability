"""
Streaming chunk inspection test.
Prints every chunk on its own line with an index so you can see
whether Anthropic batches tokens or streams them individually.
"""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.providers.provider_factory import get_provider

PROMPT = (
    "Write a short paragraph (4-5 sentences) about how the internet works. "
    "Be detailed and technical."
)


async def inspect_stream(provider_name: str, model: str):
    print(f"\n=== {provider_name} / {model} ===")
    print(f"Prompt: {PROMPT[:60]}...\n")

    provider = get_provider(provider_name)

    chunk_index = 0
    token_chunks = 0
    start = time.monotonic()

    async for chunk in provider.stream(
        messages=[{"role": "user", "content": PROMPT}],
        model=model,
    ):
        elapsed = (time.monotonic() - start) * 1000

        if chunk.type == "token":
            token_chunks += 1
            # repr() shows \n, spaces etc clearly
            print(f"  [{chunk_index:03d}] +{elapsed:6.0f}ms  TOKEN    {repr(chunk.content)}")
        elif chunk.type == "metadata":
            print(f"  [{chunk_index:03d}] +{elapsed:6.0f}ms  METADATA {chunk.metadata}")
        elif chunk.type == "done":
            print(f"  [{chunk_index:03d}] +{elapsed:6.0f}ms  DONE")
        elif chunk.type == "error":
            print(f"  [{chunk_index:03d}] +{elapsed:6.0f}ms  ERROR    {chunk.error}")

        chunk_index += 1

    total = (time.monotonic() - start) * 1000
    print(f"\n  total chunks: {chunk_index}  |  token chunks: {token_chunks}  |  {total:.0f}ms total")


async def main():
    await inspect_stream("anthropic", "claude-haiku-4-5-20251001")


if __name__ == "__main__":
    asyncio.run(main())
