"""Execution-grounded evaluation for retrieval and repair reuse."""

from __future__ import annotations

from pydantic import Field

from comsol_agent.v2.contracts.models import ContractModel

from .contracts import RetrievalOutcome
from .store import MemoryRepository


class RetrievalMetrics(ContractModel):
    queries: int = Field(ge=0)
    adoption_rate: float = Field(ge=0.0, le=1.0)
    first_execution_success_rate: float = Field(ge=0.0, le=1.0)
    audited_success_rate: float = Field(ge=0.0, le=1.0)
    repair_success_rate: float = Field(ge=0.0, le=1.0)
    wrong_topology_reuse_rate: float = Field(ge=0.0, le=1.0)
    invalidated_case_reuse_rate: float = Field(ge=0.0, le=1.0)
    average_latency_ms: float = Field(ge=0.0)
    average_context_tokens: float = Field(ge=0.0)


class RetrievalEvaluator:
    """Scores retrieval by what happened after adoption, not text similarity."""

    def __init__(self, repository: MemoryRepository | None = None) -> None:
        self._outcomes: list[RetrievalOutcome] = []
        self.repository = repository

    def record(self, outcome: RetrievalOutcome) -> None:
        self._outcomes.append(outcome.model_copy(deep=True))
        if self.repository is not None:
            self._update_adoption_quality(outcome)

    @property
    def outcomes(self) -> tuple[RetrievalOutcome, ...]:
        return tuple(item.model_copy(deep=True) for item in self._outcomes)

    def metrics(self) -> RetrievalMetrics:
        total = len(self._outcomes)
        adopted = [item for item in self._outcomes if item.adopted_ids]
        executed = [item for item in adopted if item.execution_attempted]
        audited = [item for item in executed if item.audit_passed is not None]
        repairs = [item for item in adopted if item.repair_attempted]
        return RetrievalMetrics(
            queries=total,
            adoption_rate=_ratio(len(adopted), total),
            first_execution_success_rate=_ratio(
                sum(item.execution_success is True for item in executed), len(executed)
            ),
            audited_success_rate=_ratio(
                sum(item.audit_passed is True for item in audited), len(audited)
            ),
            repair_success_rate=_ratio(
                sum(item.repair_success is True for item in repairs), len(repairs)
            ),
            wrong_topology_reuse_rate=_ratio(
                sum(item.wrong_topology_reused for item in adopted), len(adopted)
            ),
            invalidated_case_reuse_rate=_ratio(
                sum(item.invalidated_case_reused for item in adopted), len(adopted)
            ),
            average_latency_ms=_average(item.latency_ms for item in self._outcomes),
            average_context_tokens=_average(
                float(item.context_tokens) for item in self._outcomes
            ),
        )

    def _update_adoption_quality(self, outcome: RetrievalOutcome) -> None:
        successful = (
            outcome.repair_success
            if outcome.repair_attempted
            else (
                outcome.audit_passed
                if outcome.audit_passed is not None
                else outcome.execution_success
            )
        )
        for record_id in outcome.adopted_ids:
            record = self.repository.get(record_id)
            if record is None:
                continue
            quality = record.quality.model_copy(
                update={
                    "adoption_count": record.quality.adoption_count + 1,
                    "adoption_success_count": (
                        record.quality.adoption_success_count + int(successful is True)
                    ),
                }
            )
            self.repository.replace(record.model_copy(update={"quality": quality}, deep=True))


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _average(values) -> float:
    materialized = list(values)
    return sum(materialized) / len(materialized) if materialized else 0.0
