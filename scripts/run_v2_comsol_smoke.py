"""Run the explicit M5 real-COMSOL lifecycle smoke gate."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from comsol_agent.v2.runtime.comsol import (
    ArtifactStore,
    ComsolRuntime,
    InProcessWorkerExecutor,
    ModelCloseRequest,
    ModelCreateRequest,
    ModelSaveRequest,
    MphBackendAdapter,
)


async def run(version: str, cores: int) -> dict[str, object]:
    run_id = f"m5-smoke-{uuid4().hex}"
    model_id = f"scratch-{uuid4().hex}"
    with tempfile.TemporaryDirectory(prefix="comsol-agent-m5-smoke-") as temporary:
        root = Path(temporary)
        backend = MphBackendAdapter(version=version, cores=cores, port=0)
        runtime = ComsolRuntime(
            backend=backend,
            artifacts=ArtifactStore(root),
            worker=InProcessWorkerExecutor(backend),
        )
        try:
            created = await runtime.create_model(
                ModelCreateRequest(run_id=run_id, model_id=model_id)
            )
            if not created.success:
                raise RuntimeError(
                    created.failure.model_dump_json() if created.failure else created
                )
            saved = await runtime.save_model(
                ModelSaveRequest(
                    run_id=run_id,
                    model_id=model_id,
                    target_name="empty-smoke.mph",
                )
            )
            if not saved.success or not saved.artifacts:
                raise RuntimeError(saved.failure.model_dump_json() if saved.failure else saved)
            closed = await runtime.close_model(ModelCloseRequest(run_id=run_id, model_id=model_id))
            if not closed.success:
                raise RuntimeError(closed.failure.model_dump_json() if closed.failure else closed)
            return {
                "success": True,
                "gate": "real_comsol_lifecycle_smoke",
                "run_id": run_id,
                "model_id": model_id,
                "comsol_version": backend.capabilities.comsol_version,
                "mph_version": backend.capabilities.backend_version,
                "artifact_sha256": saved.artifacts[0].sha256,
                "artifact_size_bytes": saved.artifacts[0].size_bytes,
                "physical_solve_audit": "not_exercised_by_m5_lifecycle_smoke",
            }
        finally:
            await runtime.stop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="6.2")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--evidence-path", default=None)
    arguments = parser.parse_args()
    result = asyncio.run(run(arguments.version, arguments.cores))
    if arguments.evidence_path:
        target = Path(arguments.evidence_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
