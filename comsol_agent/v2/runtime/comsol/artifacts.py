"""Isolated, content-addressed artifact and checkpoint storage."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from .contracts import (
    RUNTIME_SCHEMA_VERSION,
    Checkpoint,
    RuntimeArtifact,
    RuntimeProvenance,
    RuntimeStage,
)
from .errors import CheckpointCompatibilityError


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode()
    return hashlib.sha256(payload).hexdigest()


class ArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def run_directory(self, run_id: str, model_id: str) -> Path:
        directory = (self.root / run_id / model_id).resolve()
        if not directory.is_relative_to(self.root):
            raise ValueError("artifact directory escapes the configured root")
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def target(self, run_id: str, model_id: str, name: str) -> Path:
        if Path(name).name != name or name in {"", ".", ".."}:
            raise ValueError("artifact name must be a single safe path component")
        target = (self.run_directory(run_id, model_id) / name).resolve()
        if not target.is_relative_to(self.run_directory(run_id, model_id)):
            raise ValueError("artifact target escapes its isolated run directory")
        return target

    def record(
        self,
        path: Path,
        *,
        stage: RuntimeStage,
        provenance: RuntimeProvenance,
        media_type: str,
    ) -> RuntimeArtifact:
        resolved = path.resolve(strict=True)
        run_root = self.run_directory(provenance.run_id, provenance.model_id)
        if not resolved.is_relative_to(run_root):
            raise ValueError("artifact was not created inside its isolated run directory")
        content = resolved.read_bytes()
        return RuntimeArtifact(
            artifact_id=uuid4().hex,
            path=str(resolved),
            relative_path=str(resolved.relative_to(run_root)),
            media_type=media_type,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            stage=stage,
            provenance=provenance,
        )

    def write_json(
        self,
        run_id: str,
        model_id: str,
        name: str,
        value: object,
    ) -> Path:
        target = self.target(run_id, model_id, name)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
        return target

    def persist_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        path = self.write_json(
            checkpoint.provenance.run_id,
            checkpoint.provenance.model_id,
            f"{checkpoint.checkpoint_id}.checkpoint.json",
            checkpoint.model_dump(mode="json"),
        )
        return checkpoint.model_copy(update={"manifest_path": str(path)})

    def read_checkpoint(self, manifest_path: str | Path) -> Checkpoint:
        path = Path(manifest_path).resolve(strict=True)
        if not path.is_relative_to(self.root):
            raise CheckpointCompatibilityError("checkpoint manifest is outside artifact root")
        try:
            checkpoint = Checkpoint.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CheckpointCompatibilityError(f"invalid checkpoint manifest: {exc}") from exc
        return checkpoint.model_copy(update={"manifest_path": str(path)})

    @staticmethod
    def verify_artifact(artifact: RuntimeArtifact) -> None:
        path = Path(artifact.path)
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise CheckpointCompatibilityError(f"checkpoint artifact is unreadable: {exc}") from exc
        digest = hashlib.sha256(content).hexdigest()
        if digest != artifact.sha256:
            raise CheckpointCompatibilityError("checkpoint artifact hash mismatch")
        if len(content) != artifact.size_bytes:
            raise CheckpointCompatibilityError("checkpoint artifact size mismatch")

    @staticmethod
    def verify_schema(checkpoint: Checkpoint) -> None:
        if checkpoint.schema_version != RUNTIME_SCHEMA_VERSION:
            raise CheckpointCompatibilityError(
                f"checkpoint schema {checkpoint.schema_version} is not {RUNTIME_SCHEMA_VERSION}"
            )
