"""Pinned Function boundary from Kernel Actions to the bearing runtime workflow."""

from __future__ import annotations

from time import monotonic
from typing import Any, Protocol

from pydantic import Field

from comsol_agent.v2.contracts import Action, ArtifactRef, Observation, SourceRef
from comsol_agent.v2.contracts.models import ContractModel
from comsol_agent.v2.extensions import (
    API_VERSION,
    ExtensionKind,
    ExtensionManifest,
    ExtensionSnapshot,
    HealthReport,
    HealthStatus,
    PermissionSet,
    ResolutionContext,
)
from comsol_agent.v2.kernel import CancellationToken
from comsol_agent.v2.runtime.comsol import (
    ComsolRuntime,
    PinnedExecutionCatalog,
    RegisteredHandlerBinding,
    RuntimeRunRequest,
)

from .models import BearingSpec

WORKFLOW_CAPABILITY = "bearing.workflow.execute"


class FailureRouter(Protocol):
    async def route(
        self, observation: Observation, cancellation: CancellationToken
    ) -> dict[str, Any]: ...


class CapabilityPin(ContractModel):
    extension_id: str
    extension_version: str
    extension_kind: ExtensionKind
    capability: str


class BearingWorkflowRequest(ContractModel):
    route: str = Field(pattern="^(noop|clarification|parameter_override|deterministic_rebuild)$")
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    model_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    requested: BearingSpec
    previous: BearingSpec | None = None
    resume_checkpoint: str | None = None
    bindings: tuple[CapabilityPin, ...] = Field(min_length=1)
    timeout_seconds: float = Field(default=3600, gt=0, le=86400)


class BearingWorkflowResult(ContractModel):
    route: str
    runtime: dict[str, Any] | None = None
    audits: dict[str, Any] = Field(default_factory=dict)
    strict_audit_passed: bool = False
    comsol_called: bool = False


class BearingWorkflowTool:
    """Registered Function tool; the domain-neutral Kernel only sees its schemas."""

    input_schema = BearingWorkflowRequest.model_json_schema()
    output_schema = BearingWorkflowResult.model_json_schema()
    read_only = False
    idempotent = False
    timeout_seconds = 86400.0
    retryable_errors = frozenset()
    side_effects = ("COMSOL model state", "content-addressed artifacts")

    def __init__(
        self, runtime: ComsolRuntime, *, failure_router: FailureRouter | None = None
    ) -> None:
        self.runtime = runtime
        self.failure_router = failure_router
        self.snapshot: ExtensionSnapshot | None = None
        self.active = False
        self.manifest = ExtensionManifest(
            api_version=API_VERSION,
            kind=ExtensionKind.FUNCTION,
            id="bearing.workflow.function",
            version="1.0.0",
            enabled=True,
            entrypoint=(
                "comsol_agent.v2.domains.bearing.workflow:bearing_workflow_extension"
            ),
            description="Pinned bearing A-D workflow exposed as a controlled Function tool.",
            capabilities=[WORKFLOW_CAPABILITY],
            compatibility={"agent_api": ">=2.0,<3", "comsol": ["6.x"]},
            permissions=PermissionSet(
                filesystem="write", shell="none", comsol="solve", network="none"
            ),
            priority=100,
            quality=1.0,
            metadata={"domain": "bearing", "kernel_hardcoding": False},
        )

    def bind_snapshot(self, snapshot: ExtensionSnapshot) -> None:
        if self.snapshot is not None and self.snapshot is not snapshot:
            raise RuntimeError("workflow tool is already bound to another snapshot")
        self.snapshot = snapshot
        bindings: list[RegisteredHandlerBinding] = []
        for kind, capability in (
            (ExtensionKind.BUILDER, "bearing.cylindrical-roller.build"),
            (ExtensionKind.DETERMINISTIC_PATH, "bearing.parameter-override"),
            (
                ExtensionKind.DETERMINISTIC_PATH,
                "bearing.dynamic-load-continuation",
            ),
        ):
            extension = snapshot.resolve(
                kind, capability, ResolutionContext(domain="bearing")
            )[0]
            bindings.append(
                RegisteredHandlerBinding(
                    extension=extension,
                    extension_id=extension.manifest.id,
                    extension_version=extension.manifest.version,
                    extension_kind=kind,
                    capability=capability,
                    handler=extension.execute_model,
                )
            )
        self.runtime.backend.execution_catalog = PinnedExecutionCatalog(
            snapshot, bindings
        )

    async def activate(self) -> None:
        self.active = True

    async def deactivate(self) -> None:
        self.active = False

    async def health(self) -> HealthReport:
        return HealthReport(
            extension_id=self.manifest.id,
            status=HealthStatus.HEALTHY if self.active else HealthStatus.DISABLED,
        )

    def supports(self, context: ResolutionContext) -> bool:
        return context.domain in {None, "bearing"}

    async def execute(
        self, action: Action, cancellation: CancellationToken
    ) -> Observation:
        started = monotonic()
        request = BearingWorkflowRequest.model_validate(action.arguments)
        snapshot = self.snapshot
        if snapshot is None:
            raise RuntimeError("workflow has no pinned ExtensionSnapshot")
        pins = {(pin.extension_kind, pin.capability): pin for pin in request.bindings}
        for pin in request.bindings:
            resolved = snapshot.resolve(
                pin.extension_kind,
                pin.capability,
                ResolutionContext(selected_extension_id=pin.extension_id),
            )
            if len(resolved) != 1 or resolved[0].manifest.version != pin.extension_version:
                raise ValueError(
                    f"forged or unavailable binding: {pin.extension_id}:{pin.capability}"
                )

        if request.route in {"noop", "clarification"}:
            data = BearingWorkflowResult(
                route=request.route,
                strict_audit_passed=request.route == "noop",
                comsol_called=False,
            )
            return self._observation(action, data, started, success=True)

        builder = _required_pin(
            pins, ExtensionKind.BUILDER, "bearing.cylindrical-roller.build"
        )
        continuation = _required_pin(
            pins,
            ExtensionKind.DETERMINISTIC_PATH,
            "bearing.dynamic-load-continuation",
        )
        override = pins.get(
            (ExtensionKind.DETERMINISTIC_PATH, "bearing.parameter-override")
        )
        if request.route == "parameter_override" and (
            request.previous is None or request.resume_checkpoint is None or override is None
        ):
            raise ValueError(
                "parameter_override requires previous spec, B checkpoint and pinned path"
            )
        runtime_request = RuntimeRunRequest(
            run_id=request.run_id,
            model_id=request.model_id,
            builder_id=builder.extension_id,
            builder_capability=builder.capability,
            builder_version=builder.extension_version,
            extension_versions=dict(snapshot.versions),
            parameters=request.requested.comsol_parameters(),
            specification=_specification(request.requested),
            previous_parameters=(
                request.previous.comsol_parameters() if request.previous else None
            ),
            previous_specification=(
                _specification(request.previous) if request.previous else None
            ),
            override_extension_id=override.extension_id if override else None,
            override_extension_capability=override.capability if override else None,
            override_extension_version=override.extension_version if override else None,
            continuation_extension_id=continuation.extension_id,
            continuation_extension_capability=continuation.capability,
            continuation_extension_version=continuation.extension_version,
            expressions=("solid.mises", "solid.disp"),
            timeout_seconds=request.timeout_seconds,
            resume_checkpoint=request.resume_checkpoint,
        )
        result = await self.runtime.run(runtime_request, cancellation)
        audits = (
            await self._audits(request.requested, result.data.get("audit", {}), pins)
            if result.success
            else {}
        )
        strict = bool(result.success and audits and all(item["passed"] for item in audits.values()))
        data = BearingWorkflowResult(
            route=request.route,
            runtime=result.model_dump(mode="json"),
            audits=audits,
            strict_audit_passed=strict,
            comsol_called=True,
        )
        artifacts = [
            ArtifactRef(
                uri=artifact.path,
                media_type=artifact.media_type,
                sha256=artifact.sha256,
                source=SourceRef(
                    kind="comsol_runtime",
                    identifier=artifact.provenance.run_id,
                    version=artifact.provenance.comsol_version,
                ),
            )
            for artifact in result.artifacts
        ]
        observation = self._observation(
            action,
            data,
            started,
            success=strict,
            artifacts=artifacts,
            checkpoint=result.checkpoint.manifest_path if result.checkpoint else None,
            error_class=(
                None
                if strict
                else (
                    result.failure.error_class.value
                    if result.failure
                    else "physics_audit_failure"
                )
            ),
        )
        if not observation.success and self.failure_router is not None:
            observation.data["repair"] = await self.failure_router.route(
                observation, cancellation
            )
        return observation

    async def _audits(
        self,
        spec: BearingSpec,
        runtime_audit: dict[str, Any],
        pins: dict[tuple[ExtensionKind, str], CapabilityPin],
    ) -> dict[str, Any]:
        snapshot = self.snapshot
        assert snapshot is not None
        subjects = {
            "bearing.geometry.audit": spec,
            "bearing.selection.audit": {"spec": spec, **runtime_audit},
            "bearing.contact.audit": runtime_audit,
            "bearing.physics.audit": {"spec": spec, **runtime_audit},
        }
        reports: dict[str, Any] = {}
        for capability, subject in subjects.items():
            pin = _required_pin(pins, ExtensionKind.AUDITOR, capability)
            extension = snapshot.resolve(
                ExtensionKind.AUDITOR,
                capability,
                ResolutionContext(selected_extension_id=pin.extension_id),
            )[0]
            reports[capability] = await extension.audit(subject)
        return reports

    def _observation(
        self,
        action: Action,
        data: BearingWorkflowResult,
        started: float,
        *,
        success: bool,
        artifacts: list[ArtifactRef] | None = None,
        checkpoint: str | None = None,
        error_class: str | None = None,
    ) -> Observation:
        payload = data.model_dump(mode="json")
        runtime_failure = (payload.get("runtime") or {}).get("failure")
        if runtime_failure:
            payload["failure"] = runtime_failure
        return Observation(
            action_id=action.action_id,
            success=success,
            status="completed" if success else "failed",
            stage="bearing_workflow",
            data=payload,
            artifacts=artifacts or [],
            audits=list(data.audits.values()),
            error_class=error_class,
            retryable=False,
            checkpoint=checkpoint,
            duration_ms=(monotonic() - started) * 1000,
            source=SourceRef(
                kind="function",
                identifier=self.manifest.id,
                version=self.manifest.version,
            ),
        )


def _required_pin(
    pins: dict[tuple[ExtensionKind, str], CapabilityPin],
    kind: ExtensionKind,
    capability: str,
) -> CapabilityPin:
    try:
        return pins[(kind, capability)]
    except KeyError as exc:
        raise ValueError(f"missing pinned capability: {kind.value}:{capability}") from exc


def _specification(spec: BearingSpec) -> dict[str, Any]:
    return spec.model_dump(
        mode="json",
        exclude={"topology_signature", "build_signature", "provenance"},
    )


def bearing_workflow_extension(*, manifest: ExtensionManifest, config: dict[str, Any]) -> Any:
    raise RuntimeError("BearingWorkflowTool requires an injected ComsolRuntime")
