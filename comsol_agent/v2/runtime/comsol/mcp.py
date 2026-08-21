"""Minimal typed MCP-tool extension surface for the COMSOL runtime."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from comsol_agent.v2.contracts import Action, Observation, SourceRef
from comsol_agent.v2.extensions import (
    API_VERSION,
    CompatibilitySpec,
    ExtensionKind,
    ExtensionManifest,
    HealthReport,
    HealthStatus,
    PermissionSet,
    ResolutionContext,
)
from comsol_agent.v2.kernel import CancellationToken

from .contracts import (
    CancelRunRequest,
    Checkpoint,
    CheckpointCreateRequest,
    CheckpointInspectRequest,
    CheckpointRestoreRequest,
    EvaluateRequest,
    ExportRequest,
    FailureInspectRequest,
    ModelActionRequest,
    ModelCloseRequest,
    ModelCreateRequest,
    ModelLoadRequest,
    ModelSaveRequest,
    ParameterPatchRequest,
    RegisteredExecutionRequest,
    RuntimeOperation,
    RuntimeResult,
    RuntimeRunRequest,
    SessionStatus,
    SessionStatusRequest,
)
from .service import ComsolRuntime

Handler = Callable[[BaseModel], Awaitable[Any] | Any]


class RuntimeMcpTool:
    """One capability per extension keeps every input schema operation-specific."""

    read_only = False
    idempotent = False
    timeout_seconds = 3600.0
    retryable_errors = frozenset({"resource_error", "timeout"})
    side_effects = ("COMSOL model state",)

    def __init__(
        self,
        *,
        capability: str,
        request_model: type[BaseModel],
        output_model: type[BaseModel],
        handler: Handler,
        permission: str,
        filesystem: str = "none",
        read_only: bool = False,
        idempotent: bool = False,
    ) -> None:
        self.capability = capability
        self.request_model = request_model
        self.output_model = output_model
        self.handler = handler
        self.read_only = read_only
        self.idempotent = idempotent
        suffix = capability.removeprefix("comsol.").replace("_", "-")
        self.manifest = ExtensionManifest(
            api_version=API_VERSION,
            kind=ExtensionKind.MCP_TOOL,
            id=f"comsol.runtime.{suffix}",
            version="0.5.0",
            enabled=True,
            entrypoint="comsol_agent.v2.runtime.comsol.mcp:RuntimeMcpTool",
            description=f"Controlled V2 COMSOL operation: {capability}",
            capabilities=[capability],
            compatibility=CompatibilitySpec(agent_api=">=2.0,<3", comsol=["6.x"]),
            permissions=PermissionSet(
                filesystem=filesystem,
                shell="none",
                comsol=permission,
                network="none",
            ),
            priority=100,
            quality=1.0,
        )
        self.input_schema = request_model.model_json_schema()
        self.output_schema = output_model.model_json_schema()
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

    def supports(self, context: ResolutionContext) -> bool:
        return context.domain in (None, "comsol")

    async def execute(self, action: Action, cancellation: CancellationToken) -> Observation:
        cancellation.raise_if_cancelled()
        request = self.request_model.model_validate(action.arguments)
        value = self.handler(request)
        if inspect.isawaitable(value):
            value = await value
        if not isinstance(value, self.output_model):
            value = self.output_model.model_validate(value)
        success = not isinstance(value, RuntimeResult) or value.success
        failure = value.failure if isinstance(value, RuntimeResult) else None
        return Observation(
            action_id=action.action_id,
            success=success,
            status=value.status if isinstance(value, RuntimeResult) else "completed",
            stage="comsol_runtime",
            data=value.model_dump(mode="json"),
            error_class=failure.error_class if failure else None,
            exception_type=failure.causes[0].exception_type if failure else None,
            retryable=failure.retryable if failure else False,
            checkpoint=(
                value.checkpoint.manifest_path
                if isinstance(value, RuntimeResult) and value.checkpoint
                else None
            ),
            source=SourceRef(
                kind="mcp_tool", identifier=self.manifest.id, version=self.manifest.version
            ),
        )


def build_mcp_tools(runtime: ComsolRuntime) -> list[RuntimeMcpTool]:
    async def runtime_status(_: SessionStatusRequest) -> SessionStatus:
        return await runtime.status()

    async def run_build(request: ModelActionRequest) -> RuntimeResult:
        return await runtime.model_action(request, RuntimeOperation.BUILD)

    async def run_mesh(request: ModelActionRequest) -> RuntimeResult:
        return await runtime.model_action(request, RuntimeOperation.MESH)

    async def run_solve(request: ModelActionRequest) -> RuntimeResult:
        return await runtime.model_action(request, RuntimeOperation.SOLVE)

    def inspect_checkpoint(request: CheckpointInspectRequest) -> Checkpoint:
        return runtime.inspect_checkpoint(request.manifest_path)

    async def restore_checkpoint(request: CheckpointRestoreRequest) -> Checkpoint:
        run_request = RuntimeRunRequest(
            run_id=request.run_id,
            model_id=request.model_id,
            builder_id=request.builder_id,
            builder_version=request.builder_version,
            extension_versions=request.extension_versions,
            specification=request.input_summary,
            resume_checkpoint=request.manifest_path,
        )
        return await runtime.restore_checkpoint(run_request)

    definitions: list[tuple[str, type[BaseModel], type[BaseModel], Handler, str, bool, bool]] = [
        (
            "comsol.runtime_status",
            SessionStatusRequest,
            SessionStatus,
            runtime_status,
            "model_read",
            True,
            True,
        ),
        (
            "comsol.create_model",
            ModelCreateRequest,
            RuntimeResult,
            runtime.create_model,
            "model_write",
            False,
            False,
        ),
        (
            "comsol.load_model",
            ModelLoadRequest,
            RuntimeResult,
            runtime.load_model,
            "model_write",
            False,
            False,
        ),
        (
            "comsol.save_model",
            ModelSaveRequest,
            RuntimeResult,
            runtime.save_model,
            "model_write",
            False,
            True,
        ),
        (
            "comsol.close_model",
            ModelCloseRequest,
            RuntimeResult,
            runtime.close_model,
            "model_write",
            False,
            True,
        ),
        (
            "comsol.apply_parameters",
            ParameterPatchRequest,
            RuntimeResult,
            runtime.apply_parameters,
            "model_write",
            False,
            True,
        ),
        (
            "comsol.execute_registered",
            RegisteredExecutionRequest,
            RuntimeResult,
            runtime.execute_registered,
            "model_write",
            False,
            False,
        ),
        ("comsol.build", ModelActionRequest, RuntimeResult, run_build, "model_write", False, False),
        ("comsol.mesh", ModelActionRequest, RuntimeResult, run_mesh, "model_write", False, False),
        ("comsol.solve", ModelActionRequest, RuntimeResult, run_solve, "solve", False, False),
        (
            "comsol.evaluate",
            EvaluateRequest,
            RuntimeResult,
            runtime.evaluate,
            "model_read",
            True,
            True,
        ),
        (
            "comsol.export_results",
            ExportRequest,
            RuntimeResult,
            runtime.export_results,
            "model_read",
            True,
            True,
        ),
        (
            "comsol.create_checkpoint",
            CheckpointCreateRequest,
            Checkpoint,
            runtime.create_checkpoint,
            "model_write",
            False,
            True,
        ),
        (
            "comsol.inspect_checkpoint",
            CheckpointInspectRequest,
            Checkpoint,
            inspect_checkpoint,
            "model_read",
            True,
            True,
        ),
        (
            "comsol.restore_checkpoint",
            CheckpointRestoreRequest,
            Checkpoint,
            restore_checkpoint,
            "model_write",
            False,
            False,
        ),
        (
            "comsol.cancel_run",
            CancelRunRequest,
            RuntimeResult,
            _cancel_handler(runtime),
            "model_write",
            False,
            True,
        ),
        (
            "comsol.inspect_failure",
            FailureInspectRequest,
            RuntimeResult,
            _failure_handler(runtime),
            "model_read",
            True,
            True,
        ),
    ]
    filesystem_permissions = {
        "comsol.load_model": "read",
        "comsol.save_model": "write",
        "comsol.export_results": "write",
        "comsol.create_checkpoint": "write",
        "comsol.inspect_checkpoint": "read",
        "comsol.restore_checkpoint": "read",
    }
    return [
        RuntimeMcpTool(
            capability=capability,
            request_model=request_model,
            output_model=output_model,
            handler=handler,
            permission=permission,
            filesystem=filesystem_permissions.get(capability, "none"),
            read_only=read_only,
            idempotent=idempotent,
        )
        for (
            capability,
            request_model,
            output_model,
            handler,
            permission,
            read_only,
            idempotent,
        ) in definitions
    ]


def _cancel_handler(runtime: ComsolRuntime) -> Handler:
    def cancel(request: CancelRunRequest) -> RuntimeResult:
        cancelled = runtime.cancel_run(request)
        return RuntimeResult(
            run_id=request.run_id,
            model_id="runtime",
            success=True,
            status="cancel_requested" if cancelled else "not_running",
            data={"target_run_id": request.target_run_id, "cancel_requested": cancelled},
        )

    return cancel


def _failure_handler(runtime: ComsolRuntime) -> Handler:
    def inspect_failure(request: FailureInspectRequest) -> RuntimeResult:
        failure = runtime.inspect_failure(request)
        return RuntimeResult(
            run_id=request.run_id,
            model_id="runtime",
            success=True,
            status="found" if failure else "not_found",
            data={"failure": failure.model_dump(mode="json") if failure else None},
        )

    return inspect_failure
