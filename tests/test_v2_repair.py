"""M6 diagnosis, dynamic repair, solver strategy, and bounded orchestration tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from comsol_agent.v2.contracts import (
    Action,
    ArtifactRef,
    GoalSpec,
    Observation,
    Plan,
    PlanStep,
    RunManifest,
    SourceRef,
)
from comsol_agent.v2.extensions import (
    API_VERSION,
    CompatibilityPolicy,
    ExtensionKind,
    ExtensionLoader,
    ExtensionManifest,
    ExtensionRegistry,
    HealthReport,
    HealthStatus,
    PermissionPolicy,
    PermissionSet,
)
from comsol_agent.v2.kernel import RunCancelledError
from comsol_agent.v2.memory import (
    HybridRetriever,
    MemoryCompatibility,
    MemoryGovernance,
    MemoryLayer,
    MemoryProvenance,
    MemoryRecord,
    MemoryRepository,
    MemoryType,
    QueryCompatibility,
    ReferenceCatalog,
    RepairCase,
    RepairVerification,
    RetrievalEvaluator,
)
from comsol_agent.v2.repair import (
    AffectedScope,
    Diagnosis,
    DiagnosticService,
    ErrorCode,
    GovernedRepairCaseSource,
    RepairCandidate,
    RepairKind,
    RepairOrchestrator,
    RepairRuleContract,
    RepairStatus,
    SolverStrategyContract,
    VersionCompatibility,
    WorkspaceRepairExecutor,
)
from comsol_agent.v2.runtime.comsol import (
    CauseFrame,
    RuntimeFailure,
    RuntimeOperation,
    RuntimeStage,
)
from comsol_agent.v2.runtime.comsol import (
    ErrorClass as RuntimeErrorClass,
)
from comsol_agent.v2.tools import PatchSet, TextReplacement, Workspace


def observation(
    *,
    success: bool = False,
    error_class: str = "pytest_failure",
    stage: str = "build",
    data: dict[str, Any] | None = None,
    checkpoint: str | None = "checkpoint-B",
) -> Observation:
    return Observation(
        action_id="action-1",
        success=success,
        status="passed" if success else "failed",
        stage=stage,
        data=data or {},
        error_class=None if success else error_class,
        retryable=not success,
        checkpoint=checkpoint,
        source=SourceRef(kind="fixture", identifier="m6"),
    )


def runtime_diagnosis(
    code: ErrorCode,
    error_class: RuntimeErrorClass,
    trigger: Observation,
    *,
    stage: RuntimeStage = RuntimeStage.BUILD,
    termination_confirmed: bool | None = None,
    retryable: bool = True,
    scope: AffectedScope | None = None,
) -> Diagnosis:
    failure = RuntimeFailure(
        error_class=error_class,
        code=code,
        message=code,
        stage=stage,
        operation=RuntimeOperation.BUILD,
        retryable=retryable,
        causes=[CauseFrame(exception_type="FixtureError", message=code)],
        termination_confirmed=termination_confirmed,
    )
    return DiagnosticService().from_runtime(
        failure,
        observation=trigger,
        affected_scope=scope,
        suspected_component="fixture.node",
    )


class FakeExecutor:
    def __init__(self, verifications: list[Observation] | None = None) -> None:
        self.verifications = verifications or [observation(success=True, data={"gates": {}})]
        self.applied: list[RepairCandidate] = []
        self.rolled_back: list[str] = []
        self.committed: list[str] = []

    async def create_checkpoint(
        self, diagnosis: Diagnosis, candidate: RepairCandidate
    ) -> str:
        return f"checkpoint:{candidate.candidate_id}"

    async def apply(self, candidate: RepairCandidate) -> None:
        self.applied.append(candidate)

    async def verify(
        self, candidate: RepairCandidate, trigger: Observation
    ) -> Observation:
        return self.verifications.pop(0)

    async def rollback(self, checkpoint: str) -> None:
        self.rolled_back.append(checkpoint)

    async def commit(self, checkpoint: str) -> None:
        self.committed.append(checkpoint)


class Rule:
    def __init__(
        self,
        diagnosis: Diagnosis,
        *,
        extension_id: str = "fixture.rule",
        priority: int = 100,
        candidate_scope: AffectedScope | None = None,
        fail_proposal: bool = False,
    ) -> None:
        self.active = False
        self.diagnosis = diagnosis
        self.fail_proposal = fail_proposal
        self.candidate_scope = candidate_scope or diagnosis.affected_scope
        self.repair_contract = RepairRuleContract(
            error_classes=frozenset({diagnosis.error_class}),
            error_codes=frozenset({diagnosis.error_code}),
            stages=frozenset({diagnosis.stage}),
            preconditions=("structured evidence exists",),
            modification_scope=diagnosis.affected_scope,
            required_permissions=frozenset(),
            max_attempts=1,
            verifier="fixture.verify",
            rollback_required=True,
            compatibility=VersionCompatibility(agent_api=">=2.0,<3", comsol=("6.x",)),
            provenance="tests/test_v2_repair.py",
        )
        self.manifest = ExtensionManifest(
            api_version=API_VERSION,
            kind=ExtensionKind.REPAIR_RULE,
            id=extension_id,
            version="1.0.0",
            enabled=True,
            entrypoint="fixture:Rule",
            description="deterministic repair fixture",
            capabilities=["repair"],
            compatibility={"agent_api": ">=2.0,<3", "comsol": ["6.x"]},
            permissions={
                "filesystem": "write",
                "shell": "none",
                "comsol": "model_write",
                "network": "none",
            },
            priority=priority,
            quality=1.0,
            metadata={"provenance": "tests/test_v2_repair.py"},
            repair_contract=self.repair_contract.model_dump(mode="json"),
        )

    async def activate(self) -> None:
        self.active = True

    async def deactivate(self) -> None:
        self.active = False

    async def health(self) -> HealthReport:
        return HealthReport(
            extension_id=self.manifest.id,
            status=HealthStatus.HEALTHY if self.active else HealthStatus.DISABLED,
        )

    def supports(self, context: Any) -> bool:
        return True

    def matches(self, trigger: Observation, context: Any) -> bool:
        return True

    async def propose(self, trigger: Observation) -> dict[str, Any]:
        if self.fail_proposal:
            raise RuntimeError("isolated rule failure")
        return RepairCandidate(
            kind=RepairKind.DETERMINISTIC_RULE,
            observation_id=trigger.observation_id,
            diagnosis_fingerprint=self.diagnosis.fingerprint,
            scope=self.candidate_scope,
            verifier="fixture.verify",
            payload={"operation": "local-only"},
            provenance=f"extension:{self.manifest.id}",
            required_gates=frozenset({"api"}),
        ).model_dump(mode="json")

    async def verify(self, trigger: Observation) -> bool:
        return trigger.success


class SolverRule(Rule):
    def __init__(self, diagnosis: Diagnosis) -> None:
        super().__init__(diagnosis, extension_id="fixture.solver")
        self.manifest = self.manifest.model_copy(
            update={"kind": ExtensionKind.SOLVER_STRATEGY}
        )
        del self.repair_contract
        self.solver_contract = SolverStrategyContract(
            solver_scope=AffectedScope(kind="solver", targets=("study.sol1",)),
            continuation={"load_steps": [0.25, 0.5, 1.0]},
            initialization={"contact": "ramped"},
            max_solves=3,
            core_hour_budget=1.0,
            success_criteria=("target step converged",),
            rollback_checkpoint="checkpoint-B",
            compatibility=VersionCompatibility(agent_api=">=2.0,<3", comsol=("6.x",)),
            provenance="tests/test_v2_repair.py",
        )
        self.manifest = self.manifest.model_copy(
            update={
                "repair_contract": None,
                "solver_strategy_contract": self.solver_contract.model_dump(mode="json"),
            }
        )
        self.candidate_scope = AffectedScope(kind="solver", targets=("study.sol1",))

    async def propose(self, trigger: Observation) -> dict[str, Any]:
        candidate = RepairCandidate(
            kind=RepairKind.SOLVER_STRATEGY,
            observation_id=trigger.observation_id,
            diagnosis_fingerprint=self.diagnosis.fingerprint,
            scope=self.candidate_scope,
            verifier="fixture.solve.verify",
            payload={"continuation": [0.25, 0.5, 1.0]},
            provenance="extension:fixture.solver",
            required_gates=frozenset({"solve"}),
        )
        return candidate.model_dump(mode="json")


def registry(tmp_path: Path) -> ExtensionRegistry:
    return ExtensionRegistry(
        ExtensionLoader(
            compatibility=CompatibilityPolicy(agent_version="2.0.0", comsol_version="6.2"),
            permissions=PermissionPolicy(
                PermissionSet(
                    filesystem="write",
                    shell="none",
                    comsol="solve",
                    network="none",
                )
            ),
            trusted_manifest_roots=(tmp_path,),
            trusted_code_roots=(Path(__file__).parents[1],),
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "scope"),
    [
        (ErrorCode.UNKNOWN_FEATURE, AffectedScope(kind="node", targets=("component.sel1",))),
        (ErrorCode.INVALID_PROPERTY, AffectedScope(kind="property", targets=("plot.looplevel",))),
        (ErrorCode.INVALID_OVERLOAD, AffectedScope(kind="type_adapter", targets=("java.value",))),
        (ErrorCode.ENTITY_DIMENSION, AffectedScope(kind="selection", targets=("sel.boundary",))),
    ],
)
async def test_deterministic_scoped_api_repairs_pass_declared_verifier(
    tmp_path: Path, code: ErrorCode, scope: AffectedScope
) -> None:
    trigger = observation(error_class="runtime_failure")
    diagnosis = runtime_diagnosis(code, RuntimeErrorClass.API_CODE, trigger, scope=scope)
    rule = Rule(diagnosis)
    extensions = registry(tmp_path)
    await extensions.register(rule)
    executor = FakeExecutor([observation(success=True, data={"gates": {"api": True}})])
    async with extensions.snapshot() as snapshot:
        result = await RepairOrchestrator(
            diagnostics=DiagnosticService(), snapshot=snapshot, executor=executor
        ).repair(trigger, diagnosis)
    assert result.status == RepairStatus.COMPLETED
    assert executor.applied[0].scope == scope
    assert executor.committed


@pytest.mark.asyncio
async def test_empty_selection_out_of_scope_candidate_stops_safely(tmp_path: Path) -> None:
    trigger = observation(error_class="runtime_failure")
    diagnosis = runtime_diagnosis(
        ErrorCode.EMPTY_SELECTION,
        RuntimeErrorClass.API_CODE,
        trigger,
        scope=AffectedScope(kind="selection", targets=("component.safe",)),
    )
    rule = Rule(
        diagnosis,
        candidate_scope=AffectedScope(kind="selection", targets=("component.other",)),
    )
    extensions = registry(tmp_path)
    await extensions.register(rule)
    executor = FakeExecutor()
    async with extensions.snapshot() as snapshot:
        result = await RepairOrchestrator(
            diagnostics=DiagnosticService(), snapshot=snapshot, executor=executor
        ).repair(trigger, diagnosis)
    assert result.status == RepairStatus.UNSAFE
    assert not executor.applied


@pytest.mark.asyncio
async def test_pytest_failure_uses_m3_exact_patch_checkpoint_and_verifier(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    trigger = observation(error_class="pytest_failure", stage="test")
    diagnosis = DiagnosticService().from_observation(
        trigger, affected_scope=AffectedScope(kind="files", targets=("sample.py",))
    )
    patch = PatchSet(
        description="fix pytest failure",
        replacements=[TextReplacement(path="sample.py", old="1", new="2")],
        evidence=[trigger.observation_id],
    )

    async def provider(diagnosis: Diagnosis, trigger: Observation) -> RepairCandidate:
        return RepairCandidate(
            kind=RepairKind.LLM_PATCH,
            observation_id=trigger.observation_id,
            diagnosis_fingerprint=diagnosis.fingerprint,
            scope=diagnosis.affected_scope,
            verifier="pytest",
            payload={"patch": patch.model_dump(mode="json")},
            provenance="bounded-llm-fixture",
        )

    async def verify(candidate: RepairCandidate, trigger: Observation) -> Observation:
        assert source.read_text(encoding="utf-8") == "value = 2\n"
        return observation(success=True, stage="test")

    extensions = registry(tmp_path)
    async with extensions.snapshot() as snapshot:
        result = await RepairOrchestrator(
            diagnostics=DiagnosticService(),
            snapshot=snapshot,
            executor=WorkspaceRepairExecutor(Workspace(tmp_path), verify),
            llm_patch=provider,
        ).repair(trigger, diagnosis)
    assert result.status == RepairStatus.COMPLETED
    assert source.read_text(encoding="utf-8") == "value = 2\n"


@pytest.mark.asyncio
async def test_non_convergence_enters_only_solver_strategy(tmp_path: Path) -> None:
    trigger = observation(error_class="runtime_failure", stage="solve")
    diagnosis = runtime_diagnosis(
        ErrorCode.NON_CONVERGENCE,
        RuntimeErrorClass.SOLVE_CONVERGENCE,
        trigger,
        stage=RuntimeStage.SOLVE,
        scope=AffectedScope(kind="solver", targets=("study.sol1",)),
    )
    extensions = registry(tmp_path)
    await extensions.register(SolverRule(diagnosis))
    executor = FakeExecutor([observation(success=True, data={"gates": {"solve": True}})])
    local_called = False

    async def local(*_: Any) -> None:
        nonlocal local_called
        local_called = True
        return None

    async with extensions.snapshot() as snapshot:
        result = await RepairOrchestrator(
            diagnostics=DiagnosticService(),
            snapshot=snapshot,
            executor=executor,
            local_pattern=local,
        ).repair(trigger, diagnosis)
    assert result.status == RepairStatus.COMPLETED
    assert executor.applied[0].kind == RepairKind.SOLVER_STRATEGY
    assert not local_called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "error_class", "confirmed"),
    [
        (ErrorCode.RUNTIME_UNAVAILABLE, RuntimeErrorClass.RESOURCE, None),
        (ErrorCode.CANCELLED, RuntimeErrorClass.CANCELLED, True),
        (ErrorCode.TIMEOUT, RuntimeErrorClass.TIMEOUT, False),
    ],
)
async def test_environment_cancel_and_unconfirmed_timeout_never_modify_model(
    tmp_path: Path,
    code: ErrorCode,
    error_class: RuntimeErrorClass,
    confirmed: bool | None,
) -> None:
    trigger = observation(error_class="runtime_failure")
    diagnosis = runtime_diagnosis(
        code, error_class, trigger, termination_confirmed=confirmed
    )
    executor = FakeExecutor()
    extensions = registry(tmp_path)
    async with extensions.snapshot() as snapshot:
        result = await RepairOrchestrator(
            diagnostics=DiagnosticService(), snapshot=snapshot, executor=executor
        ).repair(trigger, diagnosis)
    assert result.status == RepairStatus.USER_DECISION_REQUIRED
    assert not executor.applied


@pytest.mark.asyncio
async def test_physics_audit_cannot_be_repaired_by_relaxing_threshold(tmp_path: Path) -> None:
    trigger = observation(error_class="runtime_failure", stage="results_audit")
    diagnosis = runtime_diagnosis(
        ErrorCode.PHYSICS_AUDIT_FAILURE,
        RuntimeErrorClass.PHYSICS_AUDIT,
        trigger,
        stage=RuntimeStage.RESULTS_AUDIT,
        scope=AffectedScope(kind="physics_model"),
    )

    async def unsafe(diagnosis: Diagnosis, trigger: Observation) -> RepairCandidate:
        return RepairCandidate(
            kind=RepairKind.LLM_PATCH,
            observation_id=trigger.observation_id,
            diagnosis_fingerprint=diagnosis.fingerprint,
            scope=AffectedScope(kind="audit_threshold"),
            verifier="audit",
            provenance="unsafe-fixture",
        )

    executor = FakeExecutor()
    extensions = registry(tmp_path)
    async with extensions.snapshot() as snapshot:
        result = await RepairOrchestrator(
            diagnostics=DiagnosticService(),
            snapshot=snapshot,
            executor=executor,
            llm_patch=unsafe,
        ).repair(trigger, diagnosis)
    assert result.status == RepairStatus.UNSAFE
    assert not executor.applied


@pytest.mark.asyncio
async def test_same_failure_fingerprint_stops_and_rolls_back(tmp_path: Path) -> None:
    trigger = observation(error_class="pytest_failure", stage="test", data={"node": "x"})
    diagnosis = DiagnosticService().from_observation(trigger)
    repeated = observation(error_class="pytest_failure", stage="test", data={"node": "x"})

    async def provider(diagnosis: Diagnosis, trigger: Observation) -> RepairCandidate:
        return RepairCandidate(
            kind=RepairKind.LOCAL_PATTERN,
            observation_id=trigger.observation_id,
            diagnosis_fingerprint=diagnosis.fingerprint,
            scope=diagnosis.affected_scope,
            verifier="pytest",
            provenance="local-pattern",
        )

    executor = FakeExecutor([repeated])
    extensions = registry(tmp_path)
    async with extensions.snapshot() as snapshot:
        result = await RepairOrchestrator(
            diagnostics=DiagnosticService(),
            snapshot=snapshot,
            executor=executor,
            local_pattern=provider,
        ).repair(trigger, diagnosis)
    assert result.status == RepairStatus.REPEATED_FAILURE
    assert executor.rolled_back
    runtime_failure = RuntimeFailure(
        error_class=RuntimeErrorClass.API_CODE,
        code=ErrorCode.UNKNOWN_FEATURE,
        message="structured runtime failure",
        stage=RuntimeStage.BUILD,
        operation=RuntimeOperation.EXECUTE_REGISTERED,
        retryable=True,
        causes=[CauseFrame(exception_type="FixtureError", message="missing fixture")],
    )
    first_runtime = DiagnosticService().from_runtime(
        runtime_failure,
        observation=trigger,
        affected_scope=AffectedScope(kind="node"),
    )
    repeated_runtime = DiagnosticService().from_observation(
        observation(
            error_class="api_code_error",
            stage="comsol_runtime",
            data={"failure": runtime_failure.model_dump(mode="json")},
        ),
        affected_scope=AffectedScope(kind="node"),
    )
    assert repeated_runtime.fingerprint == first_runtime.fingerprint


@pytest.mark.asyncio
async def test_cancellation_after_checkpoint_rolls_back_and_preserves_truth(
    tmp_path: Path,
) -> None:
    trigger = observation(error_class="pytest_failure", stage="test")
    diagnosis = DiagnosticService().from_observation(trigger)

    async def provider(diagnosis: Diagnosis, trigger: Observation) -> RepairCandidate:
        return RepairCandidate(
            kind=RepairKind.LOCAL_PATTERN,
            observation_id=trigger.observation_id,
            diagnosis_fingerprint=diagnosis.fingerprint,
            scope=diagnosis.affected_scope,
            verifier="pytest",
            provenance="cancel-fixture",
        )

    class CancellingExecutor(FakeExecutor):
        async def apply(self, candidate: RepairCandidate) -> None:
            raise RunCancelledError("operator cancellation")

    executor = CancellingExecutor()
    extensions = registry(tmp_path)
    async with extensions.snapshot() as snapshot:
        result = await RepairOrchestrator(
            diagnostics=DiagnosticService(),
            snapshot=snapshot,
            executor=executor,
            local_pattern=provider,
        ).repair(trigger, diagnosis)
    assert result.status == RepairStatus.CANCELLED
    assert result.attempts[0].rolled_back
    assert executor.rolled_back


@pytest.mark.asyncio
async def test_budget_exhaustion_rolls_back_each_failed_candidate(tmp_path: Path) -> None:
    trigger = observation(error_class="pytest_failure", stage="test")
    diagnosis = DiagnosticService().from_observation(trigger)
    different = observation(error_class="ruff_failure", stage="test")

    def provider(kind: RepairKind) -> Callable:
        async def propose(diagnosis: Diagnosis, trigger: Observation) -> RepairCandidate:
            return RepairCandidate(
                kind=kind,
                observation_id=trigger.observation_id,
                diagnosis_fingerprint=diagnosis.fingerprint,
                scope=diagnosis.affected_scope,
                verifier="verify",
                provenance=kind,
                repair_case_id="mem_case" if kind == RepairKind.REPAIR_CASE else None,
            )

        return propose

    executor = FakeExecutor([different, different, different])
    extensions = registry(tmp_path)
    async with extensions.snapshot() as snapshot:
        result = await RepairOrchestrator(
            diagnostics=DiagnosticService(),
            snapshot=snapshot,
            executor=executor,
            local_pattern=provider(RepairKind.LOCAL_PATTERN),
            repair_case=provider(RepairKind.REPAIR_CASE),
            llm_patch=provider(RepairKind.LLM_PATCH),
        ).repair(trigger, diagnosis)
    assert result.status == RepairStatus.BUDGET_EXHAUSTED
    assert len(executor.rolled_back) == 3


@pytest.mark.asyncio
async def test_rule_disable_delete_conflict_and_handler_failure_isolation(
    tmp_path: Path,
) -> None:
    trigger = observation(error_class="runtime_failure")
    diagnosis = runtime_diagnosis(
        ErrorCode.UNKNOWN_FEATURE, RuntimeErrorClass.API_CODE, trigger
    )
    extensions = registry(tmp_path)
    broken = Rule(diagnosis, extension_id="fixture.broken", priority=110, fail_proposal=True)
    healthy = Rule(diagnosis, extension_id="fixture.healthy", priority=100)
    await extensions.register(broken)
    await extensions.register(healthy)
    executor = FakeExecutor([observation(success=True, data={"gates": {"api": True}})])
    async with extensions.snapshot() as snapshot:
        result = await RepairOrchestrator(
            diagnostics=DiagnosticService(), snapshot=snapshot, executor=executor
        ).repair(trigger, diagnosis)
    assert result.status == RepairStatus.COMPLETED
    assert any(item.event == "candidate_error" for item in result.trace)

    await extensions.disable("fixture.healthy")
    extensions.unregister("fixture.healthy")
    async with extensions.snapshot() as snapshot:
        assert not snapshot.candidates(ExtensionKind.REPAIR_RULE, "repair") or all(
            item.manifest.id != "fixture.healthy"
            for item in snapshot.candidates(ExtensionKind.REPAIR_RULE, "repair")
        )

    conflicting = registry(tmp_path)
    await conflicting.register(Rule(diagnosis, extension_id="fixture.a", priority=100))
    await conflicting.register(Rule(diagnosis, extension_id="fixture.b", priority=100))
    async with conflicting.snapshot() as snapshot:
        result = await RepairOrchestrator(
            diagnostics=DiagnosticService(), snapshot=snapshot, executor=FakeExecutor()
        ).repair(trigger, diagnosis)
    assert result.status == RepairStatus.CONFLICT


@pytest.mark.asyncio
async def test_repair_case_requires_exact_signature_versions_topology_and_governance(
    tmp_path: Path,
) -> None:
    trigger = observation(error_class="runtime_failure")
    diagnosis = runtime_diagnosis(
        ErrorCode.UNKNOWN_FEATURE, RuntimeErrorClass.API_CODE, trigger
    )
    patch_uri = "artifact://repair-compatible/patch.json"
    manifest_uri = "artifact://repair-compatible/manifest.json"
    repair = MemoryRecord(
        id="repair-compatible",
        layer=MemoryLayer.EPISODIC,
        type=MemoryType.REPAIR_CASE,
        summary="strict unknown-feature repair",
        content_ref=manifest_uri,
        structured=RepairCase(
            error_signature={
                "class": "UNKNOWN_FEATURE",
                "exception": "FixtureError",
                "feature_pattern": "fixture.*",
                "stage": diagnosis.stage,
            },
            root_cause="fixture node referenced before creation",
            failed_code_hash="a" * 64,
            patch_ref=ArtifactRef(uri=patch_uri, sha256="b" * 64),
            repair_rule_id="fixture.rule",
            verification=RepairVerification(
                static=True,
                runtime=True,
                verifier=SourceRef(kind="test", identifier="repair-runtime"),
            ),
            applicability={
                "scope": diagnosis.affected_scope.model_dump(mode="json")
            },
        ),
        provenance=MemoryProvenance(
            run_id="source-run",
            git_commit="c" * 40,
            code_hash="d" * 64,
            comsol_version="6.2",
            agent_version="2.0.0",
            agent_schema="1.0",
            contract_version="1.0",
            producer=SourceRef(kind="test", identifier="m6"),
        ),
        compatibility=MemoryCompatibility(
            domain="fixture",
            topology_signature="topology-a",
            comsol=">=6.2,<7",
            agent_api=">=2,<3",
            scopes=frozenset({"project"}),
        ),
    )
    repository = MemoryRepository()
    governance = MemoryGovernance(repository)
    governance.ingest(repair)
    governance.nominate(repair.id)
    governance.promote_repair_case(repair.id)
    evaluator = RetrievalEvaluator(repository)
    retriever = HybridRetriever(
        repository,
        reference_validator=ReferenceCatalog(
            {manifest_uri: None, patch_uri: "b" * 64}
        ),
    )
    compatibility = QueryCompatibility(
        comsol_version="6.2",
        agent_version="2.0.0",
        scopes=frozenset({"project"}),
    )
    incompatible = GovernedRepairCaseSource(
        retriever=retriever,
        evaluator=evaluator,
        domain="fixture",
        topology_signature="topology-b",
        compatibility=compatibility,
        patch_resolver=lambda uri: {"patch_ref": uri},
    )
    assert await incompatible(diagnosis, trigger) is None

    compatible = GovernedRepairCaseSource(
        retriever=retriever,
        evaluator=evaluator,
        domain="fixture",
        topology_signature="topology-a",
        compatibility=compatibility,
        patch_resolver=lambda uri: {"patch_ref": uri},
    )
    extensions = registry(tmp_path)
    async with extensions.snapshot() as snapshot:
        result = await RepairOrchestrator(
            diagnostics=DiagnosticService(),
            snapshot=snapshot,
            executor=FakeExecutor(),
            repair_case=compatible,
        ).repair(trigger, diagnosis)
    assert result.status == RepairStatus.COMPLETED
    assert result.attempts[0].candidate.repair_case_id == repair.id
    assert evaluator.metrics().repair_success_rate == 1.0


@pytest.mark.asyncio
async def test_trace_rebuilds_diagnosis_candidate_repair_verify_complete(
    tmp_path: Path,
) -> None:
    trigger = observation(error_class="runtime_failure")
    diagnosis = runtime_diagnosis(
        ErrorCode.INVALID_PROPERTY, RuntimeErrorClass.API_CODE, trigger
    )
    extensions = registry(tmp_path)
    await extensions.register(Rule(diagnosis))
    async with extensions.snapshot() as snapshot:
        result = await RepairOrchestrator(
            diagnostics=DiagnosticService(),
            snapshot=snapshot,
            executor=FakeExecutor(
                [observation(success=True, data={"gates": {"api": True}})]
            ),
        ).repair(trigger, diagnosis)
    events = [event.event for event in result.trace]
    assert events == ["diagnosis", "candidate", "checkpoint", "repair", "verify", "complete"]
    assert [event.sequence for event in result.trace] == list(range(1, 7))
    assert result.user_message
    goal = GoalSpec(objective="repair fixture")
    manifest = RunManifest(
        trace_id=goal.trace_id,
        goal=goal,
        plan=Plan(
            goal_trace_id=goal.trace_id,
            steps=[PlanStep(description="repair", action=Action(tool="repair"))],
        ),
    )
    RepairOrchestrator.record_manifest(manifest, result)
    assert manifest.repairs[0].diagnosis_id == diagnosis.diagnosis_id
    assert manifest.repairs[0].outcome == "success"
    assert manifest.checkpoints
    assert [item["event"] for item in manifest.trace_events] == events
