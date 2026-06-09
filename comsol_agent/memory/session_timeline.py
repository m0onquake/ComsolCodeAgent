"""Build compact audit timelines from session snapshots."""

from __future__ import annotations

import json
from typing import Any


def build_session_timeline(
    snapshot: dict[str, Any] | None,
    *,
    max_events: int = 30,
) -> list[dict[str, Any]]:
    """Return a compact ordered timeline for a saved session snapshot."""
    if not snapshot:
        return []

    events: list[dict[str, Any]] = []
    for message_index, message in enumerate(snapshot.get("messages") or [], start=1):
        role = message.get("role")
        if role == "system":
            continue

        if role == "assistant" and message.get("tool_calls"):
            content = _message_text(message)
            if content:
                events.append(_event(message_index, "assistant", "assistant", content))
            for tool_call in message.get("tool_calls") or []:
                function = tool_call.get("function") or {}
                events.append(
                    _event(
                        message_index,
                        "tool_call",
                        function.get("name") or "tool_call",
                        _format_arguments(function.get("arguments")),
                        tool_call_id=tool_call.get("id"),
                    )
                )
            continue

        if role == "tool":
            output = _parse_tool_output(message.get("content"))
            status = _tool_status(output)
            events.append(
                _event(
                    message_index,
                    "tool_result",
                    message.get("name") or "tool_result",
                    _tool_detail(output),
                    status=status,
                    tool_call_id=message.get("tool_call_id"),
                )
            )
            continue

        if role in {"user", "assistant"}:
            events.append(_event(message_index, role, role, _message_text(message)))

    for report_index, report in enumerate(snapshot.get("repair_reports") or [], start=1):
        plan = report.get("repair_plan") or {}
        events.append(
            {
                "index": len(events) + 1,
                "message_index": None,
                "type": "repair_report",
                "title": report.get("tool_name") or "repair",
                "detail": _truncate(
                    f"{report.get('error_type') or 'ERROR'}: {report.get('message') or ''}",
                    260,
                ),
                "status": plan.get("risk_level") or "",
                "tool_call_id": None,
                "metadata": {
                    "report_index": report_index,
                    "action": plan.get("action"),
                    "can_auto_retry": plan.get("can_auto_retry"),
                },
            }
        )

    for index, event in enumerate(events[:max(0, max_events)], start=1):
        event["index"] = index
    return events[:max(0, max_events)]


def summarize_timeline(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Return counts useful for script output and CLI summaries."""
    counts: dict[str, int] = {}
    tool_names: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("type") or "")
        counts[event_type] = counts.get(event_type, 0) + 1
        if event_type in {"tool_call", "tool_result"}:
            title = str(event.get("title") or "")
            tool_names[title] = tool_names.get(title, 0) + 1
    return {
        "event_count": len(events),
        "counts": counts,
        "tools": tool_names,
    }


def _event(
    message_index: int,
    event_type: str,
    title: str,
    detail: str,
    *,
    status: str = "",
    tool_call_id: str | None = None,
) -> dict[str, Any]:
    return {
        "index": 0,
        "message_index": message_index,
        "type": event_type,
        "title": title,
        "detail": _truncate(detail, 260),
        "status": status,
        "tool_call_id": tool_call_id,
        "metadata": {},
    }


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return _truncate(content, 260)
    if isinstance(content, list):
        return _truncate(" ".join(str(item) for item in content), 260)
    return _truncate(str(content or ""), 260)


def _format_arguments(arguments: Any) -> str:
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except Exception:
            return _truncate(arguments, 260)
    else:
        parsed = arguments
    if isinstance(parsed, dict):
        return ", ".join(f"{key}={value!r}" for key, value in parsed.items())
    return _truncate(str(parsed or ""), 260)


def _parse_tool_output(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except Exception:
        return content


def _tool_status(output: Any) -> str:
    if isinstance(output, dict):
        if output.get("success") is True:
            return "ok"
        if output.get("success") is False:
            return "error"
    return ""


def _tool_detail(output: Any) -> str:
    if isinstance(output, dict):
        if output.get("error"):
            return str(output.get("error"))
        parts = []
        for key in ("model_name", "run_id", "report_id", "message", "filepath"):
            if output.get(key) is not None:
                parts.append(f"{key}={output.get(key)}")
        if output.get("artifacts"):
            artifacts = output.get("artifacts") or {}
            parts.append(f"artifacts={artifacts.get('run_id') or artifacts.get('json_path')}")
        if parts:
            return ", ".join(parts)
        return json.dumps(output, ensure_ascii=False, default=str)[:260]
    return str(output or "")


def _truncate(text: str, max_chars: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)] + "..."
