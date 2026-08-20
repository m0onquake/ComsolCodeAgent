"""M1 acceptance tests for domain-neutral V2 contracts and Agent Kernel."""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import pytest
from pydantic import ValidationError

from comsol_agent.v2.contracts import (
    Action,
    GoalSpec,
    Observation,
    Plan,
    PlanStep,
    RunManifest,
    RunStatus,
    SourceRef,
)
from comsol_agent.v2.kernel import (
    AgentKernel,
    BudgetLimits,
    CancellationToken,
    EventBus,
    EventType,
    InvalidTransitionError,
    RunBudget,
    RunStage,
    RunStateMachine,
)


class FakeToolExecutor:
    """Scripted fake capability; contains no domain or COMSOL behavior."""

    def __init__(self, outcomes: dict[str, list[bool]]) -> None:
        self.outcomes = {name: list(values) for name, values in outcomes.items()}
        self.calls: defaultdict[str, int] = defaultdict(int)

    async def execute(
        self,
        action: Action,
        cancellation: CancellationToken,
    ) -> Observation:
        cancellation.raise_if_cancelled()
        call_index = self.calls[action.tool]
        self.calls[action.tool] += 1
        success = self.outcomes[action.tool][call_index]
        return Observation(
            action_id=action.action_id,
            success=success,
            status="ok" if success else "temporary_failure",
            stage="execute",
            data={"call": call_index + 1} if success else {},
            error_class=None if success else "fake_transient_error",
            retryable=not success,
            source=SourceRef(kind="fake_tool", identifier=action.tool, version="1.0"),
        )


class RaisingFakeToolExecutor:
    async def execute(
        self,
        action: Action,
        cancellation: CancellationToken,
    ) -> Observation:
        raise LookupError("fake executor failure")


class CancellingFakeToolExecutor:
    async def execute(
        self,
        action: Action,
        cancellation: CancellationToken,
    ) -> Observation:
        cancellation.cancel("cancelled during fake execution")
        cancellation.raise_if_cancelled()
        raise AssertionError("unreachable")


def make_goal_and_plan(tool: str = "fake.run") -> tuple[GoalSpec, Plan]:
    goal = GoalSpec(
        objective="Produce verified fake-tool evidence",
        constraints={"forbidden_domains": ["all domain-specific behavior"]},
        acceptance=["the fake action succeeds"],
    )
    plan = Plan(
        goal_trace_id=goal.trace_id,
        steps=[PlanStep(description="Run controlled fake action", action=Action(tool=tool))],
    )
    return goal, plan


def event_types(manifest: RunManifest) -> list[str]:
    return [event["event_type"] for event in manifest.trace_events]


class TestContracts:
    def test_contracts_emit_json_schema_and_round_trip_manifest(self):
        goal, plan = make_goal_and_plan()
        manifest = RunManifest(trace_id=goal.trace_id, goal=goal, plan=plan)

        schema = RunManifest.model_json_schema()
        restored = RunManifest.model_validate_json(manifest.model_dump_json())

        assert "action_records" in schema["properties"]
        assert restored == manifest

    def test_failed_observation_requires_structured_error_class(self):
        with pytest.raises(ValidationError, match="error_class"):
            Observation(
                action_id="action-1",
                success=False,
                status="failed",
                stage="execute",
                source=SourceRef(kind="fake_tool", identifier="fake.run"),
            )

    def test_manifest_rejects_mismatched_trace_identity(self):
        goal, plan = make_goal_and_plan()
        with pytest.raises(ValidationError, match="trace_id"):
            RunManifest(trace_id="different", goal=goal, plan=plan)

    def test_kernel_imports_no_domain_implementation(self):
        kernel_root = Path(__file__).parents[1] / "comsol_agent" / "v2" / "kernel"
        imported_modules: set[str] = set()
        for path in kernel_root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.add(node.module)

        forbidden_prefixes = (
            "comsol_agent.simulation",
            "comsol_agent.tools.comsol",
            "comsol_agent.v2.domains",
        )
        assert not any(
            module.startswith(forbidden_prefixes) for module in imported_modules
        )


class TestStateAndEvents:
    def test_state_machine_rejects_skipped_stage(self):
        state = RunStateMachine()

        with pytest.raises(InvalidTransitionError):
            state.transition(RunStage.EXECUTE)

    @pytest.mark.asyncio
    async def test_event_bus_isolates_broken_subscriber(self):
        bus = EventBus("trace-1")
        received = []

        def broken_subscriber(_event):
            raise RuntimeError("subscriber failed")

        bus.subscribe(broken_subscriber)
        bus.subscribe(received.append)

        await bus.emit(EventType.RUN_STARTED, RunStage.INTAKE)

        assert len(received) == 1
        assert bus.subscriber_errors == ["RuntimeError: subscriber failed"]


class TestAgentKernelAcceptance:
    @pytest.mark.asyncio
    async def test_success_path_completes_with_trace_and_manifest_evidence(self):
        goal, plan = make_goal_and_plan()
        executor = FakeToolExecutor({"fake.run": [True]})

        manifest = await AgentKernel(executor).run(goal, plan)

        assert manifest.status == RunStatus.COMPLETED
        assert manifest.current_stage == RunStage.COMPLETED
        assert len(manifest.action_records) == 1
        assert manifest.action_records[0].observation.success is True
        assert EventType.RUN_COMPLETED in event_types(manifest)
        assert [transition.to_stage for transition in manifest.transitions] == [
            RunStage.RETRIEVE,
            RunStage.PLAN,
            RunStage.PREPARE,
            RunStage.STATIC_VALIDATE,
            RunStage.EXECUTE,
            RunStage.VERIFY,
            RunStage.PROMOTE,
            RunStage.COMPLETED,
        ]

    @pytest.mark.asyncio
    async def test_retryable_failure_uses_bounded_repair_and_then_completes(self):
        goal, plan = make_goal_and_plan()
        executor = FakeToolExecutor({"fake.run": [False, True]})
        budget = RunBudget(BudgetLimits(max_actions=2, max_repairs=1))

        manifest = await AgentKernel(executor, budget=budget).run(goal, plan)

        assert manifest.status == RunStatus.COMPLETED
        assert [record.observation.success for record in manifest.action_records] == [False, True]
        assert len(manifest.repairs) == 1
        assert manifest.repairs[0].error_class == "fake_transient_error"
        assert RunStage.REPAIR in [transition.to_stage for transition in manifest.transitions]
        assert EventType.REPAIR_SCHEDULED in event_types(manifest)

    @pytest.mark.asyncio
    async def test_budget_exhaustion_stops_retryable_failure_with_diagnostic_trace(self):
        goal, plan = make_goal_and_plan()
        executor = FakeToolExecutor({"fake.run": [False]})
        budget = RunBudget(BudgetLimits(max_actions=1, max_repairs=0))

        manifest = await AgentKernel(executor, budget=budget).run(goal, plan)

        assert manifest.status == RunStatus.FAILED
        assert manifest.current_stage == RunStage.FAILED
        assert manifest.goal.status == "blocked"
        assert manifest.plan.status == "failed"
        assert manifest.plan.steps[0].status == "failed"
        assert manifest.failure_reason == "repair budget exhausted (limit=0)"
        assert len(manifest.action_records) == 1
        assert EventType.BUDGET_EXHAUSTED in event_types(manifest)
        assert EventType.RUN_FAILED in event_types(manifest)

    @pytest.mark.asyncio
    async def test_pre_cancelled_run_stops_without_calling_tool(self):
        goal, plan = make_goal_and_plan()
        executor = FakeToolExecutor({"fake.run": [True]})
        cancellation = CancellationToken()
        cancellation.cancel("user requested stop")

        manifest = await AgentKernel(executor, cancellation=cancellation).run(goal, plan)

        assert manifest.status == RunStatus.CANCELLED
        assert manifest.failure_reason == "user requested stop"
        assert executor.calls["fake.run"] == 0
        assert EventType.RUN_CANCELLED in event_types(manifest)

    @pytest.mark.asyncio
    async def test_cancellation_during_execution_fails_only_the_active_step(self):
        goal, plan = make_goal_and_plan()
        plan.steps.append(
            PlanStep(description="Unstarted fake action", action=Action(tool="fake.next"))
        )

        manifest = await AgentKernel(CancellingFakeToolExecutor()).run(goal, plan)

        assert manifest.status == RunStatus.CANCELLED
        assert manifest.plan.status == "failed"
        assert [step.status for step in manifest.plan.steps] == ["failed", "pending"]
        assert manifest.failure_reason == "cancelled during fake execution"

    @pytest.mark.asyncio
    async def test_tool_exception_becomes_structured_non_retryable_observation(self):
        goal, plan = make_goal_and_plan()

        manifest = await AgentKernel(RaisingFakeToolExecutor()).run(goal, plan)

        observation = manifest.action_records[0].observation
        assert manifest.status == RunStatus.FAILED
        assert observation.error_class == "tool_execution_error"
        assert observation.exception_type == "LookupError"
        assert observation.retryable is False
