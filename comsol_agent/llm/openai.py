"""OpenAI GPT provider implementation."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from .base import LLMProvider, LLMResponse, ToolCall, ToolDefinition


class OpenAIProvider(LLMProvider):
    """LLM provider for OpenAI GPT models (GPT-4, GPT-5, etc.)."""

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(model=model, api_key=api_key, **kwargs)
        self.base_url = base_url
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI SDK is not installed. Install dependencies with: pip install -e ."
            ) from exc

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    def _convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Ensure messages are in OpenAI format."""
        return messages

    def _convert_tools(
        self, tools: list[ToolDefinition] | None
    ) -> list[dict[str, Any]] | None:
        """Convert our ToolDefinition to OpenAI tool format."""
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        openai_messages = self._convert_messages(messages)
        openai_tools = self._convert_tools(tools)

        params: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            **kwargs,
        }
        if openai_tools:
            params["tools"] = openai_tools
            if self._is_deepseek_v4():
                # DeepSeek V4 thinking mode rejects tool_choice and requires
                # reasoning_content replay across tool turns. Keep the existing
                # OpenAI-style agent loop compatible by using non-thinking mode
                # whenever tools are present.
                params.pop("tool_choice", None)
                extra_body = dict(params.get("extra_body") or {})
                extra_body.setdefault("thinking", {"type": "disabled"})
                params["extra_body"] = extra_body
            else:
                params.setdefault("tool_choice", "auto")

        response = await self.client.chat.completions.create(**params)
        choice = response.choices[0]

        tool_calls: list[ToolCall] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolCall(id=tc.id, name=tc.function.name, arguments=args)
                )

        return LLMResponse(
            text=choice.message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage={
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
        )

    def _is_deepseek_v4(self) -> bool:
        """Return whether this provider targets DeepSeek V4 models."""
        base_url = str(self.base_url or "").lower()
        model = str(self.model or "").lower()
        return "deepseek" in base_url and model.startswith("deepseek-v4")

    async def generate_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        openai_messages = self._convert_messages(messages)

        params: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "stream": True,
            **kwargs,
        }

        stream = await self.client.chat.completions.create(**params)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def count_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Approximate token count using tiktoken."""
        try:
            import tiktoken

            enc = tiktoken.encoding_for_model(self.model)
        except (ImportError, KeyError):
            # Fallback: ~4 chars per token
            total_chars = sum(
                len(str(m.get("content", ""))) for m in messages
            )
            return max(1, total_chars // 4)

        total = 0
        for message in messages:
            total += 4  # message framing overhead
            for key, value in message.items():
                if isinstance(value, str):
                    total += len(enc.encode(value))
                elif isinstance(value, list):
                    for item in value:
                        total += len(enc.encode(json.dumps(item)))
        return total
