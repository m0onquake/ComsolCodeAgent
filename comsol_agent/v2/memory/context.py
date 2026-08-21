"""Stage-sized Context Packs with explicit provenance and authority labels."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from comsol_agent.v2.contracts import SourceRef

from .contracts import (
    ContextPack,
    ContextPackItem,
    ContextRole,
    MemoryRecord,
    MemoryType,
    RepairCase,
    RetrievalHit,
    RetrievalResult,
    VerifiedCase,
)


class ContextPackBuilder:
    """Select bounded evidence; never inline full historical source or artifacts."""

    def build(
        self,
        result: RetrievalResult,
        *,
        change_set: dict[str, Any] | None = None,
        observations: Iterable[ContextPackItem] = (),
    ) -> ContextPack:
        successful = [
            hit
            for hit in result.hits
            if hit.record.type == MemoryType.VERIFIED_CASE and hit.executable
        ]
        primary = self._item(successful[0], ContextRole.CASE) if successful else None
        auxiliary = [
            self._item(hit, ContextRole.CASE) for hit in successful[1:3]
        ]
        api_rules = [
            self._item(hit, ContextRole.FACT)
            for hit in result.hits
            if hit.record.type == MemoryType.API_RULE
            and hit.compatibility_checked
            and hit.references_checked
        ]
        repairs = [
            hit
            for hit in result.hits
            if hit.record.type == MemoryType.REPAIR_CASE and hit.executable
        ]
        return ContextPack(
            query_summary=result.query.text,
            change_set=change_set or {},
            primary_case=primary,
            auxiliary_cases=auxiliary,
            api_rules=api_rules,
            repair_case=self._item(repairs[0], ContextRole.SUGGESTION) if repairs else None,
            observations=list(observations),
        )

    @staticmethod
    def observation(
        *,
        observation_id: str,
        summary: str,
        source: SourceRef,
        data: dict[str, Any] | None = None,
    ) -> ContextPackItem:
        return ContextPackItem(
            record_id=observation_id,
            role=ContextRole.OBSERVATION,
            summary=summary,
            interface_or_delta=data or {},
            source=source,
            confidence=1.0,
            executable=False,
        )

    @staticmethod
    def _item(hit: RetrievalHit, role: ContextRole) -> ContextPackItem:
        record = hit.record
        return ContextPackItem(
            record_id=record.id,
            role=role,
            summary=record.summary,
            interface_or_delta=_bounded_interface(record),
            source=SourceRef(
                kind="memory",
                identifier=record.id,
                version=record.schema_version,
                uri=record.content_ref,
            ),
            confidence=min(1.0, hit.score),
            executable=hit.executable,
            artifact_refs=_artifact_refs(record),
        )


def _bounded_interface(record: MemoryRecord) -> dict[str, Any]:
    structured = record.structured
    if isinstance(structured, VerifiedCase):
        return {
            "topology_signature": structured.topology_signature,
            "geometry_signature": structured.geometry_signature,
            "physics_signature": structured.physics_signature,
            "solver_signature": structured.solver_signature,
            "parameters": structured.parameters,
            "applicability": structured.applicability,
            "invalidation_conditions": structured.invalidation_conditions,
        }
    if isinstance(structured, RepairCase):
        return {
            "error_signature": structured.error_signature.model_dump(
                mode="json", by_alias=True
            ),
            "root_cause": structured.root_cause,
            "repair_rule_id": structured.repair_rule_id,
            "verification": structured.verification.model_dump(mode="json"),
            "applicability": structured.applicability,
        }
    allowed = ("rule", "constraint", "stage", "applicability", "version")
    return {key: structured[key] for key in allowed if key in structured}


def _artifact_refs(record: MemoryRecord) -> list[str]:
    references = [record.content_ref] if record.content_ref else []
    structured = record.structured
    if isinstance(structured, VerifiedCase):
        references.extend(
            [structured.baseline_code.uri, *(artifact.uri for artifact in structured.artifacts)]
        )
    elif isinstance(structured, RepairCase):
        references.append(structured.patch_ref.uri)
    return list(dict.fromkeys(references))
