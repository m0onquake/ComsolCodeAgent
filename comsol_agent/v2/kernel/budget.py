"""Run budgets with deterministic accounting and elapsed-time enforcement."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    max_actions: int = 50
    max_repairs: int = 3
    max_elapsed_seconds: float = 3600.0

    def __post_init__(self) -> None:
        if self.max_actions < 0 or self.max_repairs < 0 or self.max_elapsed_seconds < 0:
            raise ValueError("Budget limits cannot be negative")


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    actions_used: int
    repairs_used: int
    elapsed_seconds: float
    limits: BudgetLimits


class BudgetExceededError(RuntimeError):
    """Raised before work that would exceed a configured budget."""

    def __init__(self, budget: str, limit: int | float):
        self.budget = budget
        self.limit = limit
        super().__init__(f"{budget} budget exhausted (limit={limit})")


class RunBudget:
    def __init__(
        self,
        limits: BudgetLimits | None = None,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.limits = limits or BudgetLimits()
        self._clock = clock
        self._started_at = clock()
        self._actions_used = 0
        self._repairs_used = 0

    def check_time(self) -> None:
        if self.elapsed_seconds >= self.limits.max_elapsed_seconds:
            raise BudgetExceededError("elapsed_time", self.limits.max_elapsed_seconds)

    def consume_action(self) -> None:
        self.check_time()
        if self._actions_used >= self.limits.max_actions:
            raise BudgetExceededError("action", self.limits.max_actions)
        self._actions_used += 1

    def consume_repair(self) -> None:
        self.check_time()
        if self._repairs_used >= self.limits.max_repairs:
            raise BudgetExceededError("repair", self.limits.max_repairs)
        self._repairs_used += 1

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self._clock() - self._started_at)

    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            actions_used=self._actions_used,
            repairs_used=self._repairs_used,
            elapsed_seconds=self.elapsed_seconds,
            limits=self.limits,
        )
