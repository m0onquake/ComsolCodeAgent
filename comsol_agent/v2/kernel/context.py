"""Provenance-preserving context composition interface."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import Field

from comsol_agent.v2.contracts import GoalSpec, Observation, Plan, SourceRef
from comsol_agent.v2.contracts.models import ContractModel
from comsol_agent.v2.kernel.budget import BudgetSnapshot


class ContextKind(StrEnum):
    GOAL = "goal"
    PLAN = "plan"
    USER = "user"
    WORKSPACE = "workspace"
    SKILL = "skill"
    RETRIEVAL = "retrieval"
    OBSERVATION = "observation"
    CHECKPOINT = "checkpoint"
    POLICY = "policy"


class ContextEntry(ContractModel):
    kind: ContextKind
    content: Any
    source: SourceRef
    priority: int = 0


class ContextSnapshot(ContractModel):
    entries: list[ContextEntry] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    compressed: bool = False


class ContextManager(Protocol):
    """Boundary for retrieval, composition, provenance, and compression."""

    async def build(
        self,
        goal: GoalSpec,
        plan: Plan,
        observations: tuple[Observation, ...],
        budget: BudgetSnapshot,
    ) -> ContextSnapshot: ...

    async def compress(self, snapshot: ContextSnapshot) -> ContextSnapshot: ...


class InMemoryContextManager:
    """Minimal M1 implementation retaining goal, plan, and recent facts."""

    def __init__(self, max_observations: int = 20) -> None:
        if max_observations < 0:
            raise ValueError("max_observations cannot be negative")
        self.max_observations = max_observations

    async def build(
        self,
        goal: GoalSpec,
        plan: Plan,
        observations: tuple[Observation, ...],
        budget: BudgetSnapshot,
    ) -> ContextSnapshot:
        entries = [
            ContextEntry(
                kind=ContextKind.GOAL,
                content=goal.model_dump(mode="json"),
                source=SourceRef(kind="contract", identifier="goal", version=goal.schema_version),
                priority=100,
            ),
            ContextEntry(
                kind=ContextKind.PLAN,
                content=plan.model_dump(mode="json"),
                source=SourceRef(kind="contract", identifier="plan", version=plan.schema_version),
                priority=90,
            ),
        ]
        recent = observations[-self.max_observations :] if self.max_observations else ()
        entries.extend(
            ContextEntry(
                kind=ContextKind.OBSERVATION,
                content=observation.model_dump(mode="json"),
                source=observation.source,
                priority=80,
            )
            for observation in recent
        )
        return ContextSnapshot(entries=entries, budget=_budget_dict(budget))

    async def compress(self, snapshot: ContextSnapshot) -> ContextSnapshot:
        # M1 has no lossy summarizer. Bound observations while retaining provenance.
        fixed = [entry for entry in snapshot.entries if entry.kind != ContextKind.OBSERVATION]
        observations = [
            entry for entry in snapshot.entries if entry.kind == ContextKind.OBSERVATION
        ]
        return ContextSnapshot(
            entries=[*fixed, *observations[-self.max_observations :]],
            budget=snapshot.budget,
            compressed=len(observations) > self.max_observations,
        )


def _budget_dict(snapshot: BudgetSnapshot) -> dict[str, Any]:
    return {
        "actions_used": snapshot.actions_used,
        "repairs_used": snapshot.repairs_used,
        "elapsed_seconds": snapshot.elapsed_seconds,
        "limits": {
            "max_actions": snapshot.limits.max_actions,
            "max_repairs": snapshot.limits.max_repairs,
            "max_elapsed_seconds": snapshot.limits.max_elapsed_seconds,
        },
    }
