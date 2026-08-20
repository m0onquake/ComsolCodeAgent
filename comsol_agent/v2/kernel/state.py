"""Explicit lifecycle state machine for V2 runs."""

from __future__ import annotations

from enum import StrEnum


class RunStage(StrEnum):
    INTAKE = "intake"
    RETRIEVE = "retrieve"
    PLAN = "plan"
    PREPARE = "prepare"
    STATIC_VALIDATE = "static_validate"
    EXECUTE = "execute"
    REPAIR = "repair"
    VERIFY = "verify"
    PROMOTE = "promote"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STAGES = frozenset({RunStage.COMPLETED, RunStage.FAILED, RunStage.CANCELLED})

_NORMAL_TRANSITIONS: dict[RunStage, frozenset[RunStage]] = {
    RunStage.INTAKE: frozenset({RunStage.RETRIEVE}),
    RunStage.RETRIEVE: frozenset({RunStage.PLAN}),
    RunStage.PLAN: frozenset({RunStage.PREPARE}),
    RunStage.PREPARE: frozenset({RunStage.STATIC_VALIDATE}),
    RunStage.STATIC_VALIDATE: frozenset({RunStage.EXECUTE, RunStage.REPAIR}),
    RunStage.EXECUTE: frozenset({RunStage.VERIFY, RunStage.REPAIR}),
    RunStage.REPAIR: frozenset({RunStage.STATIC_VALIDATE}),
    # Returning to prepare supports the next step in an ordered multi-action plan.
    RunStage.VERIFY: frozenset({RunStage.PREPARE, RunStage.PROMOTE, RunStage.REPAIR}),
    RunStage.PROMOTE: frozenset({RunStage.COMPLETED}),
    RunStage.COMPLETED: frozenset(),
    RunStage.FAILED: frozenset(),
    RunStage.CANCELLED: frozenset(),
}


class InvalidTransitionError(ValueError):
    """Raised when a caller attempts an invalid lifecycle transition."""


class RunStateMachine:
    """Small state machine with explicit, auditable transition rules."""

    def __init__(self) -> None:
        self._stage = RunStage.INTAKE

    @property
    def stage(self) -> RunStage:
        return self._stage

    @property
    def terminal(self) -> bool:
        return self._stage in TERMINAL_STAGES

    def can_transition(self, target: RunStage) -> bool:
        if self.terminal:
            return False
        if target in {RunStage.FAILED, RunStage.CANCELLED}:
            return True
        return target in _NORMAL_TRANSITIONS[self._stage]

    def transition(self, target: RunStage) -> tuple[RunStage, RunStage]:
        if not self.can_transition(target):
            raise InvalidTransitionError(f"Cannot transition from {self._stage} to {target}")
        previous = self._stage
        self._stage = target
        return previous, target
