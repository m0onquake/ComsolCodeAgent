"""Strict, domain-neutral contracts for V2 memory and retrieval."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field, model_validator

from comsol_agent.v2.contracts import ArtifactRef, SourceRef
from comsol_agent.v2.contracts.models import ContractModel, utc_now

MEMORY_SCHEMA_VERSION = "1.0"


class MemoryLayer(StrEnum):
    WORKING = "working"
    SESSION = "session"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    ARTIFACT = "artifact"


class MemoryType(StrEnum):
    VERIFIED_CASE = "verified_case"
    REPAIR_CASE = "repair_case"
    API_RULE = "api_rule"
    PROJECT_FACT = "project_fact"
    CANDIDATE_CASE = "candidate_case"
    INVALIDATED_CASE = "invalidated_case"
    PROCEDURE = "procedure"


class MemoryStatus(StrEnum):
    QUARANTINED = "quarantined"
    CANDIDATE = "candidate"
    ACTIVE = "active"
    VERIFIED = "verified"
    NEEDS_REVALIDATION = "needs_revalidation"
    INVALIDATED = "invalidated"


class ContextRole(StrEnum):
    FACT = "fact"
    CASE = "case"
    SUGGESTION = "suggestion"
    OBSERVATION = "observation"


class ErrorSignature(ContractModel):
    error_class: str = Field(min_length=1, alias="class")
    exception: str | None = None
    feature_pattern: str | None = None
    stage: str = Field(min_length=1)

    model_config = {**ContractModel.model_config, "populate_by_name": True}


class RepairVerification(ContractModel):
    static: bool
    runtime: bool
    physical: bool | None = None
    verifier: SourceRef | None = None


class RepairCase(ContractModel):
    error_signature: ErrorSignature
    root_cause: str = Field(min_length=1)
    failed_code_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    patch_ref: ArtifactRef
    repair_rule_id: str = Field(min_length=1)
    verification: RepairVerification
    applicability: dict[str, Any] = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)


class AuditGates(ContractModel):
    api: bool
    selections: bool
    mesh: bool
    solver: bool
    target_step: bool
    load_balance: bool
    reaction_balance: bool
    contact_balance: bool
    stabilization_controlled: bool
    finite_results: bool
    native_results: bool

    def all_passed(self) -> bool:
        return all(self.model_dump().values())


class VerifiedCase(ContractModel):
    original_request: str = Field(min_length=1)
    normalized_request: str = Field(min_length=1)
    engineering_spec: dict[str, Any]
    topology_signature: str = Field(min_length=1)
    geometry_signature: str = Field(min_length=1)
    physics_signature: str = Field(min_length=1)
    solver_signature: str = Field(min_length=1)
    value_sources: dict[str, dict[str, Any]] = Field(default_factory=dict)
    parameters: dict[str, float] = Field(default_factory=dict)
    baseline_code: ArtifactRef
    segment_hashes: dict[str, str] = Field(default_factory=dict)
    extension_versions: dict[str, str] = Field(default_factory=dict)
    rule_versions: dict[str, str] = Field(default_factory=dict)
    path_versions: dict[str, str] = Field(default_factory=dict)
    gates: AuditGates
    measurements: dict[str, float] = Field(default_factory=dict)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    applicability: dict[str, Any] = Field(default_factory=dict)
    invalidation_conditions: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def hashes_are_content_hashes(self) -> VerifiedCase:
        invalid = [value for value in self.segment_hashes.values() if len(value) != 64]
        if invalid:
            raise ValueError("segment_hashes values must be SHA-256 hex digests")
        return self


class MemoryProvenance(ContractModel):
    run_id: str | None = None
    git_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,64}$")
    code_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    comsol_version: str | None = None
    agent_version: str = Field(min_length=1)
    agent_schema: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    producer: SourceRef
    parent_ids: list[str] = Field(default_factory=list)

    def complete_for_verified_case(self) -> bool:
        return all((self.run_id, self.git_commit, self.code_hash, self.comsol_version))


class MemoryCompatibility(ContractModel):
    domain: str = Field(min_length=1)
    topology_signature: str | None = None
    comsol: str = Field(default="", description="PEP 440 compatible specifier")
    agent_api: str = Field(default="", description="PEP 440 compatible specifier")
    builder_versions: dict[str, str] = Field(default_factory=dict)
    contract_versions: dict[str, str] = Field(default_factory=dict)
    scopes: frozenset[str] = Field(default_factory=frozenset)


class MemoryQuality(ContractModel):
    execution_passed: bool = False
    physical_audit_passed: bool = False
    audit_score: float = Field(default=0.0, ge=0.0, le=1.0)
    unresolved_high_warnings: int = Field(default=0, ge=0)
    adoption_count: int = Field(default=0, ge=0)
    adoption_success_count: int = Field(default=0, ge=0)

    @property
    def adoption_success_rate(self) -> float:
        if not self.adoption_count:
            return 0.0
        return self.adoption_success_count / self.adoption_count


class MemoryRelation(ContractModel):
    kind: str = Field(min_length=1)
    target_id: str = Field(min_length=1)


class MemoryRecord(ContractModel):
    id: str = Field(default_factory=lambda: f"mem_{uuid4().hex}")
    layer: MemoryLayer
    type: MemoryType
    status: MemoryStatus = MemoryStatus.QUARANTINED
    summary: str = Field(min_length=1)
    content_ref: str | None = None
    structured: VerifiedCase | RepairCase | dict[str, Any]
    provenance: MemoryProvenance
    compatibility: MemoryCompatibility
    quality: MemoryQuality = Field(default_factory=MemoryQuality)
    citations: list[SourceRef] = Field(default_factory=list)
    relations: list[MemoryRelation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    validated_at: datetime | None = None
    schema_version: str = MEMORY_SCHEMA_VERSION

    @model_validator(mode="after")
    def enforce_typed_content_and_long_term_layer(self) -> MemoryRecord:
        if self.layer in {MemoryLayer.WORKING, MemoryLayer.SESSION}:
            raise ValueError(
                "Working and Session entries belong to RuntimeMemory, not MemoryRecord"
            )
        if self.type == MemoryType.VERIFIED_CASE and not isinstance(
            self.structured, VerifiedCase
        ):
            raise ValueError("verified_case requires VerifiedCase structured content")
        if self.type == MemoryType.REPAIR_CASE and not isinstance(self.structured, RepairCase):
            raise ValueError("repair_case requires RepairCase structured content")
        if self.status == MemoryStatus.VERIFIED and self.type not in {
            MemoryType.VERIFIED_CASE,
            MemoryType.REPAIR_CASE,
        }:
            raise ValueError("verified status is reserved for audited cases")
        return self

    @property
    def executable(self) -> bool:
        if self.status != MemoryStatus.VERIFIED:
            return False
        if self.type == MemoryType.VERIFIED_CASE:
            case = self.structured
            return (
                isinstance(case, VerifiedCase)
                and case.gates.all_passed()
                and self.quality.execution_passed
                and self.quality.physical_audit_passed
                and self.provenance.complete_for_verified_case()
            )
        if self.type == MemoryType.REPAIR_CASE:
            repair = self.structured
            return isinstance(repair, RepairCase) and repair.verification.runtime
        return False


class RuntimeMemoryEntry(ContractModel):
    entry_id: str = Field(default_factory=lambda: uuid4().hex)
    layer: MemoryLayer
    content: Any
    source: SourceRef
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def runtime_layer_only(self) -> RuntimeMemoryEntry:
        if self.layer not in {MemoryLayer.WORKING, MemoryLayer.SESSION}:
            raise ValueError("RuntimeMemoryEntry only accepts working or session layers")
        return self


class RetrievalWeights(ContractModel):
    structured: float = Field(default=0.35, ge=0)
    keyword: float = Field(default=0.25, ge=0)
    vector: float = Field(default=0.25, ge=0)
    relation: float = Field(default=0.15, ge=0)
    quality: float = Field(default=0.20, ge=0)
    freshness: float = Field(default=0.10, ge=0)
    adoption: float = Field(default=0.15, ge=0)


class QueryCompatibility(ContractModel):
    comsol_version: str | None = None
    agent_version: str | None = None
    builder_versions: dict[str, str] = Field(default_factory=dict)
    contract_versions: dict[str, str] = Field(default_factory=dict)
    scopes: frozenset[str] = Field(default_factory=frozenset)


class RetrievalQuery(ContractModel):
    text: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    topology_signature: str | None = None
    parameters: dict[str, float] = Field(default_factory=dict)
    compatibility: QueryCompatibility = Field(default_factory=QueryCompatibility)
    types: frozenset[MemoryType] = Field(default_factory=frozenset)
    statuses: frozenset[MemoryStatus] = Field(
        default_factory=lambda: frozenset({MemoryStatus.VERIFIED, MemoryStatus.ACTIVE})
    )
    error_signature: ErrorSignature | None = None
    related_ids: frozenset[str] = Field(default_factory=frozenset)
    require_executable: bool = False
    top_k: int = Field(default=5, ge=1, le=50)


class RetrievalHit(ContractModel):
    record: MemoryRecord
    score: float = Field(ge=0)
    channel_scores: dict[str, float] = Field(default_factory=dict)
    executable: bool
    compatibility_checked: bool
    references_checked: bool
    reasons: list[str] = Field(default_factory=list)


class RetrievalRejection(ContractModel):
    record_id: str
    reasons: list[str] = Field(min_length=1)


class RetrievalResult(ContractModel):
    query: RetrievalQuery
    hits: list[RetrievalHit] = Field(default_factory=list)
    rejected: list[RetrievalRejection] = Field(default_factory=list)


class ContextPackItem(ContractModel):
    record_id: str
    role: ContextRole
    summary: str
    interface_or_delta: dict[str, Any] = Field(default_factory=dict)
    source: SourceRef
    confidence: float = Field(ge=0.0, le=1.0)
    executable: bool = False
    artifact_refs: list[str] = Field(default_factory=list)


class ContextPack(ContractModel):
    query_summary: str
    change_set: dict[str, Any] = Field(default_factory=dict)
    primary_case: ContextPackItem | None = None
    auxiliary_cases: list[ContextPackItem] = Field(default_factory=list, max_length=2)
    api_rules: list[ContextPackItem] = Field(default_factory=list)
    repair_case: ContextPackItem | None = None
    observations: list[ContextPackItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class DeletionReceipt(ContractModel):
    record_id: str
    reason: str = Field(min_length=1)
    provenance_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    deleted_at: datetime = Field(default_factory=utc_now)


class RetrievalOutcome(ContractModel):
    query_id: str = Field(default_factory=lambda: uuid4().hex)
    retrieved_ids: list[str]
    adopted_ids: list[str] = Field(default_factory=list)
    execution_attempted: bool
    execution_success: bool | None = None
    audit_passed: bool | None = None
    repair_attempted: bool = False
    repair_success: bool | None = None
    wrong_topology_reused: bool = False
    invalidated_case_reused: bool = False
    latency_ms: float = Field(default=0.0, ge=0)
    context_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def outcomes_require_attempts(self) -> RetrievalOutcome:
        if not self.execution_attempted and (
            self.execution_success is not None or self.audit_passed is not None
        ):
            raise ValueError("execution outcomes require execution_attempted")
        if not self.repair_attempted and self.repair_success is not None:
            raise ValueError("repair_success requires repair_attempted")
        return self
