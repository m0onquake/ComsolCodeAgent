"""Tool registry — central registration and discovery of all agent tools.

Tools are registered with:
- A unique name
- A description for the LLM
- A JSON Schema for parameters
- The actual handler function

This registry generates ToolDefinition objects for the LLM provider.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Coroutine
from typing import Any

from comsol_agent.llm.base import ToolDefinition


# Type alias for tool handler functions
ToolHandler = Callable[..., Coroutine[Any, Any, dict[str, Any]]]

# Global registry
_registry: dict[str, tuple[ToolDefinition, ToolHandler]] = {}


def register(
    name: str,
    description: str,
    parameters: dict[str, Any],
    handler: ToolHandler,
) -> None:
    """Register a tool.

    Args:
        name: Unique tool name.
        description: Human-readable description for the LLM.
        parameters: JSON Schema for the tool's parameters.
        handler: Async callable that executes the tool.
    """
    _registry[name] = (
        ToolDefinition(name=name, description=description, parameters=parameters),
        handler,
    )


def get_tool_definitions() -> list[ToolDefinition]:
    """Get all registered tool definitions for the LLM."""
    return [td for td, _ in _registry.values()]


def get_tool_definition(name: str) -> ToolDefinition | None:
    """Get the definition for a specific tool."""
    entry = _registry.get(name)
    return entry[0] if entry else None


def get_tool_handler(name: str) -> ToolHandler | None:
    """Get the handler for a specific tool."""
    entry = _registry.get(name)
    return entry[1] if entry else None


def get_all_tools() -> dict[str, tuple[ToolDefinition, ToolHandler]]:
    """Get all registered tools (for debugging)."""
    return dict(_registry)


def clear() -> None:
    """Clear all registered tools (for testing)."""
    _registry.clear()


def list_tools() -> list[str]:
    """List all registered tool names."""
    return list(_registry.keys())


def validate_tool_arguments(name: str, arguments: dict[str, Any]) -> list[str]:
    """Validate tool arguments against the registered JSON schema subset.

    This intentionally implements the small schema surface used by the tool
    definitions: required fields, primitive types, enums, and optional
    additionalProperties=false.
    """
    definition = get_tool_definition(name)
    if definition is None:
        return [f"Unknown tool: {name}"]

    schema = definition.parameters or {}
    if schema.get("type") != "object":
        return []

    errors: list[str] = []
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    for field in required:
        if field not in arguments:
            errors.append(f"Missing required argument: {field}")

    if schema.get("additionalProperties") is False:
        for field in arguments:
            if field not in properties:
                errors.append(f"Unexpected argument: {field}")

    for field, value in arguments.items():
        field_schema = properties.get(field)
        if not field_schema:
            continue

        expected_type = field_schema.get("type")
        if expected_type and not _matches_json_type(value, expected_type):
            errors.append(
                f"Argument '{field}' must be {expected_type}; got {type(value).__name__}"
            )

        enum_values = field_schema.get("enum")
        if enum_values is not None and value not in enum_values:
            errors.append(
                f"Argument '{field}' must be one of {enum_values}; got {value!r}"
            )

    return errors


def _matches_json_type(value: Any, expected_type: str | list[str]) -> bool:
    """Return whether a Python value matches a JSON Schema primitive type."""
    if isinstance(expected_type, list):
        return any(_matches_json_type(value, t) for t in expected_type)

    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (isinstance(value, int | float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "null":
        return value is None
    return True


# ---- Synchronous wrapper for tools ----

def register_sync(
    name: str,
    description: str,
    parameters: dict[str, Any],
    handler: Callable[..., dict[str, Any]] | ToolHandler,
) -> None:
    """Register a synchronous tool (wraps it in an async function).

    If an async handler is accidentally passed here, await it instead of
    leaking a coroutine object into the agent loop.
    """

    async def async_handler(**kwargs: Any) -> dict[str, Any]:
        result = handler(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    register(name, description, parameters, async_handler)
