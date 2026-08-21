"""M4 acceptance tests for governed multi-level memory and hybrid RAG."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from comsol_agent.v2.contracts import ArtifactRef, SourceRef
from comsol_agent.v2.memory import (
    AuditGates,
    ContextPackBuilder,
    ErrorSignature,
    HybridRetriever,
    JsonMemoryRepository,
    ManifestMigrator,
    MemoryCompatibility,
    MemoryGovernance,
    MemoryLayer,
    MemoryProvenance,
    MemoryQuality,
    MemoryRecord,
    MemoryRelation,
    MemoryRepository,
    MemoryStatus,
    MemoryType,
    PromotionEvidence,
    PromotionRejectedError,
    QueryCompatibility,
    ReferenceCatalog,
    RepairCase,
    RepairVerification,
    RetrievalEvaluator,
    RetrievalHit,
    RetrievalOutcome,
    RetrievalQuery,
    RetrievalResult,
    RuntimeMemory,
    RuntimeMemoryEntry,
    UngovernedMemoryWriteError,
    VerifiedCase,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
GIT_COMMIT = "d" * 40


def artifact(uri: str, digest: str = HASH_A) -> ArtifactRef:
    return ArtifactRef(uri=uri, sha256=digest, media_type="application/json")


def gates(**overrides: bool) -> AuditGates:
    values = {
        "api": True,
        "selections": True,
        "mesh": True,
        "solver": True,
        "target_step": True,
        "load_balance": True,
        "reaction_balance": True,
        "contact_balance": True,
        "stabilization_controlled": True,
        "finite_results": True,
        "native_results": True,
    }
    values.update(overrides)
    return AuditGates(**values)


def provenance(*, complete: bool = True) -> MemoryProvenance:
    return MemoryProvenance(
        run_id="run-1" if complete else None,
        git_commit=GIT_COMMIT if complete else None,
        code_hash=HASH_A if complete else None,
        comsol_version="6.2" if complete else None,
        agent_version="2.0.0",
        agent_schema="1.0",
        contract_version="1.0",
        producer=SourceRef(kind="auditor", identifier="strict.fake", version="1.0"),
    )


def compatibility(
    *, topology: str = "bearing/cylindrical/12", comsol: str = ">=6.2,<7"
) -> MemoryCompatibility:
    return MemoryCompatibility(
        domain="bearing",
        topology_signature=topology,
        comsol=comsol,
        agent_api=">=2,<3",
        builder_versions={"bearing.builder": ">=1,<2"},
        contract_versions={"bearing.spec": "==1.0"},
        scopes=frozenset({"project"}),
    )


def verified_record(
    record_id: str,
    *,
    topology: str = "bearing/cylindrical/12",
    request: str = "12 roller cylindrical bearing +X 101 N",
    audit_gates: AuditGates | None = None,
    provenance_complete: bool = True,
    comsol: str = ">=6.2,<7",
    relations: list[MemoryRelation] | None = None,
) -> MemoryRecord:
    strict_gates = audit_gates or gates()
    case = VerifiedCase(
        original_request=request,
        normalized_request=request.lower(),
        engineering_spec={"domain": "bearing", "roller_count": 12},
        topology_signature=topology,
        geometry_signature="geometry-v1",
        physics_signature="contact-solid-v1",
        solver_signature="stationary-continuation-v1",
        value_sources={"load": {"value": 101.0, "unit": "N", "source": "user"}},
        parameters={"load": 101.0, "roller_count": 12.0},
        baseline_code=artifact(f"artifact://{record_id}/baseline.py", HASH_B),
        segment_hashes={"builder": HASH_C},
        extension_versions={"bearing.builder": "1.2.0"},
        gates=strict_gates,
        measurements={"load": 101.0, "reaction": 100.9},
        artifacts=[artifact(f"artifact://{record_id}/model.mph", HASH_C)],
        applicability={"load_min": 1.0, "load_max": 200.0},
        invalidation_conditions=["COMSOL major version changes"],
        keywords=["bearing", "contact", "101N"],
    )
    return MemoryRecord(
        id=record_id,
        layer=MemoryLayer.EPISODIC,
        type=MemoryType.VERIFIED_CASE,
        summary=request,
        content_ref=f"artifact://{record_id}/manifest.json",
        structured=case,
        provenance=provenance(complete=provenance_complete),
        compatibility=compatibility(topology=topology, comsol=comsol),
        quality=MemoryQuality(),
        relations=relations or [],
    )


def repair_record(record_id: str, *, runtime_verified: bool) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        layer=MemoryLayer.EPISODIC,
        type=MemoryType.REPAIR_CASE,
        summary="Create a selection feature before referencing it",
        content_ref=f"artifact://{record_id}/manifest.json",
        structured=RepairCase(
            error_signature={
                "class": "UNKNOWN_FEATURE",
                "exception": "FlException",
                "feature_pattern": "box_*",
                "stage": "selections",
            },
            root_cause="Intersection referenced a Box before creation",
            failed_code_hash=HASH_B,
            patch_ref=artifact(f"artifact://{record_id}/repair.diff", HASH_C),
            repair_rule_id="comsol.selection.create_before_use",
            verification=RepairVerification(
                static=True,
                runtime=runtime_verified,
                verifier=SourceRef(kind="test", identifier="fake-runtime", version="1"),
            ),
            keywords=["unknown feature", "selection", "box"],
        ),
        provenance=provenance(),
        compatibility=compatibility(),
    )


def api_rule_record(record_id: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        layer=MemoryLayer.SEMANTIC,
        type=MemoryType.API_RULE,
        summary="Versioned COMSOL selection API rule",
        content_ref=f"artifact://{record_id}/rule.json",
        structured={
            "rule": "create selections before use",
            "stage": "selections",
            "version": "1.0",
        },
        provenance=provenance(),
        compatibility=compatibility(),
        citations=[
            SourceRef(
                kind="code",
                identifier="selection-builder",
                version="1.0",
                uri=f"artifact://{record_id}/source.py",
            )
        ],
    )


def environment(*, comsol_version: str = "6.2") -> QueryCompatibility:
    return QueryCompatibility(
        comsol_version=comsol_version,
        agent_version="2.1.0",
        builder_versions={"bearing.builder": "1.4.0"},
        contract_versions={"bearing.spec": "1.0"},
        scopes=frozenset({"project"}),
    )


def evidence(**overrides) -> PromotionEvidence:
    values = {
        "auditor_id": "strict.fake",
        "final_spec": True,
        "all_stages_executed": True,
        "target_step_returned": True,
        "gates": gates(),
        "artifacts_readable": True,
        "artifact_hashes_complete": True,
        "unresolved_high_warnings": 0,
    }
    values.update(overrides)
    return PromotionEvidence(**values)


def promote_case(governance: MemoryGovernance, record: MemoryRecord) -> MemoryRecord:
    governance.ingest(record)
    governance.nominate(record.id)
    return governance.promote_verified_case(record.id, evidence())


def catalog_for(*records: MemoryRecord) -> ReferenceCatalog:
    values: dict[str, str | None] = {}
    for record in records:
        values[record.content_ref or ""] = None
        structured = record.structured
        if isinstance(structured, VerifiedCase):
            values[structured.baseline_code.uri] = structured.baseline_code.sha256
            values.update({item.uri: item.sha256 for item in structured.artifacts})
        elif isinstance(structured, RepairCase):
            values[structured.patch_ref.uri] = structured.patch_ref.sha256
    values.pop("", None)
    return ReferenceCatalog(values)


class TestMemoryContractsAndLayers:
    def test_contracts_are_strict_typed_and_emit_schema(self):
        schema = MemoryRecord.model_json_schema()
        assert schema["additionalProperties"] is False
        assert {"provenance", "compatibility", "structured"}.issubset(schema["required"])
        with pytest.raises(ValidationError):
            MemoryRecord.model_validate(
                {**verified_record("mem_bad").model_dump(), "unexpected": True}
            )

    def test_working_and_session_memory_never_enter_long_term_records(self):
        runtime = RuntimeMemory()
        runtime.append(
            RuntimeMemoryEntry(
                layer=MemoryLayer.WORKING,
                content={"observation": "temporary"},
                source=SourceRef(kind="run", identifier="run-1"),
            )
        )
        assert len(runtime.entries(MemoryLayer.WORKING)) == 1
        runtime.clear_working()
        assert runtime.entries(MemoryLayer.WORKING) == ()
        with pytest.raises(ValidationError, match="RuntimeMemory"):
            MemoryRecord.model_validate(
                {
                    **verified_record("mem_layer").model_dump(),
                    "layer": MemoryLayer.WORKING,
                }
            )


class TestGovernance:
    def test_ingest_forces_quarantine_and_strict_evidence_promotes(self):
        repository = MemoryRepository()
        governance = MemoryGovernance(repository)
        submitted = verified_record("mem_verified").model_copy(
            update={"status": MemoryStatus.VERIFIED}
        )
        governance.ingest(submitted)
        assert repository.require(submitted.id).status == MemoryStatus.QUARANTINED
        governance.nominate(submitted.id)
        promoted = governance.promote_verified_case(submitted.id, evidence())
        assert promoted.executable
        assert promoted.validated_at is not None

    def test_store_rejects_verified_records_that_bypass_governance(self):
        repository = MemoryRepository()
        submitted = verified_record("mem_bypass").model_copy(
            update={"status": MemoryStatus.VERIFIED}
        )
        with pytest.raises(UngovernedMemoryWriteError, match="quarantine"):
            repository.add(submitted)

    @pytest.mark.parametrize(
        ("record", "promotion", "message"),
        [
            (
                verified_record("mem_no_provenance", provenance_complete=False),
                lambda governance, item: governance.promote_verified_case(item.id, evidence()),
                "provenance",
            ),
            (
                verified_record("mem_failed_gate", audit_gates=gates(load_balance=False)),
                lambda governance, item: governance.promote_verified_case(
                    item.id, evidence(gates=gates(load_balance=False))
                ),
                "audit gates",
            ),
            (
                repair_record("mem_unverified_repair", runtime_verified=False),
                lambda governance, item: governance.promote_repair_case(item.id),
                "runtime verification",
            ),
        ],
    )
    def test_unverified_cases_cannot_be_promoted(self, record, promotion, message):
        governance = MemoryGovernance(MemoryRepository())
        governance.ingest(record)
        governance.nominate(record.id)
        with pytest.raises(PromotionRejectedError, match=message):
            promotion(governance, record)

    def test_deletion_removes_payload_and_persists_only_tombstone(self, tmp_path: Path):
        path = tmp_path / "memory.json"
        repository = JsonMemoryRepository(path)
        governance = MemoryGovernance(repository)
        record = verified_record("mem_delete")
        governance.ingest(record)
        receipt = governance.delete(record.id, "user requested deletion")

        restored = JsonMemoryRepository(path)
        assert restored.get(record.id) is None
        assert restored.tombstone(record.id) == receipt
        assert record.summary not in path.read_text(encoding="utf-8")


class TestHybridRetrieval:
    def test_versioned_api_rule_without_query_versions_is_rejected_from_context(self):
        repository = MemoryRepository()
        governance = MemoryGovernance(repository)
        rule = api_rule_record("mem_versioned_rule")
        governance.ingest(rule)
        governance.nominate(rule.id)
        active = governance.activate_fact(rule.id)
        result = HybridRetriever(
            repository,
            reference_validator=ReferenceCatalog(
                {
                    active.content_ref: None,
                    active.citations[0].uri: None,
                }
            ),
        ).retrieve(
            RetrievalQuery(
                text="selection API",
                domain="bearing",
                topology_signature="bearing/cylindrical/12",
            )
        )
        pack = ContextPackBuilder().build(result)

        assert result.hits == []
        assert result.rejected[0].record_id == rule.id
        assert {
            "COMSOL version required for compatibility check",
            "Agent version required for compatibility check",
            "builder version missing: bearing.builder",
            "contract version missing: bearing.spec",
        }.issubset(result.rejected[0].reasons)
        assert pack.api_rules == []

        incomplete_hit = RetrievalHit(
            record=active,
            score=1.0,
            executable=False,
            compatibility_checked=False,
            references_checked=True,
        )
        defensive_pack = ContextPackBuilder().build(
            RetrievalResult(query=result.query, hits=[incomplete_hit])
        )
        assert defensive_pack.api_rules == []

    def test_compatible_case_hits_and_wrong_topology_or_version_are_rejected(self):
        repository = MemoryRepository()
        governance = MemoryGovernance(repository)
        matching = verified_record("mem_match")
        wrong_topology = verified_record(
            "mem_wrong_topology", topology="bearing/tapered/16"
        )
        wrong_version = verified_record("mem_wrong_version", comsol=">=5.6,<6")
        for record in (matching, wrong_topology, wrong_version):
            promote_case(governance, record)
        retriever = HybridRetriever(
            repository,
            governance=governance,
            reference_validator=catalog_for(matching, wrong_topology, wrong_version),
        )
        result = retriever.retrieve(
            RetrievalQuery(
                text="cylindrical bearing 101 N",
                domain="bearing",
                topology_signature="bearing/cylindrical/12",
                parameters={"load": 101.0},
                compatibility=environment(),
                types=frozenset({MemoryType.VERIFIED_CASE}),
                require_executable=True,
            )
        )
        assert [hit.record.id for hit in result.hits] == [matching.id]
        rejected = {item.record_id: item.reasons for item in result.rejected}
        assert any("topology" in reason for reason in rejected[wrong_topology.id])
        assert any("COMSOL" in reason for reason in rejected[wrong_version.id])

    def test_hybrid_channels_and_relations_are_visible_and_configurable(self):
        repository = MemoryRepository()
        governance = MemoryGovernance(repository)
        related = verified_record(
            "mem_related",
            request="contact load continuation stable solve",
            relations=[MemoryRelation(kind="derived_from", target_id="artifact-seed")],
        )
        promote_case(governance, related)
        result = HybridRetriever(
            repository, reference_validator=catalog_for(related)
        ).retrieve(
            RetrievalQuery(
                text="contact continuation solve",
                domain="bearing",
                topology_signature="bearing/cylindrical/12",
                compatibility=environment(),
                related_ids=frozenset({"artifact-seed"}),
                require_executable=True,
            )
        )
        assert set(result.hits[0].channel_scores) == {
            "structured",
            "keyword",
            "vector",
            "relation",
        }
        assert result.hits[0].channel_scores["keyword"] > 0
        assert result.hits[0].channel_scores["vector"] > 0
        assert result.hits[0].channel_scores["relation"] > 0

    def test_missing_or_changed_reference_demotes_case_before_execution(self):
        repository = MemoryRepository()
        governance = MemoryGovernance(repository)
        record = verified_record("mem_stale_artifact")
        promote_case(governance, record)
        result = HybridRetriever(
            repository,
            reference_validator=ReferenceCatalog({record.content_ref: None}),
            governance=governance,
        ).retrieve(
            RetrievalQuery(
                text="bearing",
                domain="bearing",
                topology_signature="bearing/cylindrical/12",
                compatibility=environment(),
                require_executable=True,
            )
        )
        assert result.hits == []
        assert repository.require(record.id).status == MemoryStatus.NEEDS_REVALIDATION
        assert any("artifact missing" in reason for reason in result.rejected[0].reasons)

    def test_repair_case_requires_matching_error_and_runtime_verification(self):
        repository = MemoryRepository()
        governance = MemoryGovernance(repository)
        repair = repair_record("mem_repair", runtime_verified=True)
        governance.ingest(repair)
        governance.nominate(repair.id)
        promoted = governance.promote_repair_case(repair.id)
        retriever = HybridRetriever(
            repository, reference_validator=catalog_for(promoted)
        )
        base = {
            "text": "unknown selection feature",
            "domain": "bearing",
            "topology_signature": "bearing/cylindrical/12",
            "compatibility": environment(),
            "types": frozenset({MemoryType.REPAIR_CASE}),
            "require_executable": True,
        }
        matching = retriever.retrieve(
            RetrievalQuery(
                **base,
                error_signature=ErrorSignature(
                    **{
                        "class": "UNKNOWN_FEATURE",
                        "exception": "FlException",
                        "feature_pattern": "box_outer",
                        "stage": "selections",
                    }
                ),
            )
        )
        mismatch = retriever.retrieve(
            RetrievalQuery(
                **base,
                error_signature=ErrorSignature(
                    **{
                        "class": "NONLINEAR_CONVERGENCE",
                        "stage": "solver",
                    }
                ),
            )
        )
        assert matching.hits[0].record.id == repair.id
        assert matching.hits[0].executable
        assert mismatch.hits == []
        assert "signature mismatch" in mismatch.rejected[0].reasons[0]

    def test_invalidated_records_never_reenter_retrieval_pool(self):
        repository = MemoryRepository()
        governance = MemoryGovernance(repository)
        record = verified_record("mem_invalidated")
        promote_case(governance, record)
        governance.invalidate(record.id, "audit threshold increased")
        result = HybridRetriever(
            repository, reference_validator=catalog_for(record)
        ).retrieve(
            RetrievalQuery(
                text="bearing",
                domain="bearing",
                topology_signature="bearing/cylindrical/12",
                compatibility=environment(),
                statuses=frozenset(
                    {MemoryStatus.VERIFIED, MemoryStatus.INVALIDATED}
                ),
            )
        )
        assert result.hits == []
        assert result.rejected[0].record_id == record.id


class TestContextMigrationAndEvaluation:
    def test_context_pack_is_bounded_labeled_and_uses_refs_not_full_code(self):
        repository = MemoryRepository()
        governance = MemoryGovernance(repository)
        records = [verified_record(f"mem_context_{index}") for index in range(4)]
        for record in records:
            promote_case(governance, record)
        result = HybridRetriever(
            repository, reference_validator=catalog_for(*records)
        ).retrieve(
            RetrievalQuery(
                text="bearing contact",
                domain="bearing",
                topology_signature="bearing/cylindrical/12",
                compatibility=environment(),
                require_executable=True,
            )
        )
        pack = ContextPackBuilder().build(result, change_set={"load": [10.1, 101.0]})
        assert pack.primary_case is not None
        assert len(pack.auxiliary_cases) == 2
        serialized = pack.model_dump_json()
        assert "baseline.py" in serialized
        assert "baseline_code" not in serialized
        assert pack.primary_case.role == "case"

    def test_manifest_migration_is_idempotent_and_never_auto_promotes(
        self, tmp_path: Path
    ):
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "run_id": "historical-run",
                    "goal": {"objective": "historical bearing case"},
                    "status": "completed",
                    "versions": {"agent": "2.0.0", "comsol": "6.2"},
                    "artifacts": [{"uri": "artifact://old/model.mph"}],
                    "audits": [{"passed": True}],
                    "code_hashes": {"builder.py": HASH_A},
                    "schema_version": "1.0",
                }
            ),
            encoding="utf-8",
        )
        repository = MemoryRepository()
        migrator = ManifestMigrator(
            MemoryGovernance(repository), agent_version="2.0.0"
        )
        first = migrator.migrate([manifest_path])
        second = migrator.migrate([manifest_path])
        imported = repository.require(first.imported_ids[0])
        assert imported.status == MemoryStatus.QUARANTINED
        assert imported.type == MemoryType.CANDIDATE_CASE
        assert not imported.executable
        assert second.imported_ids == []
        assert second.skipped[0].reason == "content_ref already imported"

    def test_evaluation_metrics_depend_on_post_retrieval_execution_and_audit(self):
        repository = MemoryRepository()
        governance = MemoryGovernance(repository)
        first = verified_record("mem_textually_close")
        second = verified_record("mem_less_similar")
        promote_case(governance, first)
        promote_case(governance, second)
        evaluator = RetrievalEvaluator(repository)
        evaluator.record(
            RetrievalOutcome(
                retrieved_ids=["mem_textually_close"],
                adopted_ids=["mem_textually_close"],
                execution_attempted=True,
                execution_success=False,
                audit_passed=False,
                latency_ms=20,
                context_tokens=100,
            )
        )
        evaluator.record(
            RetrievalOutcome(
                retrieved_ids=["mem_less_similar"],
                adopted_ids=["mem_less_similar"],
                execution_attempted=True,
                execution_success=True,
                audit_passed=True,
                latency_ms=10,
                context_tokens=50,
            )
        )
        metrics = evaluator.metrics()
        assert metrics.first_execution_success_rate == 0.5
        assert metrics.audited_success_rate == 0.5
        assert metrics.average_latency_ms == 15
        assert metrics.average_context_tokens == 75
        assert repository.require(first.id).quality.adoption_success_rate == 0.0
        assert repository.require(second.id).quality.adoption_success_rate == 1.0
