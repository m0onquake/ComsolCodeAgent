"""Smoke-test the DeepSeek OpenAI-compatible chat API.

The script reads DEEPSEEK_API_KEY from the environment and never prints it.
It performs one small non-streaming chat-completions call.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.cli.config import load_config
from comsol_agent.llm.router import create_provider


async def _run(model: str, base_url: str | None, prompt: str) -> int:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    config = load_config()
    if not api_key and config.llm.provider == "deepseek":
        api_key = config.llm.api_key
    if model == "deepseek-v4-flash" and config.llm.provider == "deepseek":
        model = config.llm.model or model
    if base_url is None and config.llm.provider == "deepseek":
        base_url = config.llm.base_url
    if not api_key:
        print("DeepSeek API key is not set in env or config.", file=sys.stderr)
        return 2

    provider = create_provider(
        "deepseek",
        model=model,
        api_key=api_key,
        base_url=base_url,
    )
    response = await provider.generate(
        messages=[
            {"role": "system", "content": "You are a concise API smoke-test assistant."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=128,
    )

    print("DeepSeek API smoke test succeeded.")
    print(f"Model: {model}")
    print(f"Finish reason: {response.finish_reason}")
    if response.usage:
        print(f"Total tokens: {response.usage.get('total_tokens', 0)}")
    print("Response:")
    print(response.text or "")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test DeepSeek API connectivity.")
    parser.add_argument("--model", default="deepseek-v4-flash", help="DeepSeek model name.")
    parser.add_argument("--base-url", default=None, help="DeepSeek OpenAI-compatible base URL.")
    parser.add_argument(
        "--prompt",
        default="Reply with exactly: COMSOL Agent DeepSeek OK",
        help="Small prompt for the smoke test.",
    )
    args = parser.parse_args()
    base_url = args.base_url or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
    raise SystemExit(asyncio.run(_run(args.model, base_url, args.prompt)))


if __name__ == "__main__":
    main()
