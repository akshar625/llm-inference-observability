import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.providers.provider_factory import get_provider
from app.config.constants import Constants

MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    # claude-haiku-4-5-20251001
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
        print(result)
        # generate -> {'content': 'Hi! How are you doing?', 'input_tokens': 15, 'output_tokens': 10, 'model': 'claude-haiku-4-5-20251001'}
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
        import json
        try:
            data = json.loads(chunk)
            # OpenAI: choices[0].delta.content
            token = (
                data.get("choices", [{}])[0].get("delta", {}).get("content")
                # Anthropic: delta.text
                or data.get("delta", {}).get("text")
            )
            if token:
                print(token, end="", flush=True)
        except (json.JSONDecodeError, KeyError):
            pass
    print()


async def main():
    for name, model in MODELS.items():
        try:
            await test_provider(name, model)
        except Exception as e:
            print(f"\n[{name}] ERROR: {e}")


if __name__ == "__main__":
    asyncio.run(main())
