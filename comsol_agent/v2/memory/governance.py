"""Quarantine, promotion, invalidation, revalidation, and deletion policy."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import Field

from comsol_agent.v2.contracts.models import ContractModel, utc_now

from .contracts import (
    AuditGates,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    QueryCompatibility,
    RepairCase,
    VerifiedCase,
)
from .store import MemoryRepository, StaleMemoryWriteError


class PromotionRejectedError(RuntimeError):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


class InvalidMemoryTransitionError(RuntimeError):
    pass


class PromotionEvidence(ContractModel):
    auditor_id: str = Field(min_length=1)
    final_spec: bool
    all_stages_executed: bool
    target_step_returned: bool
    gates: AuditGates
    artifacts_readable: bool
    artifact_hashes_complete: bool
    unresolved_high_warnings: int = Field(default=0, ge=0)


class CompatibilityDecision(ContractModel):
    compatible: bool
    complete: bool
    reasons: list[str] = Field(default_factory=list)


ReferenceValidator = Callable[[MemoryRecord], tuple[bool, list[str]]]


def compatibility_decision(
    record: MemoryRecord,
    environment: QueryCompatibility,
    *,
    domain: str,
    topology_signature: str | None,
) -> CompatibilityDecision:
    reasons: list[str] = []
    incomplete: list[str] = []
    declared = record.compatibility
    if declared.domain != domain:
        reasons.append(f"domain mismatch: {declared.domain} != {domain}")
    if declared.topology_signature and declared.topology_signature != topology_signature:
        reasons.append("topology signature mismatch")
    _check_version("COMSOL", environment.comsol_version, declared.comsol, reasons, incomplete)
    _check_version("Agent", environment.agent_version, declared.agent_api, reasons, incomplete)
    _check_version_map(
        "builder", environment.builder_versions, declared.builder_versions, reasons, incomplete
    )
    _check_version_map(
        "contract",
        environment.contract_versions,
        declared.contract_versions,
        reasons,
        incomplete,
    )
    missing_scopes = declared.scopes - environment.scopes
    if missing_scopes:
        reasons.append(f"missing data scopes: {sorted(missing_scopes)}")
    return CompatibilityDecision(
        compatible=not reasons,
        complete=not incomplete,
        reasons=[*reasons, *incomplete],
    )


def _check_version(
    label: str,
    actual: str | None,
    constraint: str,
    reasons: list[str],
    incomplete: list[str],
) -> None:
    if not constraint:
        return
    if actual is None:
        incomplete.append(f"{label} version required for compatibility check")
        return
    try:
        if Version(actual) not in SpecifierSet(constraint):
            reasons.append(f"{label} {actual} does not satisfy {constraint}")
    except (InvalidSpecifier, InvalidVersion):
        reasons.append(f"invalid {label} compatibility declaration or version")


def _check_version_map(
    label: str,
    actual: dict[str, str],
    constraints: dict[str, str],
    reasons: list[str],
    incomplete: list[str],
) -> None:
    for component, constraint in constraints.items():
        version = actual.get(component)
        if version is None:
            incomplete.append(f"{label} version missing: {component}")
            continue
        _check_version(f"{label} {component}", version, constraint, reasons, incomplete)


class MemoryGovernance:
    """The only public path from untrusted candidate to executable memory."""

    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    def ingest(self, record: MemoryRecord) -> str:
        quarantined = record.model_copy(
            update={"status": MemoryStatus.QUARANTINED, "validated_at": None}, deep=True
        )
        return self.repository.add(quarantined)

    def nominate(self, record_id: str) -> MemoryRecord:
        record = self.repository.require(record_id)
        if record.status != MemoryStatus.QUARANTINED:
            raise InvalidMemoryTransitionError("only quarantined records can be nominated")
        candidate = record.model_copy(update={"status": MemoryStatus.CANDIDATE}, deep=True)
        self.repository.replace(
            candidate,
            expected_status=MemoryStatus.QUARANTINED,
            governed_transition=True,
        )
        return candidate

    def activate_fact(self, record_id: str) -> MemoryRecord:
        record = self.repository.require(record_id)
        if record.status != MemoryStatus.CANDIDATE:
            raise InvalidMemoryTransitionError("only candidate facts can be activated")
        if record.type not in {
            MemoryType.API_RULE,
            MemoryType.PROJECT_FACT,
            MemoryType.PROCEDURE,
        }:
            raise InvalidMemoryTransitionError("cases require an evidence-based promotion path")
        if record.type == MemoryType.PROJECT_FACT and not record.citations:
            raise PromotionRejectedError(["project facts require code citations"])
        activated = record.model_copy(
            update={"status": MemoryStatus.ACTIVE, "validated_at": utc_now()}, deep=True
        )
        self.repository.replace(
            activated,
            expected_status=MemoryStatus.CANDIDATE,
            governed_transition=True,
        )
        return activated

    def promote_verified_case(
        self, record_id: str, evidence: PromotionEvidence
    ) -> MemoryRecord:
        record = self.repository.require(record_id)
        if record.status != MemoryStatus.CANDIDATE:
            raise InvalidMemoryTransitionError("promotion requires candidate status")
        reasons = self._verified_case_rejections(record, evidence)
        if reasons:
            raise PromotionRejectedError(reasons)
        quality = record.quality.model_copy(
            update={
                "execution_passed": True,
                "physical_audit_passed": True,
                "audit_score": 1.0,
                "unresolved_high_warnings": 0,
            }
        )
        promoted = record.model_copy(
            update={
                "status": MemoryStatus.VERIFIED,
                "validated_at": utc_now(),
                "quality": quality,
            },
            deep=True,
        )
        self.repository.replace(
            promoted,
            expected_status=MemoryStatus.CANDIDATE,
            governed_transition=True,
        )
        return promoted

    def promote_repair_case(self, record_id: str) -> MemoryRecord:
        record = self.repository.require(record_id)
        if record.status != MemoryStatus.CANDIDATE:
            raise InvalidMemoryTransitionError("promotion requires candidate status")
        if record.type != MemoryType.REPAIR_CASE or not isinstance(
            record.structured, RepairCase
        ):
            raise PromotionRejectedError(["record is not a typed repair case"])
        if not record.structured.verification.static:
            raise PromotionRejectedError(["repair static verification did not pass"])
        if not record.structured.verification.runtime:
            raise PromotionRejectedError(["repair runtime verification did not pass"])
        if record.structured.verification.verifier is None:
            raise PromotionRejectedError(["repair verification provenance is missing"])
        if not all(
            (
                record.provenance.run_id,
                record.provenance.git_commit,
                record.provenance.code_hash,
            )
        ):
            raise PromotionRejectedError(["repair provenance is incomplete"])
        promoted = record.model_copy(
            update={
                "status": MemoryStatus.VERIFIED,
                "validated_at": utc_now(),
                "quality": record.quality.model_copy(
                    update={"execution_passed": True}
                ),
            },
            deep=True,
        )
        self.repository.replace(
            promoted,
            expected_status=MemoryStatus.CANDIDATE,
            governed_transition=True,
        )
        return promoted

    def revalidate(
        self,
        record_id: str,
        environment: QueryCompatibility,
        reference_validator: ReferenceValidator,
        *,
        domain: str,
        topology_signature: str | None,
    ) -> MemoryRecord:
        record = self.repository.require(record_id)
        if record.status != MemoryStatus.NEEDS_REVALIDATION:
            raise InvalidMemoryTransitionError("record does not need revalidation")
        compatibility = compatibility_decision(
            record,
            environment,
            domain=domain,
            topology_signature=topology_signature,
        )
        references_valid, reference_reasons = reference_validator(record)
        if not compatibility.compatible or not compatibility.complete or not references_valid:
            raise PromotionRejectedError([*compatibility.reasons, *reference_reasons])
        target = (
            MemoryStatus.VERIFIED
            if record.type in {MemoryType.VERIFIED_CASE, MemoryType.REPAIR_CASE}
            else MemoryStatus.ACTIVE
        )
        updated = record.model_copy(
            update={"status": target, "validated_at": utc_now()}, deep=True
        )
        self.repository.replace(
            updated,
            expected_status=MemoryStatus.NEEDS_REVALIDATION,
            governed_transition=True,
        )
        return updated

    def mark_needs_revalidation(self, record_id: str, _reasons: list[str]) -> MemoryRecord:
        record = self.repository.require(record_id)
        if record.status not in {MemoryStatus.VERIFIED, MemoryStatus.ACTIVE}:
            return record
        updated = record.model_copy(
            update={"status": MemoryStatus.NEEDS_REVALIDATION}, deep=True
        )
        try:
            self.repository.replace(
                updated,
                expected_status=record.status,
                governed_transition=True,
            )
        except StaleMemoryWriteError:
            return self.repository.require(record_id)
        return updated

    def invalidate(self, record_id: str, _reason: str) -> MemoryRecord:
        record = self.repository.require(record_id)
        updated = record.model_copy(
            update={"status": MemoryStatus.INVALIDATED, "type": MemoryType.INVALIDATED_CASE},
            deep=True,
        )
        self.repository.replace(
            updated,
            expected_status=record.status,
            governed_transition=True,
        )
        return updated

    def delete(self, record_id: str, reason: str):
        return self.repository.delete(record_id, reason)

    @staticmethod
    def _verified_case_rejections(
        record: MemoryRecord, evidence: PromotionEvidence
    ) -> list[str]:
        reasons: list[str] = []
        if record.type != MemoryType.VERIFIED_CASE or not isinstance(
            record.structured, VerifiedCase
        ):
            return ["record is not a typed verified case"]
        if not evidence.final_spec:
            reasons.append("run did not use the final specification")
        if not evidence.all_stages_executed:
            reasons.append("not all execution stages passed")
        if not evidence.target_step_returned:
            reasons.append("target parameter step was not returned")
        if not evidence.gates.all_passed() or not record.structured.gates.all_passed():
            reasons.append("strict physical audit gates did not all pass")
        if evidence.gates != record.structured.gates:
            reasons.append("promotion evidence does not match stored audit gates")
        if not evidence.artifacts_readable:
            reasons.append("one or more artifacts are unreadable")
        if not evidence.artifact_hashes_complete:
            reasons.append("artifact hashes are incomplete")
        if evidence.unresolved_high_warnings:
            reasons.append("run has unresolved high-severity warnings")
        if not record.provenance.complete_for_verified_case():
            reasons.append("verified-case provenance is incomplete")
        if record.provenance.producer.kind != "auditor":
            reasons.append("verified-case producer is not an Auditor")
        if evidence.auditor_id != record.provenance.producer.identifier:
            reasons.append("promotion Auditor does not match stored provenance")
        if not record.content_ref:
            reasons.append("verified case requires a RunManifest content_ref")
        if not record.structured.artifacts:
            reasons.append("verified case has no result artifacts")
        return reasons


def freshness_score(validated_at: datetime | None, now: datetime | None = None) -> float:
    if validated_at is None:
        return 0.0
    current = now or utc_now()
    days = max(0.0, (current - validated_at).total_seconds() / 86400)
    return 1.0 / (1.0 + days / 365.0)
