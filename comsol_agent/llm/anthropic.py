"""Anthropic Claude provider implementation."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from .base import LLMProvider, LLMResponse, ToolCall, ToolDefinition


class AnthropicProvider(LLMProvider):
    """LLM provider for Anthropic Claude models."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(model=model, api_key=api_key, **kwargs)
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise RuntimeError(
                "Anthropic SDK is not installed. Install dependencies with: pip install -e ."
            ) from exc

        self.client = AsyncAnthropic(api_key=api_key, base_url=base_url)

    def _convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert OpenAI-format messages to Anthropic format.

        Returns (system_prompt, messages_list).
        """
        system_prompt = None
        anthropic_messages: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                system_prompt = content if isinstance(content, str) else str(content)
            elif role == "tool":
                anthropic_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id", ""),
                            "content": content if isinstance(content, str) else json.dumps(content),
                        }
                    ],
                })
            elif role == "assistant" and msg.get("tool_calls"):
                # Convert assistant message with tool_calls
                tool_blocks: list[dict[str, Any]] = []
                text_parts: list[str] = []
                if isinstance(content, str) and content:
                    text_parts.append(content)

                for tc in msg["tool_calls"]:
                    tool_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": tc.get("function", {}).get("name", tc.get("name", "")),
                        "input": tc.get("function", {}).get(
                            "arguments", tc.get("arguments", {})
                        )
                        if isinstance(
                            tc.get("function", {}).get("arguments", tc.get("arguments", {})),
                            dict,
                        )
                        else json.loads(
                            tc.get("function", {}).get(
                                "arguments", tc.get("arguments", "{}")
                            )
                        ),
                    })

                content_blocks: list[dict[str, Any]] = []
                if text_parts:
                    content_blocks.append({"type": "text", "text": "\n".join(text_parts)})
                content_blocks.extend(tool_blocks)

                anthropic_messages.append({"role": "assistant", "content": content_blocks})
            else:
                anthropic_messages.append({"role": role, "content": content})

        return system_prompt, anthropic_messages

    def _convert_tools(
        self, tools: list[ToolDefinition] | None
    ) -> list[dict[str, Any]] | None:
        """Convert our ToolDefinition to Anthropic tool format."""
        if not tools:
            return None
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        system_prompt, anthropic_messages = self._convert_messages(messages)
        anthropic_tools = self._convert_tools(tools)

        params: dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.pop("max_tokens", 8192),
            **kwargs,
        }
        if system_prompt:
            params["system"] = system_prompt
        if anthropic_tools:
            params["tools"] = anthropic_tools

        response = await self.client.messages.create(**params)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )

        return LLMResponse(
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            finish_reason=response.stop_reason or "stop",
            usage={
                "input_tokens": response.usage.input_tokens if response.usage else 0,
                "output_tokens": response.usage.output_tokens if response.usage else 0,
                "total_tokens": (
                    response.usage.input_tokens + response.usage.output_tokens
                    if response.usage
                    else 0
                ),
            },
        )

    async def generate_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        system_prompt, anthropic_messages = self._convert_messages(messages)

        params: dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.pop("max_tokens", 8192),
            **kwargs,
        }
        if system_prompt:
            params["system"] = system_prompt

        async with self.client.messages.stream(**params) as stream:
            async for text in stream.text_stream:
                yield text

    def count_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Approximate token count for Anthropic messages."""
        try:
            import tiktoken

            enc = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            total_chars = sum(
                len(str(m.get("content", ""))) for m in messages
            )
            return max(1, total_chars // 4)

        total = 0
        for message in messages:
            total += 4
            for key, value in message.items():
                if isinstance(value, str):
                    total += len(enc.encode(value))
                elif isinstance(value, list):
                    for item in value:
                        total += len(enc.encode(json.dumps(item)))
        return total
