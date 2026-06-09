"""Smoke-test DeepSeek OpenAI-compatible tool-call support."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.cli.config import load_config
from comsol_agent.llm.base import ToolDefinition
from comsol_agent.llm.router import create_provider


async def _run(model: str, base_url: str | None) -> int:
    config = load_config()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key and config.llm.provider == "deepseek":
        api_key = config.llm.api_key
    if model == "deepseek-v4-flash" and config.llm.provider == "deepseek":
        model = config.llm.model or model
    if base_url is None and config.llm.provider == "deepseek":
        base_url = config.llm.base_url
    if not api_key:
        print("DeepSeek API key is not set in env or config.", file=sys.stderr)
        return 2

    provider = create_provider("deepseek", model=model, api_key=api_key, base_url=base_url)
    tool = ToolDefinition(
        name="record_probe",
        description="Record a short probe value for integration testing.",
        parameters={
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "description": "The exact probe value to record.",
                }
            },
            "required": ["value"],
            "additionalProperties": False,
        },
    )
    response = await provider.generate(
        messages=[
            {
                "role": "system",
                "content": "You are testing tool-call support. Use tools when explicitly asked.",
            },
            {
                "role": "user",
                "content": "Call record_probe with value COMSOL_AGENT_TOOL_OK. Do not answer in text.",
            },
        ],
        tools=[tool],
        temperature=0,
        max_tokens=128,
    )

    if not response.tool_calls:
        print("DeepSeek did not return a tool call.")
        print(f"Text: {response.text!r}")
        return 1

    call = response.tool_calls[0]
    print("DeepSeek tool-call smoke test succeeded.")
    print(f"Model: {model}")
    print(f"Tool: {call.name}")
    print(f"Arguments: {call.arguments}")
    if call.name != "record_probe" or call.arguments.get("value") != "COMSOL_AGENT_TOOL_OK":
        print("Unexpected tool-call payload.")
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test DeepSeek tool-call support.")
    parser.add_argument("--model", default="deepseek-v4-flash", help="DeepSeek model name.")
    parser.add_argument("--base-url", default=None, help="DeepSeek OpenAI-compatible base URL.")
    args = parser.parse_args()
    base_url = args.base_url or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
    raise SystemExit(asyncio.run(_run(args.model, base_url)))


if __name__ == "__main__":
    main()
