"""Typed diagnostic service; classifiers are injected outside the Kernel."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from comsol_agent.v2.contracts import Observation
from comsol_agent.v2.runtime.comsol import ErrorClass as RuntimeErrorClass
from comsol_agent.v2.runtime.comsol import RuntimeFailure

from .models import (
    AffectedScope,
    CauseSummary,
    Diagnosis,
    DiagnosticErrorClass,
    ErrorCode,
    EvidenceReference,
    RepairKind,
    Severity,
)

_RUNTIME_CLASS_MAP = {
    RuntimeErrorClass.API_CODE: DiagnosticErrorClass.API_CODE,
    RuntimeErrorClass.GEOMETRY: DiagnosticErrorClass.GEOMETRY,
    RuntimeErrorClass.MESH: DiagnosticErrorClass.MESH,
    RuntimeErrorClass.SOLVE_CONVERGENCE: DiagnosticErrorClass.SOLVE_CONVERGENCE,
    RuntimeErrorClass.PHYSICS_AUDIT: DiagnosticErrorClass.PHYSICS_AUDIT,
    RuntimeErrorClass.CANCELLED: DiagnosticErrorClass.CANCELLED,
    RuntimeErrorClass.TIMEOUT: DiagnosticErrorClass.TIMEOUT,
    RuntimeErrorClass.RESOURCE: DiagnosticErrorClass.RESOURCE,
}

_OBSERVATION_CODES = {
    "pytest_failure": (DiagnosticErrorClass.TEST, ErrorCode.PYTEST_FAILURE),
    "ruff_failure": (DiagnosticErrorClass.STATIC_ANALYSIS, ErrorCode.RUFF_FAILURE),
    "patch_conflict": (DiagnosticErrorClass.FILE_PATCH, ErrorCode.FILE_PATCH_FAILURE),
    "patch_failure": (DiagnosticErrorClass.FILE_PATCH, ErrorCode.FILE_PATCH_FAILURE),
}

_DEFAULT_SCOPES = {
    ErrorCode.INVALID_PROPERTY: AffectedScope(kind="property"),
    ErrorCode.INVALID_OVERLOAD: AffectedScope(kind="type_adapter"),
    ErrorCode.EMPTY_SELECTION: AffectedScope(kind="selection"),
    ErrorCode.ENTITY_DIMENSION: AffectedScope(kind="selection"),
    ErrorCode.PAIR_BINDING: AffectedScope(kind="pair_binding"),
    ErrorCode.NON_CONVERGENCE: AffectedScope(kind="solver"),
    ErrorCode.PHYSICS_AUDIT_FAILURE: AffectedScope(kind="physics_model"),
    ErrorCode.PYTEST_FAILURE: AffectedScope(kind="files"),
    ErrorCode.RUFF_FAILURE: AffectedScope(kind="files"),
    ErrorCode.FILE_PATCH_FAILURE: AffectedScope(kind="files"),
}


class DiagnosticService:
    """Normalize RuntimeFailure and test/file Observations into one contract."""

    def from_runtime(
        self,
        failure: RuntimeFailure,
        *,
        observation: Observation,
        affected_scope: AffectedScope | None = None,
        suspected_component: str | None = None,
    ) -> Diagnosis:
        try:
            code = ErrorCode(failure.code)
        except ValueError:
            code = ErrorCode.UNKNOWN
        error_class = _RUNTIME_CLASS_MAP[failure.error_class]
        allowed = self._allowed(code, failure.retryable, failure.termination_confirmed)
        scope = affected_scope or _DEFAULT_SCOPES.get(
            code, AffectedScope(kind="runtime_environment")
        )
        return self._build(
            error_class=error_class,
            code=code,
            stage=failure.stage.value,
            operation=failure.operation.value if failure.operation else None,
            causes=(
                CauseSummary(exception_type=item.exception_type, message=item.message)
                for item in failure.causes
            ),
            retryable=failure.retryable,
            termination_confirmed=failure.termination_confirmed,
            scope=scope,
            suspected_component=suspected_component,
            observation=observation,
            allowed=allowed,
        )

    def from_observation(
        self,
        observation: Observation,
        *,
        affected_scope: AffectedScope | None = None,
    ) -> Diagnosis:
        runtime_payload = observation.data.get("failure")
        if runtime_payload:
            return self.from_runtime(
                RuntimeFailure.model_validate(runtime_payload),
                observation=observation,
                affected_scope=affected_scope,
                suspected_component=observation.location,
            )
        error_class, code = _OBSERVATION_CODES.get(
            observation.error_class or "",
            (DiagnosticErrorClass.RUNTIME, ErrorCode.UNKNOWN),
        )
        causes = ()
        if observation.exception_type:
            causes = (
                CauseSummary(
                    exception_type=observation.exception_type,
                    message=str(observation.data.get("message", observation.status)),
                ),
            )
        return self._build(
            error_class=error_class,
            code=code,
            stage=observation.stage,
            operation=str(observation.data.get("operation"))
            if observation.data.get("operation")
            else None,
            causes=causes,
            retryable=observation.retryable,
            termination_confirmed=observation.data.get("termination_confirmed"),
            scope=affected_scope
            or _DEFAULT_SCOPES.get(code, AffectedScope(kind="unknown")),
            suspected_component=observation.location,
            observation=observation,
            allowed=self._allowed(
                code, observation.retryable, observation.data.get("termination_confirmed")
            ),
        )

    def _build(
        self,
        *,
        error_class: DiagnosticErrorClass,
        code: ErrorCode,
        stage: str,
        operation: str | None,
        causes: Iterable[CauseSummary],
        retryable: bool,
        termination_confirmed: bool | None,
        scope: AffectedScope,
        suspected_component: str | None,
        observation: Observation,
        allowed: frozenset[RepairKind],
    ) -> Diagnosis:
        chain = tuple(causes)
        fingerprint = _fingerprint(error_class, code, stage, operation, chain, scope)
        return Diagnosis(
            error_class=error_class,
            error_code=code,
            fingerprint=fingerprint,
            stage=stage,
            operation=operation,
            exception_chain=chain,
            retryable=retryable,
            termination_confirmed=termination_confirmed,
            affected_scope=scope,
            suspected_component=suspected_component,
            evidence=(
                EvidenceReference(
                    observation_id=observation.observation_id,
                    source=f"{observation.source.kind}:{observation.source.identifier}",
                    artifacts=tuple(item.uri for item in observation.artifacts),
                ),
            ),
            compatible_checkpoint=observation.checkpoint,
            allowed_repair_kinds=allowed,
            severity=Severity.ERROR if retryable else Severity.CRITICAL,
            confidence=1.0 if code != ErrorCode.UNKNOWN else 0.4,
        )

    @staticmethod
    def _allowed(
        code: ErrorCode, retryable: bool, termination_confirmed: bool | None
    ) -> frozenset[RepairKind]:
        if not retryable or code in {ErrorCode.RUNTIME_UNAVAILABLE, ErrorCode.CANCELLED}:
            return frozenset()
        if code == ErrorCode.TIMEOUT and termination_confirmed is not True:
            return frozenset()
        if code == ErrorCode.NON_CONVERGENCE:
            return frozenset({RepairKind.SOLVER_STRATEGY})
        return frozenset(
            {
                RepairKind.DETERMINISTIC_RULE,
                RepairKind.LOCAL_PATTERN,
                RepairKind.REPAIR_CASE,
                RepairKind.LLM_PATCH,
            }
        )


def _fingerprint(
    error_class: DiagnosticErrorClass,
    code: ErrorCode,
    stage: str,
    operation: str | None,
    causes: tuple[CauseSummary, ...],
    scope: AffectedScope,
) -> str:
    payload = {
        "error_class": error_class,
        "code": code,
        "stage": stage,
        "operation": operation,
        "causes": [item.model_dump(mode="json") for item in causes],
        "scope": scope.model_dump(mode="json"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()
