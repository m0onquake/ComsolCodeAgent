"""Strict, transport-neutral contracts for V2 user-facing observability."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from comsol_agent.v2.contracts.models import ContractModel, utc_now


class V2EventKind(StrEnum):
    SESSION = "session"
    SPECIFICATION = "specification"
    RETRIEVAL = "retrieval"
    PLAN = "plan"
    TOOL = "tool"
    COMSOL_STAGE = "comsol_stage"
    REPAIR = "repair"
    BUDGET = "budget"
    AUDIT = "audit"
    ARTIFACT = "artifact"
    FAILURE = "failure"


class SessionStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSE_REQUESTED = "pause_requested"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


class EvidenceState(StrEnum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class VerificationLevel(StrEnum):
    NONE = "none"
    STATIC_DEMO = "static_demo"
    SPECIFICATION_VALIDATED = "specification_validated"
    PLANNED = "planned"
    MODEL_BUILT = "model_built"
    SOLVE_PASSED = "solve_passed"
    ENGINEERING_PREVIEW_ACCEPTED = "engineering_preview_accepted"
    PHYSICAL_AUDIT_PASSED = "physical_audit_passed"
    FAILED = "failed"


class EvidenceGate(ContractModel):
    state: EvidenceState = EvidenceState.PENDING
    source: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)


class V2Event(ContractModel):
    sequence: int = Field(ge=1)
    session_id: str
    turn_id: str
    kind: V2EventKind
    phase: str
    status: str
    source: str
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utc_now)


class ArtifactView(ContractModel):
    artifact_id: str
    name: str
    uri: str
    media_type: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    stage: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    download_url: str | None = None


class FailureView(ContractModel):
    error_class: str
    message: str
    stage: str | None = None
    code: str | None = None
    retryable: bool = False
    termination_confirmed: bool | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class SessionSnapshot(ContractModel):
    session_id: str
    status: SessionStatus
    active_turn_id: str | None = None
    verification_level: VerificationLevel = VerificationLevel.NONE
    gates: dict[str, EvidenceGate]
    specification: dict[str, Any] | None = None
    previous_specification: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    checkpoint: str | None = None
    artifacts: list[ArtifactView] = Field(default_factory=list)
    repairs: list[dict[str, Any]] = Field(default_factory=list)
    failure: FailureView | None = None
    budget: dict[str, Any] = Field(default_factory=dict)
    event_count: int = Field(default=0, ge=0)
    turn_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
