"""Strict public contracts for the V2 COMSOL runtime."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator

from comsol_agent.v2.contracts.models import ContractModel, utc_now

RUNTIME_SCHEMA_VERSION = "1.0"


class RuntimeStage(StrEnum):
    INPUT_VALIDATION = "A_input_validation"
    BUILD = "B_build"
    SOLVE = "C_solve"
    RESULTS_AUDIT = "D_results_audit"


class StageState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class RuntimeOperation(StrEnum):
    RUNTIME_STATUS = "runtime_status"
    CREATE_MODEL = "create_model"
    LOAD_MODEL = "load_model"
    SAVE_MODEL = "save_model"
    CLOSE_MODEL = "close_model"
    APPLY_PARAMETERS = "apply_parameters"
    EXECUTE_REGISTERED = "execute_registered"
    BUILD = "build"
    MESH = "mesh"
    SOLVE = "solve"
    EVALUATE = "evaluate"
    EXPORT_RESULTS = "export_results"
    CREATE_CHECKPOINT = "create_checkpoint"
    INSPECT_CHECKPOINT = "inspect_checkpoint"
    RESTORE_CHECKPOINT = "restore_checkpoint"
    CANCEL_RUN = "cancel_run"
    INSPECT_FAILURE = "inspect_failure"


class RegisteredExtensionKind(StrEnum):
    BUILDER = "builder"
    DETERMINISTIC_PATH = "deterministic_path"


class ErrorClass(StrEnum):
    API_CODE = "api_code_error"
    GEOMETRY = "geometry_error"
    MESH = "mesh_error"
    SOLVE_CONVERGENCE = "solve_or_convergence_error"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    RESOURCE = "resource_error"
    PHYSICS_AUDIT = "physics_audit_failure"


class RuntimeRequestBase(ContractModel):
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ModelRequestBase(RuntimeRequestBase):
    model_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class SessionStatusRequest(RuntimeRequestBase):
    pass


class ModelCreateRequest(ModelRequestBase):
    pass


class ModelLoadRequest(ModelRequestBase):
    source_path: str = Field(min_length=1)


class ModelSaveRequest(ModelRequestBase):
    target_name: str = Field(default="model.mph", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ModelCloseRequest(ModelRequestBase):
    pass


class ParameterPatchRequest(ModelRequestBase):
    parameters: dict[str, str] = Field(min_length=1)

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not name.strip() or not parameter.strip() for name, parameter in value.items()):
            raise ValueError("parameter names and values must be non-empty")
        return value


class RegisteredExecutionRequest(ModelRequestBase):
    extension_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    extension_version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    extension_kind: RegisteredExtensionKind
    capability: str = Field(min_length=1)
    specification: dict[str, Any] = Field(default_factory=dict)


class ModelActionRequest(ModelRequestBase):
    timeout_seconds: float = Field(default=300.0, gt=0, le=86400)


class EvaluateRequest(ModelRequestBase):
    expressions: tuple[str, ...] = Field(min_length=1)


class ExportRequest(ModelRequestBase):
    target_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class RuntimeRunRequest(ModelRequestBase):
    builder_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    builder_capability: str = Field(min_length=1)
    builder_version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    extension_versions: dict[str, str] = Field(min_length=1)
    parameters: dict[str, str] = Field(default_factory=dict)
    specification: dict[str, Any] = Field(default_factory=dict)
    previous_parameters: dict[str, str] | None = None
    previous_specification: dict[str, Any] | None = None
    override_extension_id: str | None = Field(
        default=None, pattern=r"^[a-z0-9][a-z0-9_.-]*$"
    )
    override_extension_capability: str | None = None
    override_extension_version: str | None = Field(
        default=None, pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$"
    )
    continuation_extension_id: str | None = Field(
        default=None, pattern=r"^[a-z0-9][a-z0-9_.-]*$"
    )
    continuation_extension_capability: str | None = None
    continuation_extension_version: str | None = Field(
        default=None, pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$"
    )
    expressions: tuple[str, ...] = Field(default_factory=tuple)
    timeout_seconds: float = Field(default=3600.0, gt=0, le=86400)
    resume_checkpoint: str | None = None

    @model_validator(mode="after")
    def builder_is_in_snapshot(self) -> RuntimeRunRequest:
        if self.extension_versions.get(self.builder_id) != self.builder_version:
            raise ValueError("builder version must match the pinned extension snapshot")
        override = (
            self.override_extension_id,
            self.override_extension_capability,
            self.override_extension_version,
        )
        if any(override) and not all(override):
            raise ValueError("override extension binding must be complete")
        if self.override_extension_id and (
            self.extension_versions.get(self.override_extension_id)
            != self.override_extension_version
        ):
            raise ValueError("override version must match the pinned extension snapshot")
        continuation = (
            self.continuation_extension_id,
            self.continuation_extension_capability,
            self.continuation_extension_version,
        )
        if any(continuation) and not all(continuation):
            raise ValueError("continuation extension binding must be complete")
        if self.continuation_extension_id and (
            self.extension_versions.get(self.continuation_extension_id)
            != self.continuation_extension_version
        ):
            raise ValueError("continuation version must match the pinned extension snapshot")
        if self.resume_checkpoint and self.override_extension_id and (
            self.previous_specification is None or self.previous_parameters is None
        ):
            raise ValueError("override resume requires full previous specification and parameters")
        return self


class CheckpointCreateRequest(ModelRequestBase):
    stage: RuntimeStage
    builder_id: str
    builder_capability: str
    builder_version: str
    extension_versions: dict[str, str] = Field(min_length=1)
    parameters: dict[str, str] = Field(default_factory=dict)
    specification: dict[str, Any] = Field(default_factory=dict)
    model_summary: dict[str, Any]


class CheckpointInspectRequest(RuntimeRequestBase):
    manifest_path: str = Field(min_length=1)


class CheckpointRestoreRequest(ModelRequestBase):
    manifest_path: str = Field(min_length=1)
    builder_id: str
    builder_capability: str
    builder_version: str
    extension_versions: dict[str, str] = Field(min_length=1)
    parameters: dict[str, str] = Field(default_factory=dict)
    specification: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=300.0, gt=0, le=86400)


class CancelRunRequest(RuntimeRequestBase):
    target_run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    reason: str = Field(default="cancelled by request", min_length=1)


class FailureInspectRequest(RuntimeRequestBase):
    target_run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class RuntimeProvenance(ContractModel):
    run_id: str
    model_id: str
    backend: str
    backend_version: str
    comsol_version: str
    source: str
    created_at: datetime = Field(default_factory=utc_now)


class RuntimeArtifact(ContractModel):
    artifact_id: str
    path: str
    relative_path: str
    media_type: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    stage: RuntimeStage
    provenance: RuntimeProvenance

    @field_validator("relative_path")
    @classmethod
    def relative_path_is_isolated(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("artifact relative_path must remain inside its run directory")
        return value


class CauseFrame(ContractModel):
    exception_type: str
    message: str


class RuntimeFailure(ContractModel):
    error_class: ErrorClass
    code: str
    message: str
    stage: RuntimeStage
    operation: RuntimeOperation | None = None
    retryable: bool = False
    causes: list[CauseFrame] = Field(min_length=1)
    termination_confirmed: bool | None = None


class StageRecord(ContractModel):
    stage: RuntimeStage
    state: StageState = StageState.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class Checkpoint(ContractModel):
    schema_version: str = RUNTIME_SCHEMA_VERSION
    checkpoint_id: str
    stage: RuntimeStage
    artifact: RuntimeArtifact
    manifest_path: str
    runtime_version: str
    comsol_version: str
    backend_version: str
    builder_id: str
    builder_capability: str
    builder_version: str
    extension_versions: dict[str, str]
    input_summary: dict[str, Any]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_summary: dict[str, Any]
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance: RuntimeProvenance


class RuntimeResult(ContractModel):
    run_id: str
    model_id: str
    success: bool
    status: str
    stage_records: dict[RuntimeStage, StageRecord] = Field(default_factory=dict)
    artifacts: list[RuntimeArtifact] = Field(default_factory=list)
    checkpoint: Checkpoint | None = None
    failure: RuntimeFailure | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    cleanup_complete: bool = True

    @model_validator(mode="after")
    def success_and_failure_agree(self) -> RuntimeResult:
        if self.success and self.failure is not None:
            raise ValueError("successful runtime result cannot contain a failure")
        if not self.success and self.failure is None:
            raise ValueError("failed runtime result requires a structured failure")
        return self


class SessionStatus(ContractModel):
    started: bool
    healthy: bool
    quarantined: bool
    active_models: list[str]
    active_resource_leases: int = Field(ge=0)
    capabilities: dict[str, Any]
