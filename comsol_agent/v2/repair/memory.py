"""Governed M4 RepairCase retrieval adapter for M6."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from comsol_agent.v2.contracts import Observation
from comsol_agent.v2.memory import (
    ErrorSignature,
    HybridRetriever,
    MemoryStatus,
    MemoryType,
    QueryCompatibility,
    RepairCase,
    RetrievalEvaluator,
    RetrievalOutcome,
    RetrievalQuery,
)

from .models import Diagnosis, RepairCandidate, RepairKind


class GovernedRepairCaseSource:
    """Return only strict, executable, exact-signature RepairCase candidates."""

    def __init__(
        self,
        *,
        retriever: HybridRetriever,
        evaluator: RetrievalEvaluator,
        domain: str,
        topology_signature: str | None,
        compatibility: QueryCompatibility,
        patch_resolver: Callable[[str], dict[str, Any]],
    ) -> None:
        self.retriever = retriever
        self.evaluator = evaluator
        self.domain = domain
        self.topology_signature = topology_signature
        self.compatibility = compatibility
        self.patch_resolver = patch_resolver
        self._last_retrieved: list[str] = []

    async def __call__(
        self, diagnosis: Diagnosis, observation: Observation
    ) -> RepairCandidate | None:
        query = RetrievalQuery(
            text=" ".join(
                [
                    diagnosis.error_code,
                    diagnosis.stage,
                    diagnosis.suspected_component or "",
                ]
            ),
            domain=self.domain,
            topology_signature=self.topology_signature,
            compatibility=self.compatibility,
            types=frozenset({MemoryType.REPAIR_CASE}),
            statuses=frozenset({MemoryStatus.VERIFIED}),
            error_signature=ErrorSignature(
                **{
                    "class": diagnosis.error_code,
                    "exception": (
                        diagnosis.exception_chain[-1].exception_type
                        if diagnosis.exception_chain
                        else None
                    ),
                    "feature_pattern": diagnosis.suspected_component,
                    "stage": diagnosis.stage,
                }
            ),
            require_executable=True,
            top_k=1,
        )
        result = self.retriever.retrieve(query)
        self._last_retrieved = [hit.record.id for hit in result.hits]
        if not result.hits:
            return None
        hit = result.hits[0]
        if not hit.executable or not isinstance(hit.record.structured, RepairCase):
            return None
        repair = hit.record.structured
        declared_scope = repair.applicability.get("scope")
        if declared_scope != diagnosis.affected_scope.model_dump(mode="json"):
            return None
        payload = self.patch_resolver(repair.patch_ref.uri)
        return RepairCandidate(
            kind=RepairKind.REPAIR_CASE,
            observation_id=observation.observation_id,
            diagnosis_fingerprint=diagnosis.fingerprint,
            scope=diagnosis.affected_scope,
            verifier=(
                repair.verification.verifier.identifier
                if repair.verification.verifier
                else "repair-case-runtime-verifier"
            ),
            payload=payload,
            provenance=f"memory:{hit.record.id}",
            repair_case_id=hit.record.id,
            required_gates=frozenset({"static", "runtime"}),
        )

    def record_result(self, candidate: RepairCandidate, success: bool) -> None:
        self.evaluator.record(
            RetrievalOutcome(
                retrieved_ids=self._last_retrieved,
                adopted_ids=[candidate.repair_case_id] if candidate.repair_case_id else [],
                execution_attempted=True,
                execution_success=success,
                repair_attempted=True,
                repair_success=success,
            )
        )
