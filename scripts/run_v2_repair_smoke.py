"""Run the isolated M6 real-COMSOL API error/repair/checkpoint smoke gate."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from comsol_agent.v2.contracts import Observation, SourceRef
from comsol_agent.v2.extensions import (
    API_VERSION,
    CompatibilityPolicy,
    ExtensionKind,
    ExtensionLoader,
    ExtensionManifest,
    ExtensionRegistry,
    HealthReport,
    HealthStatus,
    PermissionPolicy,
    PermissionSet,
)
from comsol_agent.v2.kernel import CancellationToken
from comsol_agent.v2.repair import (
    AffectedScope,
    Diagnosis,
    DiagnosticService,
    ErrorCode,
    RepairCandidate,
    RepairKind,
    RepairOrchestrator,
    RepairRuleContract,
    VersionCompatibility,
)
from comsol_agent.v2.runtime.comsol import (
    ArtifactStore,
    CheckpointCreateRequest,
    CheckpointRestoreRequest,
    ComsolRuntime,
    FailureInspectRequest,
    InProcessWorkerExecutor,
    ModelCloseRequest,
    ModelCreateRequest,
    MphBackendAdapter,
    PinnedExecutionCatalog,
    RegisteredExecutionRequest,
    RegisteredHandlerBinding,
    RuntimeStage,
)


def manifest(
    extension_id: str,
    kind: ExtensionKind,
    capability: str,
    *,
    repair_contract: RepairRuleContract | None = None,
) -> ExtensionManifest:
    return ExtensionManifest(
        api_version=API_VERSION,
        kind=kind,
        id=extension_id,
        version="1.0.0",
        enabled=True,
        entrypoint="scripts.run_v2_repair_smoke:SmokeExtension",
        description="isolated M6 real COMSOL smoke fixture",
        capabilities=[capability],
        compatibility={"agent_api": ">=2.0,<3", "comsol": ["6.x"]},
        permissions={
            "filesystem": "none",
            "shell": "none",
            "comsol": "model_write",
            "network": "none",
        },
        priority=100,
        quality=1.0,
        metadata={"provenance": "scripts/run_v2_repair_smoke.py"},
        repair_contract=(
            repair_contract.model_dump(mode="json") if repair_contract else None
        ),
    )


class SmokeExtension:
    def __init__(self, extension_manifest: ExtensionManifest) -> None:
        self.manifest = extension_manifest
        self.active = False

    async def activate(self) -> None:
        self.active = True

    async def deactivate(self) -> None:
        self.active = False

    async def health(self) -> HealthReport:
        return HealthReport(
            extension_id=self.manifest.id,
            status=HealthStatus.HEALTHY if self.active else HealthStatus.DISABLED,
        )

    def supports(self, context: Any) -> bool:
        return True

    def preconditions(self, context: Any) -> tuple[str, ...]:
        return ()

    def steps(self) -> tuple[str, ...]:
        return (self.manifest.capabilities[0],)

    def rollback(self) -> dict[str, Any]:
        return {"checkpoint": "B"}

    def acceptance(self) -> tuple[str, ...]:
        return ("api_call_succeeds",)


class SetupPath(SmokeExtension):
    def execute_model(self, handle: Any, specification: dict[str, Any]) -> dict[str, Any]:
        java = handle.mph_model.java
        java.component().create("comp1", True)
        java.component("comp1").geom().create("geom1", 3)
        java.component("comp1").geom("geom1").feature().create("blk1", "Block")
        java.component("comp1").geom("geom1").feature("blk1").set(
            "size", ["1", "1", "1"]
        )
        return {"setup": True}


class InvalidPropertyPath(SmokeExtension):
    def execute_model(self, handle: Any, specification: dict[str, Any]) -> dict[str, Any]:
        handle.mph_model.java.component("comp1").geom("geom1").feature("blk1").set(
            "m6_definitely_invalid_property", "1"
        )
        return {"unexpected": "invalid property was accepted"}


class RepairPath(SmokeExtension):
    def execute_model(self, handle: Any, specification: dict[str, Any]) -> dict[str, Any]:
        handle.mph_model.java.component("comp1").geom("geom1").feature("blk1").set(
            "size", ["2", "2", "2"]
        )
        return {"property": "size", "value": ["2", "2", "2"]}


class VerifyPath(RepairPath):
    pass


class PropertyRepairRule(SmokeExtension):
    def __init__(self) -> None:
        self.repair_contract = RepairRuleContract(
            error_classes=frozenset({"api_code_error"}),
            error_codes=frozenset({ErrorCode.INVALID_PROPERTY}),
            stages=frozenset({RuntimeStage.BUILD}),
            preconditions=("compatible_checkpoint",),
            modification_scope=AffectedScope(
                kind="property", targets=("component.comp1.geom1.blk1.size",)
            ),
            required_permissions=frozenset({"comsol:model_write"}),
            max_attempts=1,
            verifier="comsol.api-probe",
            rollback_required=True,
            compatibility=VersionCompatibility(agent_api=">=2.0,<3", comsol=("6.x",)),
            provenance="scripts/run_v2_repair_smoke.py",
        )
        super().__init__(
            manifest(
                "smoke.property-rule",
                ExtensionKind.REPAIR_RULE,
                "repair",
                repair_contract=self.repair_contract,
            )
        )
        self.diagnosis: Diagnosis | None = None

    def matches(self, observation: Observation, context: Any) -> bool:
        return self.diagnosis is not None

    async def propose(self, observation: Observation) -> dict[str, Any]:
        assert self.diagnosis is not None
        return RepairCandidate(
            kind=RepairKind.DETERMINISTIC_RULE,
            observation_id=observation.observation_id,
            diagnosis_fingerprint=self.diagnosis.fingerprint,
            scope=self.repair_contract.modification_scope,
            permissions=frozenset({"comsol:model_write"}),
            verifier=self.repair_contract.verifier,
            payload={"path": "smoke.repair"},
            provenance="extension:smoke.property-rule",
            required_gates=frozenset({"api"}),
        ).model_dump(mode="json")

    async def verify(self, observation: Observation) -> bool:
        return observation.success


class RuntimeRepairExecutor:
    def __init__(
        self, runtime: ComsolRuntime, model_id: str, checkpoint_manifest: str
    ) -> None:
        self.runtime = runtime
        self.model_id = model_id
        self.checkpoint_manifest = checkpoint_manifest

    async def create_checkpoint(
        self, diagnosis: Diagnosis, candidate: RepairCandidate
    ) -> str:
        return self.checkpoint_manifest

    async def apply(self, candidate: RepairCandidate, limits: Any) -> None:
        restored = await self.runtime.restore_model(
            CheckpointRestoreRequest(
                run_id=f"restore-{uuid4().hex}",
                model_id=self.model_id,
                manifest_path=self.checkpoint_manifest,
                builder_id="smoke.setup",
                builder_capability="smoke.setup",
                builder_version="1.0.0",
                extension_versions={"smoke.setup": "1.0.0"},
            )
        )
        if not restored.success:
            raise RuntimeError(restored.failure)
        repaired = await self.runtime.execute_registered(
            RegisteredExecutionRequest(
                run_id=f"repair-{uuid4().hex}",
                model_id=self.model_id,
                extension_id="smoke.repair",
                extension_version="1.0.0",
                extension_kind="deterministic_path",
                capability="smoke.repair",
            )
        )
        if not repaired.success:
            raise RuntimeError(repaired.failure)

    async def verify(
        self, candidate: RepairCandidate, trigger: Observation
    ) -> Observation:
        verified = await self.runtime.execute_registered(
            RegisteredExecutionRequest(
                run_id=f"verify-{uuid4().hex}",
                model_id=self.model_id,
                extension_id="smoke.verify",
                extension_version="1.0.0",
                extension_kind="deterministic_path",
                capability="smoke.verify",
            )
        )
        return Observation(
            action_id="real-comsol-verify",
            success=verified.success,
            status=verified.status,
            stage="build",
            data={"gates": {"api": verified.success}},
            error_class=None if verified.success else "runtime_failure",
            retryable=not verified.success,
            checkpoint=self.checkpoint_manifest,
            source=SourceRef(kind="comsol", identifier="real-6.2"),
        )

    async def rollback(self, checkpoint: str) -> None:
        restored = await self.runtime.restore_model(
            CheckpointRestoreRequest(
                run_id=f"rollback-{uuid4().hex}",
                model_id=self.model_id,
                manifest_path=checkpoint,
                builder_id="smoke.setup",
                builder_capability="smoke.setup",
                builder_version="1.0.0",
                extension_versions={"smoke.setup": "1.0.0"},
            )
        )
        if not restored.success:
            raise RuntimeError(restored.failure)

    async def commit(self, checkpoint: str) -> None:
        return None


async def run(version: str, cores: int) -> dict[str, object]:
    run_id = f"m6-smoke-{uuid4().hex}"
    model_id = f"scratch-{uuid4().hex}"
    with tempfile.TemporaryDirectory(prefix="comsol-agent-m6-smoke-") as temporary:
        root = Path(temporary)
        registry = ExtensionRegistry(
            ExtensionLoader(
                compatibility=CompatibilityPolicy(
                    agent_version="2.0.0", comsol_version=version
                ),
                permissions=PermissionPolicy(
                    PermissionSet(
                        filesystem="none",
                        shell="none",
                        comsol="model_write",
                        network="none",
                    )
                ),
                trusted_manifest_roots=(root,),
                trusted_code_roots=(Path(__file__).parents[1],),
            )
        )
        setup = SetupPath(manifest("smoke.setup", ExtensionKind.DETERMINISTIC_PATH, "smoke.setup"))
        invalid = InvalidPropertyPath(
            manifest("smoke.invalid", ExtensionKind.DETERMINISTIC_PATH, "smoke.invalid")
        )
        repair = RepairPath(
            manifest("smoke.repair", ExtensionKind.DETERMINISTIC_PATH, "smoke.repair")
        )
        verify = VerifyPath(
            manifest("smoke.verify", ExtensionKind.DETERMINISTIC_PATH, "smoke.verify")
        )
        rule = PropertyRepairRule()
        for extension in (setup, invalid, repair, verify, rule):
            registration = await registry.register(extension)
            if registration.error:
                raise RuntimeError(registration.error)
        async with registry.snapshot() as snapshot:
            catalog = PinnedExecutionCatalog(
                snapshot,
                [
                    RegisteredHandlerBinding(
                        extension=item,
                        extension_id=item.manifest.id,
                        extension_version=item.manifest.version,
                        extension_kind=ExtensionKind.DETERMINISTIC_PATH,
                        capability=item.manifest.capabilities[0],
                        handler=item.execute_model,
                    )
                    for item in (setup, invalid, repair, verify)
                ],
            )
            backend = MphBackendAdapter(
                version=version, cores=cores, port=0, execution_catalog=catalog
            )
            runtime = ComsolRuntime(
                backend=backend,
                artifacts=ArtifactStore(root),
                worker=InProcessWorkerExecutor(backend),
            )
            try:
                created = await runtime.create_model(
                    ModelCreateRequest(run_id=f"create-{run_id}", model_id=model_id)
                )
                if not created.success:
                    raise RuntimeError(created.failure)
                prepared = await runtime.execute_registered(
                    RegisteredExecutionRequest(
                        run_id=f"setup-{run_id}",
                        model_id=model_id,
                        extension_id="smoke.setup",
                        extension_version="1.0.0",
                        extension_kind="deterministic_path",
                        capability="smoke.setup",
                    )
                )
                if not prepared.success:
                    raise RuntimeError(prepared.failure)
                checkpoint = await runtime.create_checkpoint(
                    CheckpointCreateRequest(
                        run_id=f"checkpoint-{run_id}",
                        model_id=model_id,
                        stage=RuntimeStage.BUILD,
                        builder_id="smoke.setup",
                        builder_capability="smoke.setup",
                        builder_version="1.0.0",
                        extension_versions={"smoke.setup": "1.0.0"},
                        model_summary={"fixture": "property-error"},
                    )
                )
                failed_run = f"invalid-{run_id}"
                failed = await runtime.execute_registered(
                    RegisteredExecutionRequest(
                        run_id=failed_run,
                        model_id=model_id,
                        extension_id="smoke.invalid",
                        extension_version="1.0.0",
                        extension_kind="deterministic_path",
                        capability="smoke.invalid",
                    )
                )
                if failed.success:
                    raise RuntimeError("expected the real COMSOL property call to fail")
                failure = runtime.inspect_failure(
                    FailureInspectRequest(run_id=run_id, target_run_id=failed_run)
                )
                if failure is None:
                    raise RuntimeError("runtime failure index did not preserve the error")
                trigger = Observation(
                    action_id="real-comsol-invalid-property",
                    success=False,
                    status=failed.status,
                    stage="build",
                    data={"operation": "execute_registered"},
                    error_class="runtime_failure",
                    exception_type=failure.causes[0].exception_type,
                    retryable=failure.retryable,
                    checkpoint=checkpoint.manifest_path,
                    source=SourceRef(kind="comsol", identifier=f"real-{version}"),
                )
                diagnosis = DiagnosticService().from_runtime(
                    failure,
                    observation=trigger,
                    affected_scope=rule.repair_contract.modification_scope,
                    suspected_component="component.comp1.geom1.blk1",
                )
                if diagnosis.error_code != ErrorCode.INVALID_PROPERTY:
                    raise RuntimeError(
                        f"expected INVALID_PROPERTY, got {diagnosis.error_code}: {failure.message}"
                    )
                rule.diagnosis = diagnosis
                result = await RepairOrchestrator(
                    diagnostics=DiagnosticService(),
                    snapshot=snapshot,
                    executor=RuntimeRepairExecutor(
                        runtime, model_id, checkpoint.manifest_path
                    ),
                ).repair(trigger, diagnosis, cancellation=CancellationToken())
                if result.status != "completed":
                    raise RuntimeError(result.model_dump_json())
                closed = await runtime.close_model(
                    ModelCloseRequest(run_id=f"close-{run_id}", model_id=model_id)
                )
                return {
                    "success": closed.success,
                    "gate": "real_comsol_api_repair_smoke",
                    "run_id": run_id,
                    "model_id": model_id,
                    "comsol_version": backend.capabilities.comsol_version,
                    "mph_version": backend.capabilities.backend_version,
                    "error_code": diagnosis.error_code,
                    "cause_chain": [
                        item.model_dump(mode="json") for item in diagnosis.exception_chain
                    ],
                    "checkpoint_sha256": checkpoint.model_sha256,
                    "repair_status": result.status,
                    "trace": [event.event for event in result.trace],
                    "physical_solve_audit": "not_exercised_by_m6_api_smoke",
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
