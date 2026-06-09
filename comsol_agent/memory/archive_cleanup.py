"""Safe cleanup helpers for archived simulation artifact indexes."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from comsol_agent.memory.archive_store import ArchiveStore, SimulationArtifact


def cleanup_missing_artifact_indexes(
    archive_store: ArchiveStore,
    *,
    kind: str | None = None,
    limit: int = 100,
    apply: bool = False,
) -> dict[str, Any]:
    """Find and optionally delete artifact index rows whose files are missing."""
    artifacts = archive_store.list_simulation_artifacts(kind=kind, limit=max(1, int(limit)))
    stale = []
    for artifact in artifacts:
        missing = _missing_paths(artifact)
        if missing:
            stale.append(
                {
                    "run_id": artifact.run_id,
                    "kind": artifact.kind,
                    "model_name": artifact.model_name,
                    "missing_paths": missing,
                    "artifact": asdict(artifact),
                }
            )

    deleted = []
    if apply:
        for item in stale:
            if archive_store.delete_simulation_artifact(item["run_id"]):
                deleted.append(item["run_id"])

    return {
        "success": True,
        "archive_path": str(archive_store.db_path),
        "dry_run": not apply,
        "kind": kind,
        "scanned": len(artifacts),
        "stale_count": len(stale),
        "deleted_count": len(deleted),
        "deleted_run_ids": deleted,
        "stale": stale,
    }


def _missing_paths(artifact: SimulationArtifact) -> list[dict[str, str]]:
    paths = {
        "json_path": artifact.json_path,
        "manifest_path": artifact.manifest_path,
    }
    if artifact.csv_path:
        paths["csv_path"] = artifact.csv_path

    missing = []
    for field, raw_path in paths.items():
        if not raw_path:
            missing.append({"field": field, "path": ""})
            continue
        path = Path(raw_path).expanduser()
        if not path.exists():
            missing.append({"field": field, "path": str(path)})
    return missing
