"""Export archive indexes and memory records for audit/review."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from comsol_agent.memory.archive_store import ArchiveStore
from comsol_agent.memory.session_timeline import build_session_timeline, summarize_timeline


def export_archive_bundle(
    archive_store: ArchiveStore,
    *,
    output_path: str | Path | None = None,
    session_dir: str | Path | None = None,
    limit: int = 100,
    include_timelines: bool = False,
    max_events: int = 50,
) -> dict[str, Any]:
    """Export archive records to a JSON file and return a compact manifest."""
    limit = max(1, int(limit))
    sessions = archive_store.list_sessions(limit=limit)
    memories = archive_store.list_memories(limit=limit)
    templates = archive_store.list_templates(limit=limit)
    artifacts = archive_store.list_simulation_artifacts(kind=None, limit=limit)

    session_root = Path(session_dir).expanduser() if session_dir else None
    payload: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "archive_path": str(archive_store.db_path),
        "limits": {
            "limit": limit,
            "include_timelines": include_timelines,
            "max_events": max_events,
        },
        "counts": {
            "sessions": len(sessions),
            "memories": len(memories),
            "templates": len(templates),
            "simulation_artifacts": len(artifacts),
        },
        "sessions": [_session_record(session, session_root, include_timelines, max_events) for session in sessions],
        "memories": [asdict(memory) for memory in memories],
        "templates": [asdict(template) for template in templates],
        "simulation_artifacts": [asdict(artifact) for artifact in artifacts],
    }

    target = Path(output_path).expanduser() if output_path else _default_output_path()
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    return {
        "success": True,
        "path": str(target),
        "size_bytes": target.stat().st_size,
        "archive_path": str(archive_store.db_path),
        "counts": payload["counts"],
        "include_timelines": include_timelines,
    }


def _session_record(
    session: Any,
    session_dir: Path | None,
    include_timelines: bool,
    max_events: int,
) -> dict[str, Any]:
    record = asdict(session)
    if not include_timelines or session_dir is None:
        return record

    snapshot = _load_snapshot(session_dir, session.id)
    timeline = build_session_timeline(snapshot, max_events=max_events)
    record["snapshot"] = _snapshot_summary(snapshot)
    record["timeline_summary"] = summarize_timeline(timeline)
    record["timeline"] = timeline
    return record


def _load_snapshot(session_dir: Path, session_id: str) -> dict[str, Any] | None:
    path = session_dir / f"{session_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _snapshot_summary(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    if not snapshot:
        return None
    return {
        "created_at": snapshot.get("created_at"),
        "updated_at": snapshot.get("updated_at"),
        "llm": snapshot.get("llm") or {},
        "stats": snapshot.get("stats") or {},
        "repair_report_count": len(snapshot.get("repair_reports") or []),
    }


def _default_output_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return Path("runtime_smoke/archive_exports") / f"archive_export_{timestamp}.json"
