"""Deterministic-priority, bounded, evidence-driven repair orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from comsol_agent.v2.contracts import Observation, RepairRecord, RunManifest
from comsol_agent.v2.extensions import ExtensionKind, ExtensionSnapshot, ResolutionContext
from comsol_agent.v2.kernel import CancellationToken, RunCancelledError

from .diagnosis import DiagnosticService
from .models import (
    Diagnosis,
    ErrorCode,
    RepairAttempt,
    RepairCandidate,
    RepairKind,
    RepairResult,
    RepairRuleContract,
    RepairStatus,
    RepairTraceEvent,
    SolverStrategyContract,
)


class RepairExecutor(Protocol):
    async def create_checkpoint(
        self, diagnosis: Diagnosis, candidate: RepairCandidate
    ) -> str: ...

    async def apply(self, candidate: RepairCandidate) -> None: ...

    async def verify(
        self, candidate: RepairCandidate, trigger: Observation
    ) -> Observation: ...

    async def rollback(self, checkpoint: str) -> None: ...

    async def commit(self, checkpoint: str) -> None: ...


CandidateProvider = Callable[
    [Diagnosis, Observation], Awaitable[RepairCandidate | None]
]


class RepairOrchestrator:
    """Apply the fixed M6 source order with budgets, verifier, and rollback."""

    def __init__(
        self,
        *,
        diagnostics: DiagnosticService,
        snapshot: ExtensionSnapshot,
        executor: RepairExecutor,
        local_pattern: CandidateProvider | None = None,
        repair_case: CandidateProvider | None = None,
        llm_patch: CandidateProvider | None = None,
        max_attempts_per_stage: int = 3,
        max_llm_attempts: int = 2,
    ) -> None:
        if not 1 <= max_attempts_per_stage <= 3:
            raise ValueError("max_attempts_per_stage must be between one and three")
        if not 0 <= max_llm_attempts <= 2:
            raise ValueError("max_llm_attempts must be between zero and two")
        self.diagnostics = diagnostics
        self.snapshot = snapshot
        self.executor = executor
        self.local_pattern = local_pattern
        self.repair_case = repair_case
        self.llm_patch = llm_patch
        self.max_attempts_per_stage = max_attempts_per_stage
        self.max_llm_attempts = max_llm_attempts

    async def repair(
        self,
        observation: Observation,
        diagnosis: Diagnosis,
        *,
        cancellation: CancellationToken | None = None,
    ) -> RepairResult:
        token = cancellation or CancellationToken()
        trace: list[RepairTraceEvent] = []
        attempts: list[RepairAttempt] = []
        self._trace(trace, "diagnosis", diagnosis, observation_id=observation.observation_id)
        if not diagnosis.allowed_repair_kinds:
            return self._finish(
                RepairStatus.USER_DECISION_REQUIRED,
                diagnosis,
                attempts,
                trace,
                self._unrepairable_message(diagnosis),
            )

        try:
            extensions, conflict = self._extension_candidates(diagnosis, observation)
            if conflict:
                self._trace(trace, "conflict", diagnosis, detail={"extensions": conflict})
                return self._finish(
                    RepairStatus.CONFLICT,
                    diagnosis,
                    attempts,
                    trace,
                    f"多个同优先级修复扩展冲突：{', '.join(conflict)}",
                )
            providers = [
                (RepairKind.LOCAL_PATTERN, self.local_pattern),
                (RepairKind.REPAIR_CASE, self.repair_case),
                (RepairKind.LLM_PATCH, self.llm_patch),
            ]
            llm_attempts = 0
            source_items: list[tuple[RepairKind, object]] = [
                (kind, extension) for kind, extension in extensions
            ]
            source_items.extend((kind, provider) for kind, provider in providers if provider)
            for kind, source in source_items:
                token.raise_if_cancelled()
                if len(attempts) >= self.max_attempts_per_stage:
                    return self._finish(
                        RepairStatus.BUDGET_EXHAUSTED,
                        diagnosis,
                        attempts,
                        trace,
                        f"修复预算已耗尽（阶段上限 {self.max_attempts_per_stage} 次）。",
                    )
                if kind == RepairKind.LLM_PATCH:
                    if llm_attempts >= self.max_llm_attempts:
                        continue
                    llm_attempts += 1
                candidate = await self._propose(source, kind, diagnosis, observation, trace)
                if candidate is None:
                    continue
                safety = self._safety_error(candidate, diagnosis, source)
                self._trace(
                    trace,
                    "candidate",
                    diagnosis,
                    candidate=candidate,
                    detail={"kind": candidate.kind, "safety_error": safety},
                )
                if safety:
                    attempts.append(
                        RepairAttempt(candidate=candidate, failure_reason=safety)
                    )
                    continue
                checkpoint = await self.executor.create_checkpoint(diagnosis, candidate)
                attempt = RepairAttempt(candidate=candidate, checkpoint=checkpoint)
                attempts.append(attempt)
                self._trace(
                    trace, "checkpoint", diagnosis, candidate=candidate, checkpoint=checkpoint
                )
                try:
                    await self.executor.apply(candidate)
                    self._trace(trace, "repair", diagnosis, candidate=candidate)
                    verified = await self.executor.verify(candidate, observation)
                    attempt.verification_observation_id = verified.observation_id
                    self._trace(
                        trace,
                        "verify",
                        diagnosis,
                        candidate=candidate,
                        observation_id=verified.observation_id,
                        detail={"success": verified.success, "gates": verified.data.get("gates")},
                    )
                    if self._verified(candidate, verified):
                        attempt.success = True
                        commit = getattr(self.executor, "commit", None)
                        if commit is not None:
                            await commit(checkpoint)
                        self._record_repair_case_outcome(candidate, True)
                        self._trace(trace, "complete", diagnosis, candidate=candidate)
                        return RepairResult(
                            status=RepairStatus.COMPLETED,
                            diagnosis=diagnosis,
                            attempts=attempts,
                            trace=trace,
                            final_observation_id=verified.observation_id,
                            user_message="局部修复已通过声明的复验器和后置门禁。",
                        )
                    repeated = self.diagnostics.from_observation(
                        verified, affected_scope=diagnosis.affected_scope
                    ).fingerprint == diagnosis.fingerprint
                    await self.executor.rollback(checkpoint)
                    attempt.rolled_back = True
                    attempt.failure_reason = (
                        "same failure fingerprint repeated"
                        if repeated
                        else "verifier or postcondition failed"
                    )
                    self._record_repair_case_outcome(candidate, False)
                    self._trace(
                        trace,
                        "rollback",
                        diagnosis,
                        candidate=candidate,
                        checkpoint=checkpoint,
                        detail={"reason": attempt.failure_reason},
                    )
                    if repeated:
                        return self._finish(
                            RepairStatus.REPEATED_FAILURE,
                            diagnosis,
                            attempts,
                            trace,
                            "复验返回相同失败指纹，已停止原样重试并回滚。",
                        )
                except RunCancelledError:
                    await self.executor.rollback(checkpoint)
                    attempt.rolled_back = True
                    self._trace(
                        trace, "rollback", diagnosis, candidate=candidate, checkpoint=checkpoint
                    )
                    raise
                except Exception as error:
                    await self.executor.rollback(checkpoint)
                    attempt.rolled_back = True
                    attempt.failure_reason = f"{type(error).__name__}: {error}"
                    self._record_repair_case_outcome(candidate, False)
                    self._trace(
                        trace,
                        "rollback",
                        diagnosis,
                        candidate=candidate,
                        checkpoint=checkpoint,
                        detail={"reason": attempt.failure_reason},
                    )
            status = (
                RepairStatus.BUDGET_EXHAUSTED
                if len(attempts) >= self.max_attempts_per_stage
                else RepairStatus.UNSAFE
                if attempts
                else RepairStatus.FAILED
            )
            return self._finish(
                status,
                diagnosis,
                attempts,
                trace,
                (
                    f"修复预算已耗尽（阶段上限 {self.max_attempts_per_stage} 次）。"
                    if status == RepairStatus.BUDGET_EXHAUSTED
                    else "没有候选满足作用域、权限、兼容性和复验要求；需要用户决策。"
                ),
            )
        except RunCancelledError:
            return self._finish(
                RepairStatus.CANCELLED,
                diagnosis,
                attempts,
                trace,
                "修复已取消；已创建的检查点均已回滚。",
            )

    def _extension_candidates(
        self, diagnosis: Diagnosis, observation: Observation
    ) -> tuple[list[tuple[RepairKind, object]], list[str]]:
        if diagnosis.error_code == ErrorCode.NON_CONVERGENCE:
            kind = ExtensionKind.SOLVER_STRATEGY
            repair_kind = RepairKind.SOLVER_STRATEGY
        else:
            kind = ExtensionKind.REPAIR_RULE
            repair_kind = RepairKind.DETERMINISTIC_RULE
        context = ResolutionContext(
            signature=diagnosis.model_dump(mode="json")
        )
        candidates = [
            item
            for item in self.snapshot.candidates(kind, "repair", context)
            if item.matches(observation, context)
            and self._contract_matches(item, diagnosis)
        ]
        if len(candidates) > 1:
            first = candidates[0].manifest
            tied = [
                item.manifest.id
                for item in candidates
                if item.manifest.priority == first.priority
                and item.manifest.quality == first.quality
            ]
            if len(tied) > 1:
                return [], tied
        return [(repair_kind, item) for item in candidates], []

    @staticmethod
    def record_manifest(manifest: RunManifest, result: RepairResult) -> None:
        """Persist the complete M6 repair facts into the M1 RunManifest."""
        for index, attempt in enumerate(result.attempts, start=1):
            candidate = attempt.candidate
            manifest.repairs.append(
                RepairRecord(
                    action_id=candidate.candidate_id,
                    error_class=result.diagnosis.error_class,
                    attempt=index,
                    verifier=candidate.verifier,
                    diagnosis_id=result.diagnosis.diagnosis_id,
                    error_code=result.diagnosis.error_code,
                    observation_id=candidate.observation_id,
                    candidate_id=candidate.candidate_id,
                    source=candidate.provenance,
                    scope=candidate.scope.model_dump(mode="json"),
                    checkpoint=attempt.checkpoint,
                    repair_case_id=candidate.repair_case_id,
                    outcome="success" if attempt.success else attempt.failure_reason,
                    rolled_back=attempt.rolled_back,
                )
            )
            if attempt.checkpoint and attempt.checkpoint not in manifest.checkpoints:
                manifest.checkpoints.append(attempt.checkpoint)
        manifest.trace_events.extend(
            event.model_dump(mode="json") for event in result.trace
        )

    @staticmethod
    def _contract_matches(extension: object, diagnosis: Diagnosis) -> bool:
        declared = extension.manifest.repair_contract  # type: ignore[attr-defined]
        contract = RepairRuleContract.model_validate(declared) if declared else None
        if contract is not None:
            return contract.matches(diagnosis)
        declared_strategy = extension.manifest.solver_strategy_contract  # type: ignore[attr-defined]
        strategy = (
            SolverStrategyContract.model_validate(declared_strategy)
            if declared_strategy
            else None
        )
        return strategy is not None and diagnosis.error_code in strategy.error_codes

    async def _propose(
        self,
        source: object,
        kind: RepairKind,
        diagnosis: Diagnosis,
        observation: Observation,
        trace: list[RepairTraceEvent],
    ) -> RepairCandidate | None:
        try:
            if kind in {RepairKind.DETERMINISTIC_RULE, RepairKind.SOLVER_STRATEGY}:
                raw = await source.propose(observation)  # type: ignore[attr-defined]
                candidate = (
                    raw if isinstance(raw, RepairCandidate) else RepairCandidate.model_validate(raw)
                )
                return candidate.model_copy(
                    update={
                        "extension_id": source.manifest.id,  # type: ignore[attr-defined]
                        "extension_version": source.manifest.version,  # type: ignore[attr-defined]
                    }
                )
            provider = source
            return await provider(diagnosis, observation)  # type: ignore[operator]
        except Exception as error:
            self._trace(
                trace,
                "candidate_error",
                diagnosis,
                detail={"kind": kind, "error": f"{type(error).__name__}: {error}"},
            )
            return None

    @staticmethod
    def _safety_error(
        candidate: RepairCandidate, diagnosis: Diagnosis, source: object
    ) -> str | None:
        if candidate.kind not in diagnosis.allowed_repair_kinds:
            return f"repair kind {candidate.kind} is not allowed for {diagnosis.error_code}"
        if candidate.observation_id != diagnosis.evidence[0].observation_id:
            return "candidate does not cite the triggering Observation"
        if candidate.diagnosis_fingerprint != diagnosis.fingerprint:
            return "candidate diagnosis fingerprint mismatch"
        if diagnosis.error_code == ErrorCode.NON_CONVERGENCE and candidate.scope.kind != "solver":
            return "non-convergence repairs are restricted to solver scope"
        if (
            diagnosis.error_code == ErrorCode.PHYSICS_AUDIT_FAILURE
            and candidate.scope.kind == "audit_threshold"
        ):
            return "physics audit failures cannot be repaired by relaxing thresholds"
        manifest = getattr(source, "manifest", None)
        declared_rule = getattr(manifest, "repair_contract", None)
        declared_strategy = getattr(manifest, "solver_strategy_contract", None)
        contract = (
            RepairRuleContract.model_validate(declared_rule)
            if declared_rule
            else SolverStrategyContract.model_validate(declared_strategy)
            if declared_strategy
            else None
        )
        if contract is not None:
            allowed_scope = getattr(contract, "modification_scope", None) or getattr(
                contract, "solver_scope", None
            )
            if allowed_scope and not allowed_scope.contains(candidate.scope):
                return "candidate exceeds the declared modification scope"
            if (
                isinstance(contract, RepairRuleContract)
                and candidate.verifier != contract.verifier
            ):
                return "candidate verifier differs from the rule contract"
            if (
                isinstance(contract, RepairRuleContract)
                and contract.rollback_required
                and not candidate.checkpoint_required
            ):
                return "rule requires a rollback checkpoint"
            if not contract.required_permissions.issubset(candidate.permissions):
                return "candidate omits permissions required by its contract"
            if not candidate.permissions.issubset(source.manifest.permissions.tokens()):
                return "candidate attempts to elevate extension permissions"
        return None

    @staticmethod
    def _verified(candidate: RepairCandidate, observation: Observation) -> bool:
        if not observation.success:
            return False
        gates = observation.data.get("gates", {})
        return all(gates.get(gate) is True for gate in candidate.required_gates)

    def _record_repair_case_outcome(
        self, candidate: RepairCandidate, success: bool
    ) -> None:
        if candidate.kind != RepairKind.REPAIR_CASE or self.repair_case is None:
            return
        recorder = getattr(self.repair_case, "record_result", None)
        if recorder is not None:
            recorder(candidate, success)

    @staticmethod
    def _unrepairable_message(diagnosis: Diagnosis) -> str:
        if diagnosis.error_code == ErrorCode.RUNTIME_UNAVAILABLE:
            return "COMSOL 运行环境不可用；不会修改代码或模型，请恢复运行时资源后重试。"
        if diagnosis.error_code == ErrorCode.CANCELLED:
            return "运行已取消；策略禁止自动重试。"
        if diagnosis.error_code == ErrorCode.TIMEOUT:
            return "超时终止尚未确认；Worker 隔离前不会自动修改或重试。"
        return f"错误 {diagnosis.error_code} 当前没有安全的自动修复路径。"

    @staticmethod
    def _trace(
        trace: list[RepairTraceEvent],
        event: str,
        diagnosis: Diagnosis,
        *,
        candidate: RepairCandidate | None = None,
        observation_id: str | None = None,
        checkpoint: str | None = None,
        detail: dict | None = None,
    ) -> None:
        trace.append(
            RepairTraceEvent(
                sequence=len(trace) + 1,
                event=event,
                diagnosis_id=diagnosis.diagnosis_id,
                candidate_id=candidate.candidate_id if candidate else None,
                observation_id=observation_id,
                checkpoint=checkpoint,
                detail=detail or {},
            )
        )

    @staticmethod
    def _finish(
        status: RepairStatus,
        diagnosis: Diagnosis,
        attempts: list[RepairAttempt],
        trace: list[RepairTraceEvent],
        message: str,
    ) -> RepairResult:
        if not trace or trace[-1].event not in {"complete", "failure"}:
            RepairOrchestrator._trace(
                trace, "failure", diagnosis, detail={"status": status, "message": message}
            )
        return RepairResult(
            status=status,
            diagnosis=diagnosis,
            attempts=attempts,
            trace=trace,
            user_message=message,
        )
