"""Session snapshot storage for audit and debugging.

The architecture keeps a JSON backup of conversation state under
``~/.comsol_agent/sessions``.  This module deliberately stores plain snapshots
only; retrieval, vector search, and long-term memory belong to later phases.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from comsol_agent.memory.archive_store import ArchiveStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_session_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return f"session_{timestamp}"


class SessionStore:
    """Write whole-session JSON snapshots to disk."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        session_dir: Path,
        session_id: str | None = None,
        archive_store: ArchiveStore | None = None,
    ):
        self.session_dir = Path(session_dir).expanduser().resolve()
        self.session_id = session_id or _new_session_id()
        self.created_at = _utc_now()
        self.path = self.session_dir / f"{self.session_id}.json"
        self.archive_store = archive_store

    def save(
        self,
        *,
        state: Any,
        provider: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Persist a JSON snapshot of the current agent state."""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": _utc_now(),
            "llm": {
                "provider": provider,
                "model": model,
            },
            "stats": {
                "total_tokens_used": getattr(state, "total_tokens_used", 0),
                "tool_iterations_this_turn": getattr(state, "tool_iterations_this_turn", 0),
                "message_count": len(getattr(state, "messages", [])),
                "turn_count": len([m for m in getattr(state, "messages", []) if m.get("role") == "user"]),
            },
            "messages": getattr(state, "messages", []),
            "turns": [_to_jsonable(turn) for turn in getattr(state, "turns", [])],
            "repair_reports": _to_jsonable(getattr(state, "repair_reports", [])),
            "metadata": metadata or {},
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        self._save_archive(payload)
        return self.path

    def _save_archive(self, payload: dict[str, Any]) -> None:
        if self.archive_store is None:
            return

        metadata = payload.get("metadata", {})
        event = metadata.get("event")
        self.archive_store.upsert_session(
            self.session_id,
            name=metadata.get("session_name"),
            summary=metadata.get("summary"),
            created_at=self.created_at,
        )

        compaction_summary = metadata.get("compaction_summary")
        if event in {"manual_compact", "auto_compact"} and compaction_summary:
            self.archive_store.add_memory(
                self.session_id,
                memory_type="compaction_summary",
                content=str(compaction_summary),
                token_count=int(metadata.get("compacted_tokens", 0)),
                metadata={
                    "event": event,
                    "original_tokens": metadata.get("original_tokens"),
                    "compressed_message_count": metadata.get("compressed_message_count"),
                },
            )


def _to_jsonable(value: Any) -> Any:
    """Convert dataclass-style objects to JSON-compatible values."""
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    return value
