"""Deterministic context compaction helpers.

This is the offline skeleton for the architecture's Phase 2 compaction flow.
It preserves user messages verbatim, keeps a recent suffix intact, and replaces
older assistant/tool details with a compact summary.  LLM-written summaries and
archive/vector persistence can be layered on top later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from comsol_agent.utils.token_counter import estimate_messages_tokens


@dataclass
class CompactionResult:
    """Result of compacting an OpenAI-style message list."""

    messages: list[dict[str, Any]]
    summary: str
    original_tokens: int
    compacted_tokens: int
    compressed_message_count: int
    preserved_user_count: int

    @property
    def changed(self) -> bool:
        return self.compressed_message_count > 0 and self.compacted_tokens < self.original_tokens


def compact_messages(
    messages: list[dict[str, Any]],
    *,
    model: str = "gpt-4o",
    recency_zone_tokens: int = 8000,
    max_summary_chars: int = 2500,
    max_tool_result_chars: int = 2000,
) -> CompactionResult:
    """Compact older non-user messages while preserving user messages verbatim."""
    original_tokens = estimate_messages_tokens(messages, model)
    if len(messages) <= 2:
        return CompactionResult(
            messages=list(messages),
            summary="",
            original_tokens=original_tokens,
            compacted_tokens=original_tokens,
            compressed_message_count=0,
            preserved_user_count=0,
        )

    system_messages = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]
    recency_start = _find_recency_start(non_system, model, recency_zone_tokens)
    older = non_system[:recency_start]
    recent = non_system[recency_start:]

    older_user_messages = [m for m in older if m.get("role") == "user"]
    compressible = [m for m in older if m.get("role") != "user"]
    summary = _summarize_messages(
        compressible,
        max_summary_chars=max_summary_chars,
        max_tool_result_chars=max_tool_result_chars,
    )

    if summary:
        summary_message = {
            "role": "user",
            "content": "[Compacted context]\n"
            + summary
            + "\n\nOlder user messages are preserved verbatim below.",
        }
        compacted = system_messages + [summary_message] + older_user_messages + recent
    else:
        compacted = system_messages + older_user_messages + recent

    compacted_tokens = estimate_messages_tokens(compacted, model)
    if compacted_tokens >= original_tokens:
        compacted = list(messages)
        compacted_tokens = original_tokens
        compressed_count = 0
    else:
        compressed_count = len(compressible)

    return CompactionResult(
        messages=compacted,
        summary=summary,
        original_tokens=original_tokens,
        compacted_tokens=compacted_tokens,
        compressed_message_count=compressed_count,
        preserved_user_count=len(older_user_messages),
    )


def _find_recency_start(
    messages: list[dict[str, Any]],
    model: str,
    recency_zone_tokens: int,
) -> int:
    """Return the first index of the recent suffix to keep verbatim."""
    if recency_zone_tokens <= 0:
        return len(messages)

    token_total = 0
    for index in range(len(messages) - 1, -1, -1):
        message_tokens = estimate_messages_tokens([messages[index]], model)
        if token_total + message_tokens > recency_zone_tokens and index < len(messages) - 1:
            return index + 1
        token_total += message_tokens
    return 0


def _summarize_messages(
    messages: list[dict[str, Any]],
    *,
    max_summary_chars: int,
    max_tool_result_chars: int,
) -> str:
    if not messages:
        return ""

    lines: list[str] = []
    for index, message in enumerate(messages, start=1):
        role = message.get("role", "unknown")
        if role == "assistant":
            lines.append(_summarize_assistant_message(index, message))
        elif role == "tool":
            lines.append(_summarize_tool_message(index, message, max_tool_result_chars))
        else:
            lines.append(f"{index}. {role}: {_truncate(str(message.get('content', '')), 240)}")

        if sum(len(line) for line in lines) >= max_summary_chars:
            lines.append("... summary truncated ...")
            break

    summary = "\n".join(lines)
    return _truncate(summary, max_summary_chars)


def _summarize_assistant_message(index: int, message: dict[str, Any]) -> str:
    parts = []
    content = message.get("content")
    if content:
        parts.append(_truncate(str(content), 220))

    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        names = []
        for tool_call in tool_calls:
            function = tool_call.get("function", {})
            names.append(function.get("name") or tool_call.get("name") or "unknown_tool")
        parts.append("tool_calls=" + ", ".join(names))

    return f"{index}. assistant: " + ("; ".join(parts) if parts else "(no text)")


def _summarize_tool_message(
    index: int,
    message: dict[str, Any],
    max_tool_result_chars: int,
) -> str:
    name = message.get("name", "unknown_tool")
    raw_content = str(message.get("content", ""))
    content = _truncate(raw_content, max_tool_result_chars)

    try:
        parsed = json.loads(raw_content)
        if isinstance(parsed, dict):
            success = parsed.get("success")
            error = parsed.get("error")
            if error:
                content = f"success={success}, error={_truncate(str(error), 220)}"
            elif success is not None:
                content = f"success={success}, keys={sorted(parsed.keys())}"
    except json.JSONDecodeError:
        pass

    return f"{index}. tool {name}: {content}"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 16)] + "...[truncated]"
