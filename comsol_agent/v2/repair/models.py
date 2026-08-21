"""Strict, domain-neutral contracts for diagnosis and bounded repair."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field, model_validator

from comsol_agent.v2.contracts.models import ContractModel


class DiagnosticErrorClass(StrEnum):
    API_CODE = "api_code_error"
    GEOMETRY = "geometry_error"
    MESH = "mesh_error"
    SOLVE_CONVERGENCE = "solve_or_convergence_error"
    PHYSICS_AUDIT = "physics_audit_failure"
    RUNTIME = "runtime_error"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    RESOURCE = "resource_error"
    TEST = "test_failure"
    STATIC_ANALYSIS = "static_analysis_failure"
    FILE_PATCH = "file_patch_failure"


class ErrorCode(StrEnum):
    UNKNOWN_FEATURE = "UNKNOWN_FEATURE"
    INVALID_PROPERTY = "INVALID_PROPERTY"
    INVALID_OVERLOAD = "INVALID_OVERLOAD"
    EMPTY_SELECTION = "EMPTY_SELECTION"
    ENTITY_DIMENSION = "ENTITY_DIMENSION"
    PAIR_BINDING = "PAIR_BINDING"
    GEOMETRY_FAILURE = "GEOMETRY_FAILURE"
    MESH_FAILURE = "MESH_FAILURE"
    NON_CONVERGENCE = "NON_CONVERGENCE"
    PHYSICS_AUDIT_FAILURE = "PHYSICS_AUDIT_FAILURE"
    RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    RESOURCE_UNAVAILABLE = "RESOURCE_UNAVAILABLE"
    PYTEST_FAILURE = "PYTEST_FAILURE"
    RUFF_FAILURE = "RUFF_FAILURE"
    FILE_PATCH_FAILURE = "FILE_PATCH_FAILURE"
    UNKNOWN = "UNKNOWN"


class RepairKind(StrEnum):
    DETERMINISTIC_RULE = "deterministic_rule"
    LOCAL_PATTERN = "local_pattern"
    REPAIR_CASE = "repair_case"
    LLM_PATCH = "llm_patch"
    SOLVER_STRATEGY = "solver_strategy"
    USER_DECISION = "user_decision"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class RepairStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CONFLICT = "conflict"
    REPEATED_FAILURE = "repeated_failure"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"
    UNSAFE = "unsafe"
    USER_DECISION_REQUIRED = "user_decision_required"
    CHECKPOINT_FAILED = "checkpoint_failed"
    ROLLBACK_FAILED = "rollback_failed"
    COMMIT_FAILED = "commit_failed"


class CauseSummary(ContractModel):
    exception_type: str
    message: str


class AffectedScope(ContractModel):
    kind: str = Field(min_length=1)
    targets: tuple[str, ...] = Field(default_factory=tuple)

    def contains(self, other: AffectedScope) -> bool:
        if self.kind != other.kind:
            return False
        if not self.targets:
            return True
        return all(
            any(target == allowed or target.startswith(f"{allowed}.") for allowed in self.targets)
            for target in other.targets
        )


class EvidenceReference(ContractModel):
    observation_id: str
    source: str
    artifacts: tuple[str, ...] = Field(default_factory=tuple)


class Diagnosis(ContractModel):
    diagnosis_id: str = Field(default_factory=lambda: uuid4().hex)
    error_class: DiagnosticErrorClass
    error_code: ErrorCode
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage: str
    operation: str | None = None
    exception_chain: tuple[CauseSummary, ...] = Field(default_factory=tuple)
    retryable: bool
    termination_confirmed: bool | None = None
    affected_scope: AffectedScope
    suspected_component: str | None = None
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    compatible_checkpoint: str | None = None
    allowed_repair_kinds: frozenset[RepairKind] = Field(default_factory=frozenset)
    severity: Severity = Severity.ERROR
    confidence: float = Field(ge=0.0, le=1.0)


class VersionCompatibility(ContractModel):
    agent_api: str = Field(min_length=1)
    comsol: tuple[str, ...] = Field(default_factory=tuple)
    builders: dict[str, str] = Field(default_factory=dict)


class RepairExecutionContext(ContractModel):
    """Policy-owned runtime facts used to execute declarative repair contracts."""

    agent_version: str = Field(default="2.0.0", min_length=1)
    comsol_version: str | None = None
    builder_versions: dict[str, str] = Field(default_factory=dict)
    satisfied_preconditions: frozenset[str] = Field(default_factory=frozenset)
    mandatory_gates: frozenset[str] = Field(default_factory=frozenset)
    solve_attempts_used: int = Field(default=0, ge=0)
    core_hours_used: float = Field(default=0.0, ge=0.0)


class RepairExecutionLimits(ContractModel):
    """Immutable limits supplied by the orchestrator to the controlled executor."""

    max_solves: int | None = Field(default=None, ge=1)
    core_hour_budget: float | None = Field(default=None, gt=0)
    required_checkpoint: str | None = None
    required_gates: frozenset[str] = Field(min_length=1)
    success_criteria: tuple[str, ...] = Field(default_factory=tuple)


class RepairRuleContract(ContractModel):
    error_classes: frozenset[DiagnosticErrorClass] = Field(min_length=1)
    error_codes: frozenset[ErrorCode] = Field(min_length=1)
    stages: frozenset[str] = Field(min_length=1)
    preconditions: tuple[str, ...] = Field(default_factory=tuple)
    modification_scope: AffectedScope
    required_permissions: frozenset[str] = Field(default_factory=frozenset)
    max_attempts: int = Field(ge=1, le=3)
    verifier: str = Field(min_length=1)
    rollback_required: bool = True
    compatibility: VersionCompatibility
    provenance: str = Field(min_length=1)

    def matches(self, diagnosis: Diagnosis) -> bool:
        return (
            diagnosis.error_class in self.error_classes
            and diagnosis.error_code in self.error_codes
            and diagnosis.stage in self.stages
        )


class SolverStrategyContract(ContractModel):
    error_codes: frozenset[ErrorCode] = Field(
        default_factory=lambda: frozenset({ErrorCode.NON_CONVERGENCE})
    )
    preconditions: tuple[str, ...] = Field(default_factory=tuple)
    solver_scope: AffectedScope
    continuation: dict[str, Any] = Field(default_factory=dict)
    initialization: dict[str, Any] = Field(default_factory=dict)
    max_solves: int = Field(ge=1, le=3)
    core_hour_budget: float = Field(gt=0)
    success_criteria: tuple[str, ...] = Field(min_length=1)
    rollback_checkpoint: str = Field(min_length=1)
    required_permissions: frozenset[str] = Field(default_factory=frozenset)
    compatibility: VersionCompatibility
    provenance: str = Field(min_length=1)


class RepairCandidate(ContractModel):
    candidate_id: str = Field(default_factory=lambda: uuid4().hex)
    kind: RepairKind
    observation_id: str
    diagnosis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: AffectedScope
    permissions: frozenset[str] = Field(default_factory=frozenset)
    verifier: str = Field(min_length=1)
    checkpoint_required: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: str = Field(min_length=1)
    extension_id: str | None = None
    extension_version: str | None = None
    repair_case_id: str | None = None
    required_gates: frozenset[str] = Field(min_length=1)

    @model_validator(mode="after")
    def source_fields_are_consistent(self) -> RepairCandidate:
        if self.kind == RepairKind.REPAIR_CASE and not self.repair_case_id:
            raise ValueError("repair_case candidates require repair_case_id")
        return self


class RepairTraceEvent(ContractModel):
    sequence: int = Field(ge=1)
    event: str
    diagnosis_id: str
    candidate_id: str | None = None
    observation_id: str | None = None
    checkpoint: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class RepairAttempt(ContractModel):
    candidate: RepairCandidate
    checkpoint: str | None = None
    verification_observation_id: str | None = None
    success: bool = False
    rolled_back: bool = False
    failure_reason: str | None = None
    rollback_failure: str | None = None


class RepairResult(ContractModel):
    status: RepairStatus
    diagnosis: Diagnosis
    attempts: list[RepairAttempt] = Field(default_factory=list)
    trace: list[RepairTraceEvent] = Field(default_factory=list)
    final_observation_id: str | None = None
    user_message: str
    manual_recovery_required: bool = False
