"""Domain-neutral V2 Action—Observation agent loop."""

from __future__ import annotations

from time import monotonic
from typing import Protocol

from comsol_agent.v2.contracts import (
    Action,
    ActionRecord,
    GoalSpec,
    GoalStatus,
    Observation,
    Plan,
    PlanStatus,
    RepairRecord,
    RunManifest,
    RunStatus,
    SourceRef,
    StateTransitionRecord,
    StepStatus,
)
from comsol_agent.v2.contracts.models import utc_now
from comsol_agent.v2.kernel.budget import BudgetExceededError, RunBudget
from comsol_agent.v2.kernel.cancellation import CancellationToken, RunCancelledError
from comsol_agent.v2.kernel.context import ContextManager, InMemoryContextManager
from comsol_agent.v2.kernel.events import EventBus, EventType, TraceRecorder
from comsol_agent.v2.kernel.state import RunStage, RunStateMachine


class ToolExecutor(Protocol):
    """Controlled execution boundary; concrete registries arrive in M2."""

    async def execute(
        self,
        action: Action,
        cancellation: CancellationToken,
    ) -> Observation: ...


class AgentKernel:
    """Orchestrate plans without importing any domain or tool implementation."""

    def __init__(
        self,
        executor: ToolExecutor,
        *,
        context_manager: ContextManager | None = None,
        budget: RunBudget | None = None,
        cancellation: CancellationToken | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.executor = executor
        self.context_manager = context_manager or InMemoryContextManager()
        self.budget = budget or RunBudget()
        self.cancellation = cancellation or CancellationToken()
        self._event_bus = event_bus

    async def run(self, goal: GoalSpec, plan: Plan) -> RunManifest:
        if plan.goal_trace_id != goal.trace_id:
            raise ValueError("Plan goal_trace_id must match GoalSpec trace_id")
        if goal.status != GoalStatus.ACTIVE:
            raise ValueError("AgentKernel requires an active GoalSpec")

        state = RunStateMachine()
        event_bus = self._event_bus or EventBus(goal.trace_id)
        if event_bus.trace_id != goal.trace_id:
            raise ValueError("EventBus trace_id must match GoalSpec trace_id")
        trace = TraceRecorder(goal.trace_id)
        unsubscribe_trace = event_bus.subscribe(trace.record)
        manifest = RunManifest(trace_id=goal.trace_id, goal=goal, plan=plan)
        observations: list[Observation] = []

        try:
            await event_bus.emit(EventType.RUN_STARTED, state.stage, {"run_id": manifest.run_id})
            await self._advance(state, manifest, event_bus, RunStage.RETRIEVE, "goal accepted")
            self.cancellation.raise_if_cancelled()
            await self.context_manager.build(
                goal,
                plan,
                tuple(observations),
                self.budget.snapshot(),
            )
            await self._advance(state, manifest, event_bus, RunStage.PLAN, "context assembled")
            await self._advance(state, manifest, event_bus, RunStage.PREPARE, "plan selected")
            plan.status = PlanStatus.IN_PROGRESS

            for index, step in enumerate(plan.steps):
                self.cancellation.raise_if_cancelled()
                step.status = StepStatus.IN_PROGRESS
                await self._advance(
                    state,
                    manifest,
                    event_bus,
                    RunStage.STATIC_VALIDATE,
                    f"prepare step {step.step_id}",
                )
                attempt = 0

                while True:
                    self.cancellation.raise_if_cancelled()
                    self.budget.consume_action()
                    attempt += 1
                    await self._advance(
                        state,
                        manifest,
                        event_bus,
                        RunStage.EXECUTE,
                        f"execute step {step.step_id} attempt {attempt}",
                    )
                    await event_bus.emit(
                        EventType.ACTION_STARTED,
                        state.stage,
                        {
                            "action_id": step.action.action_id,
                            "tool": step.action.tool,
                            "attempt": attempt,
                        },
                    )
                    observation = await self._execute_safely(step.action)
                    observations.append(observation)
                    manifest.action_records.append(
                        ActionRecord(action=step.action, observation=observation, attempt=attempt)
                    )
                    manifest.artifacts.extend(observation.artifacts)
                    manifest.audits.extend(observation.audits)
                    if observation.checkpoint:
                        manifest.checkpoints.append(observation.checkpoint)
                    await event_bus.emit(
                        EventType.OBSERVATION_RECORDED,
                        state.stage,
                        {
                            "observation_id": observation.observation_id,
                            "action_id": observation.action_id,
                            "success": observation.success,
                            "error_class": observation.error_class,
                            "retryable": observation.retryable,
                        },
                    )
                    await self.context_manager.build(
                        goal,
                        plan,
                        tuple(observations),
                        self.budget.snapshot(),
                    )

                    if observation.success:
                        step.status = StepStatus.COMPLETE
                        await self._advance(
                            state,
                            manifest,
                            event_bus,
                            RunStage.VERIFY,
                            f"step {step.step_id} returned successful evidence",
                        )
                        break

                    if not observation.retryable:
                        step.status = StepStatus.FAILED
                        raise _RunFailureError(
                            f"non-repairable {observation.error_class} in step {step.step_id}"
                        )

                    await self._advance(
                        state,
                        manifest,
                        event_bus,
                        RunStage.REPAIR,
                        f"retryable {observation.error_class}",
                    )
                    self.budget.consume_repair()
                    manifest.repairs.append(
                        RepairRecord(
                            action_id=step.action.action_id,
                            error_class=observation.error_class or "unknown",
                            attempt=attempt,
                            verifier="repeat action and require successful Observation",
                        )
                    )
                    await event_bus.emit(
                        EventType.REPAIR_SCHEDULED,
                        state.stage,
                        {"action_id": step.action.action_id, "attempt": attempt},
                    )
                    await self._advance(
                        state,
                        manifest,
                        event_bus,
                        RunStage.STATIC_VALIDATE,
                        "bounded retry prepared",
                    )

                if index < len(plan.steps) - 1:
                    await self._advance(
                        state,
                        manifest,
                        event_bus,
                        RunStage.PREPARE,
                        "prepare next plan step",
                    )

            plan.status = PlanStatus.COMPLETE
            await self._advance(
                state,
                manifest,
                event_bus,
                RunStage.PROMOTE,
                "all plan steps verified",
            )
            await self._advance(
                state,
                manifest,
                event_bus,
                RunStage.COMPLETED,
                "acceptance evidence complete",
            )
            goal.status = GoalStatus.COMPLETE
            manifest.status = RunStatus.COMPLETED
            manifest.finished_at = utc_now()
            await event_bus.emit(EventType.RUN_COMPLETED, state.stage, {"run_id": manifest.run_id})
        except BudgetExceededError as exc:
            await event_bus.emit(
                EventType.BUDGET_EXHAUSTED,
                state.stage,
                {"budget": exc.budget, "limit": exc.limit},
            )
            await self._fail(state, manifest, event_bus, str(exc))
        except RunCancelledError as exc:
            await self._cancel(state, manifest, event_bus, str(exc))
        except _RunFailureError as exc:
            await self._fail(state, manifest, event_bus, str(exc))
        finally:
            manifest.trace_events = trace.as_dicts()
            unsubscribe_trace()

        return manifest

    async def _execute_safely(self, action: Action) -> Observation:
        started_at = monotonic()
        try:
            observation = await self.executor.execute(action, self.cancellation)
        except RunCancelledError:
            raise
        except Exception as exc:
            return Observation(
                action_id=action.action_id,
                success=False,
                status="exception",
                stage=RunStage.EXECUTE,
                error_class="tool_execution_error",
                exception_type=type(exc).__name__,
                retryable=False,
                duration_ms=(monotonic() - started_at) * 1000,
                source=SourceRef(kind="tool", identifier=action.tool, version="unknown"),
            )
        if observation.action_id != action.action_id:
            return Observation(
                action_id=action.action_id,
                success=False,
                status="invalid_observation",
                stage=RunStage.EXECUTE,
                error_class="contract_violation",
                exception_type="ObservationActionMismatch",
                retryable=False,
                duration_ms=(monotonic() - started_at) * 1000,
                source=SourceRef(kind="kernel", identifier="observation-validator"),
            )
        return observation

    async def _advance(
        self,
        state: RunStateMachine,
        manifest: RunManifest,
        event_bus: EventBus,
        target: RunStage,
        reason: str,
    ) -> None:
        self.cancellation.raise_if_cancelled()
        self.budget.check_time()
        previous, current = state.transition(target)
        manifest.current_stage = current
        manifest.transitions.append(
            StateTransitionRecord(from_stage=previous, to_stage=current, reason=reason)
        )
        await event_bus.emit(
            EventType.STAGE_CHANGED,
            current,
            {"from_stage": previous, "to_stage": current, "reason": reason},
        )

    async def _fail(
        self,
        state: RunStateMachine,
        manifest: RunManifest,
        event_bus: EventBus,
        reason: str,
    ) -> None:
        if not state.terminal:
            previous, current = state.transition(RunStage.FAILED)
            manifest.transitions.append(
                StateTransitionRecord(from_stage=previous, to_stage=current, reason=reason)
            )
            await event_bus.emit(
                EventType.STAGE_CHANGED,
                current,
                {"from_stage": previous, "to_stage": current, "reason": reason},
            )
        manifest.current_stage = RunStage.FAILED
        manifest.status = RunStatus.FAILED
        self._fail_in_progress_steps(manifest.plan)
        manifest.plan.status = PlanStatus.FAILED
        manifest.goal.status = GoalStatus.BLOCKED
        manifest.failure_reason = reason
        manifest.finished_at = utc_now()
        await event_bus.emit(EventType.RUN_FAILED, RunStage.FAILED, {"reason": reason})

    async def _cancel(
        self,
        state: RunStateMachine,
        manifest: RunManifest,
        event_bus: EventBus,
        reason: str,
    ) -> None:
        if not state.terminal:
            previous, current = state.transition(RunStage.CANCELLED)
            manifest.transitions.append(
                StateTransitionRecord(from_stage=previous, to_stage=current, reason=reason)
            )
            await event_bus.emit(
                EventType.STAGE_CHANGED,
                current,
                {"from_stage": previous, "to_stage": current, "reason": reason},
            )
        manifest.current_stage = RunStage.CANCELLED
        manifest.status = RunStatus.CANCELLED
        self._fail_in_progress_steps(manifest.plan)
        manifest.plan.status = PlanStatus.FAILED
        manifest.goal.status = GoalStatus.BLOCKED
        manifest.failure_reason = reason
        manifest.finished_at = utc_now()
        await event_bus.emit(EventType.RUN_CANCELLED, RunStage.CANCELLED, {"reason": reason})

    @staticmethod
    def _fail_in_progress_steps(plan: Plan) -> None:
        """Close active steps when their enclosing run reaches a terminal failure state."""
        for step in plan.steps:
            if step.status == StepStatus.IN_PROGRESS:
                step.status = StepStatus.FAILED


class _RunFailureError(RuntimeError):
    pass
