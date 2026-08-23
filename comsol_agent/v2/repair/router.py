"""Adapter that routes failed tool Observations through bounded M6 diagnosis/repair."""

from __future__ import annotations

from typing import Any

from comsol_agent.v2.contracts import Observation
from comsol_agent.v2.extensions import ExtensionSnapshot
from comsol_agent.v2.kernel import CancellationToken

from .diagnosis import DiagnosticService
from .models import Diagnosis, RepairCandidate, RepairExecutionContext, RepairExecutionLimits
from .orchestrator import RepairOrchestrator


class _UnavailableRepairExecutor:
    """Fail closed if a host exposes a repair candidate without an executor."""

    async def create_checkpoint(
        self, diagnosis: Diagnosis, candidate: RepairCandidate
    ) -> str:
        raise RuntimeError("no controlled repair executor is configured")

    async def apply(
        self, candidate: RepairCandidate, limits: RepairExecutionLimits
    ) -> None:
        raise RuntimeError("no controlled repair executor is configured")

    async def verify(
        self, candidate: RepairCandidate, trigger: Observation
    ) -> Observation:
        raise RuntimeError("no controlled repair executor is configured")

    async def rollback(self, checkpoint: str) -> None:
        raise RuntimeError("no controlled repair executor is configured")

    async def commit(self, checkpoint: str) -> None:
        raise RuntimeError("no controlled repair executor is configured")


class ObservationRepairRouter:
    """Diagnose every failed Observation and apply only registered bounded repairs."""

    def __init__(
        self,
        snapshot: ExtensionSnapshot,
        *,
        execution_context: RepairExecutionContext | None = None,
        executor: Any | None = None,
    ) -> None:
        self.diagnostics = DiagnosticService()
        self.orchestrator = RepairOrchestrator(
            diagnostics=self.diagnostics,
            snapshot=snapshot,
            executor=executor or _UnavailableRepairExecutor(),
            max_attempts_per_stage=3,
            max_llm_attempts=0,
            execution_context=execution_context,
        )

    async def route(
        self, observation: Observation, cancellation: CancellationToken
    ) -> dict[str, Any]:
        diagnosis = self.diagnostics.from_observation(observation)
        result = await self.orchestrator.repair(
            observation, diagnosis, cancellation=cancellation
        )
        return {
            "diagnosis": diagnosis.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "bounded": True,
            "raw_action_retry": False,
        }
