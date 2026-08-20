"""Versioned, domain-neutral contracts shared by the V2 kernel."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    """Return an aware UTC timestamp for persisted records."""
    return datetime.now(UTC)


class ContractModel(BaseModel):
    """Base class for strict, serializable V2 contracts."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class GoalStatus(StrEnum):
    ACTIVE = "active"
    COMPLETE = "complete"
    BLOCKED = "blocked"


class PlanStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"


class StepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"


class RunStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceRef(ContractModel):
    """Identifies the origin and compatibility version of supplied data."""

    kind: str
    identifier: str
    version: str = "1"
    uri: str | None = None


class ArtifactRef(ContractModel):
    """A content-addressable artifact reference, not the artifact payload."""

    uri: str
    media_type: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source: SourceRef | None = None


class GoalSpec(ContractModel):
    """The verifiable outcome and constraints for one agent run."""

    objective: str = Field(min_length=1)
    constraints: dict[str, Any] = Field(default_factory=dict)
    acceptance: list[str] = Field(default_factory=list)
    status: GoalStatus = GoalStatus.ACTIVE
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    schema_version: str = "1.0"


class Action(ContractModel):
    """A controlled request to one tool capability."""

    action_id: str = Field(default_factory=lambda: uuid4().hex)
    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    permissions: frozenset[str] = Field(default_factory=frozenset)
    idempotency_key: str | None = None
    expected_output: dict[str, Any] = Field(default_factory=dict)


class PlanStep(ContractModel):
    """One independently observable action in a plan."""

    step_id: str = Field(default_factory=lambda: uuid4().hex)
    description: str = Field(min_length=1)
    action: Action
    status: StepStatus = StepStatus.PENDING


class Plan(ContractModel):
    """An ordered, inspectable execution plan."""

    plan_id: str = Field(default_factory=lambda: uuid4().hex)
    goal_trace_id: str
    steps: list[PlanStep] = Field(min_length=1)
    status: PlanStatus = PlanStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    schema_version: str = "1.0"

    @model_validator(mode="after")
    def unique_step_ids(self) -> Plan:
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Plan step_id values must be unique")
        return self


class Observation(ContractModel):
    """Structured evidence returned by every external action."""

    observation_id: str = Field(default_factory=lambda: uuid4().hex)
    action_id: str
    success: bool
    status: str
    stage: str
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    error_class: str | None = None
    exception_type: str | None = None
    location: str | None = None
    retryable: bool = False
    duration_ms: float = Field(default=0.0, ge=0)
    resource_usage: dict[str, float] = Field(default_factory=dict)
    checkpoint: str | None = None
    source: SourceRef
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def failure_has_error_class(self) -> Observation:
        if not self.success and not self.error_class:
            raise ValueError("A failed Observation requires error_class")
        if self.success and self.retryable:
            raise ValueError("A successful Observation cannot be retryable")
        return self


class StateTransitionRecord(ContractModel):
    from_stage: str
    to_stage: str
    reason: str
    occurred_at: datetime = Field(default_factory=utc_now)


class ActionRecord(ContractModel):
    action: Action
    observation: Observation
    attempt: int = Field(ge=1)


class RepairRecord(ContractModel):
    action_id: str
    error_class: str
    attempt: int = Field(ge=1)
    verifier: str


class RunManifest(ContractModel):
    """The sole persisted index of facts and evidence for a V2 run."""

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str
    goal: GoalSpec
    plan: Plan
    status: RunStatus = RunStatus.ACTIVE
    current_stage: str = "intake"
    retrievals: list[SourceRef] = Field(default_factory=list)
    routing_decisions: list[str] = Field(default_factory=list)
    code_hashes: dict[str, str] = Field(default_factory=dict)
    action_records: list[ActionRecord] = Field(default_factory=list)
    transitions: list[StateTransitionRecord] = Field(default_factory=list)
    repairs: list[RepairRecord] = Field(default_factory=list)
    checkpoints: list[str] = Field(default_factory=list)
    tests: list[dict[str, Any]] = Field(default_factory=list)
    audits: list[dict[str, Any]] = Field(default_factory=list)
    versions: dict[str, str] = Field(default_factory=dict)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    trace_events: list[dict[str, Any]] = Field(default_factory=list)
    failure_reason: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    schema_version: str = "1.0"

    @model_validator(mode="after")
    def trace_ids_match(self) -> RunManifest:
        if self.trace_id != self.goal.trace_id:
            raise ValueError("RunManifest trace_id must match GoalSpec trace_id")
        if self.plan.goal_trace_id != self.goal.trace_id:
            raise ValueError("Plan goal_trace_id must match GoalSpec trace_id")
        return self
