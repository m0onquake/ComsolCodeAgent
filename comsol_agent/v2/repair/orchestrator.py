"""Deterministic-priority, bounded, evidence-driven repair orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from fnmatch import fnmatchcase
from typing import Protocol

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from comsol_agent.v2.contracts import Observation, RepairRecord, RunManifest
from comsol_agent.v2.extensions import ExtensionKind, ExtensionSnapshot, ResolutionContext
from comsol_agent.v2.kernel import CancellationToken, RunCancelledError

from .diagnosis import DiagnosticService
from .models import (
    Diagnosis,
    ErrorCode,
    RepairAttempt,
    RepairCandidate,
    RepairExecutionContext,
    RepairExecutionLimits,
    RepairKind,
    RepairResult,
    RepairRuleContract,
    RepairStatus,
    RepairTraceEvent,
    SolverStrategyContract,
    VersionCompatibility,
)


class RepairExecutor(Protocol):
    async def create_checkpoint(
        self, diagnosis: Diagnosis, candidate: RepairCandidate
    ) -> str: ...

    async def apply(
        self, candidate: RepairCandidate, limits: RepairExecutionLimits
    ) -> None: ...

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
        execution_context: RepairExecutionContext | None = None,
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
        self.execution_context = execution_context or RepairExecutionContext(
            agent_version=snapshot.agent_version,
            comsol_version=snapshot.comsol_version,
        )
        self._extension_attempts: dict[tuple[str, str], int] = {}
        self._solve_attempts_used = self.execution_context.solve_attempts_used
        self._core_hours_used = self.execution_context.core_hours_used

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
                contract = self._contract(source)
                contract_error = self._contract_execution_error(
                    contract, diagnosis, source
                )
                if contract_error:
                    self._trace(
                        trace,
                        "contract_rejected",
                        diagnosis,
                        detail={
                            "kind": kind,
                            "extension_id": getattr(
                                getattr(source, "manifest", None), "id", None
                            ),
                            "reason": contract_error,
                        },
                    )
                    if contract_error.startswith("solver budget exhausted"):
                        return self._finish(
                            RepairStatus.BUDGET_EXHAUSTED,
                            diagnosis,
                            attempts,
                            trace,
                            contract_error,
                        )
                    continue
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
                limits = self._execution_limits(candidate, diagnosis, contract)
                attempt = RepairAttempt(candidate=candidate)
                attempts.append(attempt)
                if candidate.extension_id:
                    key = (diagnosis.stage, candidate.extension_id)
                    self._extension_attempts[key] = self._extension_attempts.get(key, 0) + 1
                try:
                    checkpoint = await self.executor.create_checkpoint(diagnosis, candidate)
                    if not checkpoint:
                        raise ValueError("executor returned an empty checkpoint reference")
                    attempt.checkpoint = checkpoint
                    self._trace(
                        trace,
                        "checkpoint",
                        diagnosis,
                        candidate=candidate,
                        checkpoint=checkpoint,
                    )
                except RunCancelledError:
                    attempt.failure_reason = "RunCancelledError: checkpoint creation cancelled"
                    raise
                except Exception as error:
                    attempt.failure_reason = f"{type(error).__name__}: {error}"
                    self._trace(
                        trace,
                        "checkpoint_failed",
                        diagnosis,
                        candidate=candidate,
                        detail={"error": attempt.failure_reason},
                    )
                    return self._finish(
                        RepairStatus.CHECKPOINT_FAILED,
                        diagnosis,
                        attempts,
                        trace,
                        "无法创建修复检查点；候选未执行，已安全停止。",
                    )
                try:
                    await self.executor.apply(candidate, limits)
                    self._trace(trace, "repair", diagnosis, candidate=candidate)
                    verified = await self.executor.verify(candidate, observation)
                    self._account_solver_usage(verified, contract)
                    attempt.verification_observation_id = verified.observation_id
                    self._trace(
                        trace,
                        "verify",
                        diagnosis,
                        candidate=candidate,
                        observation_id=verified.observation_id,
                        detail={"success": verified.success, "gates": verified.data.get("gates")},
                    )
                    verified_ok, verification_error = self._verified(
                        candidate, verified, limits
                    )
                    if verified_ok:
                        commit = getattr(self.executor, "commit", None)
                        try:
                            if commit is not None:
                                await commit(checkpoint)
                        except Exception as error:
                            attempt.failure_reason = f"{type(error).__name__}: {error}"
                            rollback_ok = await self._safe_rollback(
                                checkpoint,
                                attempt,
                                diagnosis,
                                trace,
                                reason="commit failed",
                            )
                            return self._finish(
                                RepairStatus.COMMIT_FAILED
                                if rollback_ok
                                else RepairStatus.ROLLBACK_FAILED,
                                diagnosis,
                                attempts,
                                trace,
                                "提交修复检查点失败；已回滚。"
                                if rollback_ok
                                else "提交与回滚均失败；运行已隔离，需要人工恢复。",
                                manual_recovery_required=not rollback_ok,
                            )
                        attempt.success = True
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
                    attempt.failure_reason = (
                        "same failure fingerprint repeated"
                        if repeated
                        else verification_error or "verifier or postcondition failed"
                    )
                    self._record_repair_case_outcome(candidate, False)
                    rollback_ok = await self._safe_rollback(
                        checkpoint,
                        attempt,
                        diagnosis,
                        trace,
                        reason=attempt.failure_reason,
                    )
                    if not rollback_ok:
                        return self._finish(
                            RepairStatus.ROLLBACK_FAILED,
                            diagnosis,
                            attempts,
                            trace,
                            "复验失败且无法确认回滚；运行已隔离，需要人工恢复。",
                            manual_recovery_required=True,
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
                    attempt.failure_reason = "RunCancelledError: repair cancelled"
                    rollback_ok = await self._safe_rollback(
                        checkpoint, attempt, diagnosis, trace, reason="repair cancelled"
                    )
                    if not rollback_ok:
                        return self._finish(
                            RepairStatus.ROLLBACK_FAILED,
                            diagnosis,
                            attempts,
                            trace,
                            "修复已取消但回滚失败；运行已隔离，需要人工恢复。",
                            manual_recovery_required=True,
                        )
                    raise
                except Exception as error:
                    attempt.failure_reason = f"{type(error).__name__}: {error}"
                    self._record_repair_case_outcome(candidate, False)
                    rollback_ok = await self._safe_rollback(
                        checkpoint,
                        attempt,
                        diagnosis,
                        trace,
                        reason=attempt.failure_reason,
                    )
                    if not rollback_ok:
                        return self._finish(
                            RepairStatus.ROLLBACK_FAILED,
                            diagnosis,
                            attempts,
                            trace,
                            "修复执行失败且无法确认回滚；运行已隔离，需要人工恢复。",
                            manual_recovery_required=True,
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

    @staticmethod
    def _contract(source: object) -> RepairRuleContract | SolverStrategyContract | None:
        manifest = getattr(source, "manifest", None)
        declared_rule = getattr(manifest, "repair_contract", None)
        if declared_rule:
            return RepairRuleContract.model_validate(declared_rule)
        declared_strategy = getattr(manifest, "solver_strategy_contract", None)
        if declared_strategy:
            return SolverStrategyContract.model_validate(declared_strategy)
        return None

    def _contract_execution_error(
        self,
        contract: RepairRuleContract | SolverStrategyContract | None,
        diagnosis: Diagnosis,
        source: object,
    ) -> str | None:
        if contract is None:
            return None
        automatic = {"structured_evidence"} if diagnosis.evidence else set()
        if diagnosis.compatible_checkpoint:
            automatic.add("compatible_checkpoint")
        satisfied = self.execution_context.satisfied_preconditions | automatic
        missing = [item for item in contract.preconditions if item not in satisfied]
        if missing:
            return f"contract precondition not satisfied: {', '.join(missing)}"
        compatibility_error = self._compatibility_error(contract.compatibility)
        if compatibility_error:
            return compatibility_error
        if isinstance(contract, RepairRuleContract):
            extension_id = getattr(getattr(source, "manifest", None), "id", "")
            extension_attempts = self._extension_attempts.get(
                (diagnosis.stage, extension_id), 0
            )
            if extension_attempts >= contract.max_attempts:
                return f"repair rule attempt budget exhausted ({contract.max_attempts})"
            return None
        if self._solve_attempts_used >= contract.max_solves:
            return f"solver budget exhausted: max_solves={contract.max_solves}"
        if self._core_hours_used >= contract.core_hour_budget:
            return (
                "solver budget exhausted: "
                f"core_hour_budget={contract.core_hour_budget}"
            )
        if (
            diagnosis.compatible_checkpoint is None
            or diagnosis.compatible_checkpoint != contract.rollback_checkpoint
        ):
            return "solver rollback checkpoint is unavailable or incompatible"
        return None

    def _compatibility_error(self, compatibility: object) -> str | None:
        declared = VersionCompatibility.model_validate(compatibility)
        try:
            if Version(self.execution_context.agent_version) not in SpecifierSet(
                declared.agent_api
            ):
                return "contract is incompatible with the active Agent version"
        except (InvalidSpecifier, InvalidVersion) as error:
            return f"invalid Agent compatibility contract: {error}"
        if declared.comsol:
            actual = self.execution_context.comsol_version
            if actual is None:
                return "contract requires a known COMSOL version"
            if not any(
                fnmatchcase(actual, pattern.replace("x", "*"))
                for pattern in declared.comsol
            ):
                return "contract is incompatible with the active COMSOL version"
        for builder_id, constraint in declared.builders.items():
            actual = self.execution_context.builder_versions.get(builder_id)
            if actual is None:
                return f"required Builder version is unknown: {builder_id}"
            try:
                if Version(actual) not in SpecifierSet(constraint):
                    return f"contract is incompatible with Builder {builder_id} {actual}"
            except (InvalidSpecifier, InvalidVersion) as error:
                return f"invalid Builder compatibility contract for {builder_id}: {error}"
        return None

    def _execution_limits(
        self,
        candidate: RepairCandidate,
        diagnosis: Diagnosis,
        contract: RepairRuleContract | SolverStrategyContract | None,
    ) -> RepairExecutionLimits:
        required_gates = (
            self._mandatory_gates(diagnosis)
            | self.execution_context.mandatory_gates
            | candidate.required_gates
        )
        if isinstance(contract, SolverStrategyContract):
            return RepairExecutionLimits(
                max_solves=contract.max_solves
                - self._solve_attempts_used,
                core_hour_budget=contract.core_hour_budget
                - self._core_hours_used,
                required_checkpoint=contract.rollback_checkpoint,
                required_gates=required_gates,
                success_criteria=contract.success_criteria,
            )
        return RepairExecutionLimits(required_gates=required_gates)

    def _account_solver_usage(
        self,
        observation: Observation,
        contract: RepairRuleContract | SolverStrategyContract | None,
    ) -> None:
        if not isinstance(contract, SolverStrategyContract):
            return
        usage = observation.data.get("usage", {})
        solves = usage.get("solves")
        core_hours = usage.get("core_hours")
        if type(solves) is int and solves >= 0:
            self._solve_attempts_used += solves
        if (
            isinstance(core_hours, (int, float))
            and not isinstance(core_hours, bool)
            and core_hours >= 0
        ):
            self._core_hours_used += float(core_hours)

    @staticmethod
    def _mandatory_gates(diagnosis: Diagnosis) -> frozenset[str]:
        gate_by_class = {
            "api_code_error": "api",
            "geometry_error": "api",
            "mesh_error": "api",
            "solve_or_convergence_error": "solve",
            "physics_audit_failure": "audit",
            "test_failure": "pytest",
            "static_analysis_failure": "ruff",
            "file_patch_failure": "static",
        }
        gate = gate_by_class.get(str(diagnosis.error_class))
        return frozenset({gate}) if gate else frozenset({"runtime"})

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
    def _verified(
        candidate: RepairCandidate,
        observation: Observation,
        limits: RepairExecutionLimits,
    ) -> tuple[bool, str | None]:
        if not observation.success:
            return False, "verifier Observation reported failure"
        gates = observation.data.get("gates", {})
        missing_gates = [
            gate for gate in sorted(limits.required_gates) if gates.get(gate) is not True
        ]
        if missing_gates:
            return False, f"mandatory gates failed or missing: {', '.join(missing_gates)}"
        criteria = observation.data.get("criteria", {})
        failed_criteria = [
            criterion
            for criterion in limits.success_criteria
            if criteria.get(criterion) is not True
        ]
        if failed_criteria:
            return False, f"success criteria failed or missing: {', '.join(failed_criteria)}"
        usage = observation.data.get("usage", {})
        solves = usage.get("solves", 0)
        core_hours = usage.get("core_hours", 0.0)
        if type(solves) is not int or solves < 0:
            return False, "invalid solver usage evidence"
        if (
            not isinstance(core_hours, (int, float))
            or isinstance(core_hours, bool)
            or core_hours < 0
        ):
            return False, "invalid core-hour usage evidence"
        if limits.max_solves is not None and solves > limits.max_solves:
            return False, "solver max_solves budget exceeded"
        if (
            limits.core_hour_budget is not None
            and core_hours > limits.core_hour_budget
        ):
            return False, "solver core-hour budget exceeded"
        return True, None

    async def _safe_rollback(
        self,
        checkpoint: str,
        attempt: RepairAttempt,
        diagnosis: Diagnosis,
        trace: list[RepairTraceEvent],
        *,
        reason: str,
    ) -> bool:
        try:
            await self.executor.rollback(checkpoint)
        except Exception as error:
            attempt.rollback_failure = f"{type(error).__name__}: {error}"
            self._trace(
                trace,
                "rollback_failed",
                diagnosis,
                candidate=attempt.candidate,
                checkpoint=checkpoint,
                detail={
                    "reason": reason,
                    "rollback_error": attempt.rollback_failure,
                },
            )
            return False
        attempt.rolled_back = True
        self._trace(
            trace,
            "rollback",
            diagnosis,
            candidate=attempt.candidate,
            checkpoint=checkpoint,
            detail={"reason": reason},
        )
        return True

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
        *,
        manual_recovery_required: bool = False,
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
            manual_recovery_required=manual_recovery_required,
        )
