"""Abstract base class for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """Represents a tool call from the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """Represents the result of executing a tool."""

    tool_call_id: str
    name: str
    output: str
    is_error: bool = False


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    provider_request_id: str | None = None

    @property
    def is_text(self) -> bool:
        return self.text is not None and not self.tool_calls

    @property
    def is_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class ToolDefinition:
    """Tool definition to pass to LLM providers."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the parameters


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    def __init__(self, model: str, api_key: str | None = None, **kwargs: Any):
        self.model = model
        self.api_key = api_key

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a response from the LLM.

        Args:
            messages: List of message dicts in the provider's format.
            tools: Optional list of tool definitions.
            **kwargs: Additional provider-specific arguments.

        Returns:
            A unified LLMResponse.
        """
        ...

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a text response from the LLM.

        Args:
            messages: List of message dicts.
            tools: Optional tool definitions (streaming with tools is provider-specific).
            **kwargs: Additional arguments.

        Yields:
            Text chunks from the LLM.
        """
        ...

    @abstractmethod
    def count_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Count the approximate number of tokens in the messages."""
        ...
