"""Conservative backfill from existing V2 RunManifest artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import Field

from comsol_agent.v2.contracts import SourceRef
from comsol_agent.v2.contracts.models import ContractModel

from .contracts import (
    MemoryCompatibility,
    MemoryLayer,
    MemoryProvenance,
    MemoryQuality,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
)
from .governance import MemoryGovernance


class MigrationIssue(ContractModel):
    path: str
    reason: str


class MigrationReport(ContractModel):
    imported_ids: list[str] = Field(default_factory=list)
    skipped: list[MigrationIssue] = Field(default_factory=list)


class ManifestMigrator:
    """Imports historical manifests into quarantine; never auto-promotes them."""

    def __init__(self, governance: MemoryGovernance, *, agent_version: str) -> None:
        self.governance = governance
        self.agent_version = agent_version

    def migrate(self, paths: Iterable[Path]) -> MigrationReport:
        report = MigrationReport()
        existing_refs = {
            record.content_ref for record in self.governance.repository.records()
        }
        for source_path in paths:
            path = source_path.resolve()
            uri = path.as_uri()
            if uri in existing_refs:
                report.skipped.append(
                    MigrationIssue(path=str(path), reason="content_ref already imported")
                )
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                record = self._record(payload, path)
            except (OSError, ValueError, TypeError) as error:
                report.skipped.append(
                    MigrationIssue(path=str(path), reason=f"{type(error).__name__}: {error}")
                )
                continue
            report.imported_ids.append(self.governance.ingest(record))
            existing_refs.add(uri)
        return report

    def _record(self, payload: dict, path: Path) -> MemoryRecord:
        required = {"run_id", "goal", "status", "versions", "artifacts"}
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"not a V2 RunManifest; missing {sorted(missing)}")
        goal = payload["goal"]
        if not isinstance(goal, dict) or not goal.get("objective"):
            raise ValueError("manifest goal objective is missing")
        versions = payload["versions"] if isinstance(payload["versions"], dict) else {}
        code_hash = _combined_code_hash(payload.get("code_hashes", {}))
        git_commit = _valid_git_commit(versions.get("git_commit"))
        structured = {
            "original_request": goal["objective"],
            "normalized_request": goal["objective"],
            "run_status": payload["status"],
            "routing_decisions": payload.get("routing_decisions", []),
            "audit_evidence": payload.get("audits", []),
            "artifact_refs": payload.get("artifacts", []),
            "migration_note": (
                "Historical evidence only. Manual nomination and strict promotion are required."
            ),
        }
        domain = str(versions.get("domain", "unknown"))
        topology = versions.get("topology_signature")
        return MemoryRecord(
            layer=MemoryLayer.EPISODIC,
            type=MemoryType.CANDIDATE_CASE,
            status=MemoryStatus.QUARANTINED,
            summary=str(goal["objective"]),
            content_ref=path.as_uri(),
            structured=structured,
            provenance=MemoryProvenance(
                run_id=str(payload["run_id"]),
                git_commit=git_commit,
                code_hash=code_hash,
                comsol_version=versions.get("comsol"),
                agent_version=str(versions.get("agent", self.agent_version)),
                agent_schema=str(payload.get("schema_version", "unknown")),
                contract_version=str(payload.get("schema_version", "unknown")),
                producer=SourceRef(
                    kind="migration",
                    identifier="v2-run-manifest-backfill",
                    version="1.0",
                    uri=path.as_uri(),
                ),
            ),
            compatibility=MemoryCompatibility(
                domain=domain,
                topology_signature=str(topology) if topology else None,
                comsol=(f"=={versions['comsol']}" if versions.get("comsol") else ""),
                agent_api=(f"=={versions['agent']}" if versions.get("agent") else ""),
            ),
            quality=MemoryQuality(
                execution_passed=payload["status"] == "completed",
                physical_audit_passed=False,
            ),
        )


def _combined_code_hash(code_hashes: object) -> str | None:
    if not isinstance(code_hashes, dict) or not code_hashes:
        return None
    values = [value for value in code_hashes.values() if isinstance(value, str)]
    if not values or any(len(value) != 64 for value in values):
        return None
    canonical = json.dumps(code_hashes, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _valid_git_commit(value: object) -> str | None:
    if not isinstance(value, str) or not 7 <= len(value) <= 64:
        return None
    if any(character not in "0123456789abcdef" for character in value):
        return None
    return value
