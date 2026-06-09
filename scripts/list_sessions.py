"""List, search, or inspect archived COMSOL Agent sessions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.memory.archive_store import ArchiveSession, ArchiveStore
from comsol_agent.memory.session_timeline import build_session_timeline, summarize_timeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect archived COMSOL Agent sessions.")
    parser.add_argument("--query", default=None, help="Search sessions by id, name, or summary.")
    parser.add_argument("--show", default=None, help="Show one session id with memory/snapshot details.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-events", type=int, default=30)
    parser.add_argument("--archive-path", default=None)
    parser.add_argument("--session-dir", default=None)
    args = parser.parse_args()

    archive_path = Path(args.archive_path).expanduser() if args.archive_path else _default_archive_path()
    session_dir = Path(args.session_dir).expanduser() if args.session_dir else _default_session_dir()
    archive = ArchiveStore(archive_path)

    if args.show:
        result = _show_session(archive, session_dir, args.show, max_events=args.max_events)
    else:
        sessions = (
            archive.search_sessions(args.query, limit=args.limit)
            if args.query
            else archive.list_sessions(limit=args.limit)
        )
        result = {
            "success": True,
            "archive_path": str(archive.db_path),
            "session_dir": str(session_dir),
            "count": len(sessions),
            "sessions": [_session_to_dict(session) for session in sessions],
        }

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result.get("success"):
        raise SystemExit(1)


def _show_session(
    archive: ArchiveStore,
    session_dir: Path,
    session_id: str,
    *,
    max_events: int,
) -> dict[str, Any]:
    try:
        overview = archive.get_session_overview(session_id)
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "archive_path": str(archive.db_path),
            "session_id": session_id,
        }

    session = overview["session"]
    memories = archive.list_memories(session_id=session_id, limit=20)
    snapshot = _load_snapshot(session_dir, session_id)
    timeline = build_session_timeline(snapshot, max_events=max_events)
    return {
        "success": True,
        "archive_path": str(archive.db_path),
        "session_dir": str(session_dir),
        "session": _session_to_dict(session),
        "overview": {
            "memory_count": overview["memory_count"],
            "last_memory_at": overview["last_memory_at"],
            "memory_types": overview["memory_types"],
        },
        "snapshot": _snapshot_preview(snapshot),
        "timeline_summary": summarize_timeline(timeline),
        "timeline": timeline,
        "memories": [
            {
                "id": memory.id,
                "type": memory.type,
                "token_count": memory.token_count,
                "created_at": memory.created_at,
                "content": memory.content,
                "metadata": memory.metadata or {},
            }
            for memory in memories
        ],
    }


def _session_to_dict(session: ArchiveSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "name": session.name,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "summary": session.summary,
    }


def _load_snapshot(session_dir: Path, session_id: str) -> dict[str, Any] | None:
    path = session_dir / f"{session_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _snapshot_preview(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    if not snapshot:
        return None
    messages = [
        message for message in snapshot.get("messages", [])
        if message.get("role") in {"user", "assistant"}
    ]
    return {
        "created_at": snapshot.get("created_at"),
        "updated_at": snapshot.get("updated_at"),
        "llm": snapshot.get("llm") or {},
        "stats": snapshot.get("stats") or {},
        "recent_messages": [
            {
                "role": message.get("role"),
                "content": _truncate(str(message.get("content") or ""), 320),
            }
            for message in messages[-6:]
        ],
    }


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)] + "..."


def _default_archive_path() -> Path:
    return Path.home() / ".comsol_agent" / "archive" / "archive.sqlite3"


def _default_session_dir() -> Path:
    return Path.home() / ".comsol_agent" / "sessions"


if __name__ == "__main__":
    main()
