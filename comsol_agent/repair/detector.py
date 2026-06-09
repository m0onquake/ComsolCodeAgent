"""Error detection and classification for failed tool calls.

This is Phase 1 of the repair loop described in the architecture.  It is
deterministic and offline: no LLM, COMSOL, or API documentation lookup is
required to produce an ErrorReport.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class ErrorType(str, Enum):
    """Repair-loop error categories."""

    SYNTAX_ERROR = "SYNTAX_ERROR"
    API_ERROR = "API_ERROR"
    PHYSICS_ERROR = "PHYSICS_ERROR"
    SOLVER_ERROR = "SOLVER_ERROR"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass
class ErrorReport:
    """Structured report emitted by the detector phase."""

    error_type: ErrorType
    message: str
    tool_name: str | None = None
    code_snippet: str | None = None
    context: dict[str, Any] | None = None
    matched_rule: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        data = asdict(self)
        data["error_type"] = self.error_type.value
        return data


_RULES: list[tuple[ErrorType, str, tuple[str, ...]]] = [
    (
        ErrorType.SYNTAX_ERROR,
        "syntax",
        (
            r"syntax error",
            r"unexpected token",
            r"invalid syntax",
            r"parse error",
            r"unterminated",
        ),
    ),
    (
        ErrorType.API_ERROR,
        "api",
        (
            r"no method",
            r"method .* not found",
            r"nullpointer",
            r"classcastexception",
            r"attributeerror",
            r"unknown method",
            r"java\.lang\.(nullpointerexception|classcastexception)",
        ),
    ),
    (
        ErrorType.PHYSICS_ERROR,
        "physics",
        (
            r"failed to find",
            r"not defined",
            r"undefined variable",
            r"boundary condition",
            r"selection .* empty",
            r"domain .* not found",
        ),
    ),
    (
        ErrorType.SOLVER_ERROR,
        "solver",
        (
            r"failed to converge",
            r"\bnan\b",
            r"singular matrix",
            r"diverged",
            r"nonlinear solver",
            r"maximum number of iterations",
        ),
    ),
    (
        ErrorType.TIMEOUT_ERROR,
        "timeout",
        (
            r"timed out",
            r"timeout",
            r"exceeded",
            r"deadline",
        ),
    ),
]


def detect_tool_error(
    *,
    tool_name: str | None,
    tool_output: str | dict[str, Any],
    arguments: dict[str, Any] | None = None,
    context_messages: list[dict[str, Any]] | None = None,
) -> ErrorReport:
    """Classify a failed tool result and extract useful repair context."""
    parsed = _parse_tool_output(tool_output)
    message = _extract_error_message(parsed)
    if not message:
        message = str(tool_output)

    error_type, matched_rule = _classify_message(message)
    code_snippet = _extract_code_snippet(arguments or {}, parsed)
    context = {
        "arguments": _truncate_nested(arguments or {}, 2000),
        "tool_output": _truncate_nested(parsed, 4000),
    }
    if context_messages:
        context["recent_messages"] = _recent_context(context_messages)

    return ErrorReport(
        error_type=error_type,
        message=_truncate(message, 2000),
        tool_name=tool_name,
        code_snippet=code_snippet,
        context=context,
        matched_rule=matched_rule,
    )


def format_repair_notice(report: ErrorReport) -> str:
    """Create a compact message for the next LLM turn."""
    code_line = ""
    if report.code_snippet:
        code_line = f"\nRelated code snippet:\n{_truncate(report.code_snippet, 1200)}"
    return (
        "[SYSTEM] The previous tool call failed. Auto-repair detector classified "
        f"the error as {report.error_type.value}.\n"
        f"Tool: {report.tool_name or 'unknown'}\n"
        f"Error: {report.message}\n"
        "Use this classification to decide whether to correct syntax/API usage, "
        "adjust physics setup, tune solver settings, or ask the user for missing context."
        f"{code_line}"
    )


def _parse_tool_output(tool_output: str | dict[str, Any]) -> dict[str, Any] | str:
    if isinstance(tool_output, dict):
        return tool_output
    try:
        parsed = json.loads(tool_output)
        return parsed if isinstance(parsed, dict) else str(parsed)
    except json.JSONDecodeError:
        return tool_output


def _extract_error_message(parsed: dict[str, Any] | str) -> str:
    if isinstance(parsed, str):
        return parsed
    for key in ("error", "message", "stderr", "output"):
        value = parsed.get(key)
        if value:
            return str(value)
    return json.dumps(parsed, ensure_ascii=False, default=str)


def _classify_message(message: str) -> tuple[ErrorType, str | None]:
    normalized = message.lower()
    for error_type, rule_name, patterns in _RULES:
        for pattern in patterns:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return error_type, rule_name
    return ErrorType.UNKNOWN, None


def _extract_code_snippet(
    arguments: dict[str, Any],
    parsed_output: dict[str, Any] | str,
) -> str | None:
    for key in ("java_code", "code", "script", "python_code"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return _truncate(value.strip(), 2000)

    if isinstance(parsed_output, dict):
        for key in ("code_snippet", "snippet", "code"):
            value = parsed_output.get(key)
            if isinstance(value, str) and value.strip():
                return _truncate(value.strip(), 2000)
    return None


def _recent_context(messages: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    recent: list[dict[str, Any]] = []
    for message in messages[-limit:]:
        recent.append(
            {
                "role": message.get("role"),
                "name": message.get("name"),
                "content": _truncate(str(message.get("content", "")), 500),
            }
        )
    return recent


def _truncate_nested(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return _truncate(value, limit)
    if isinstance(value, dict):
        return {k: _truncate_nested(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate_nested(item, limit) for item in value[:20]]
    return value


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 16)] + "...[truncated]"
