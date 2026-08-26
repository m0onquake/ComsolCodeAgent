"""Production V2 cylindrical-bearing driver used by Web and CLI adapters."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from comsol_agent.cli.config import load_config
from comsol_agent.llm.router import create_provider
from comsol_agent.v2.contracts import GoalSpec, RunStatus, SourceRef
from comsol_agent.v2.domains.bearing import (
    BearingNaturalLanguageIntake,
    BearingPlanner,
    BearingSpec,
    BearingWorkflowTool,
    IntakeStatus,
    ReviewedStrictAuditCollector,
    bearing_extensions,
)
from comsol_agent.v2.extensions import (
    CompatibilityPolicy,
    ExtensionLoader,
    ExtensionRegistry,
    PermissionPolicy,
    PermissionSet,
    RegistryToolExecutor,
)
from comsol_agent.v2.kernel import AgentKernel, BudgetLimits, EventBus, EventType, RunBudget
from comsol_agent.v2.memory import ContextPack, ContextPackBuilder
from comsol_agent.v2.model_gateway import ModelGateway, ProviderBackend
from comsol_agent.v2.repair import ObservationRepairRouter, RepairExecutionContext
from comsol_agent.v2.runtime.comsol import (
    ArtifactStore,
    ComsolRuntime,
    InProcessWorkerExecutor,
    MphBackendAdapter,
    RuntimeStageEvent,
)

from .contracts import FailureView, V2EventKind
from .session import Emit, RunControl, TurnRequest, TurnResult


class BearingV2Driver:
    """Natural language -> pinned plan -> Kernel -> Runtime -> strict audit."""

    def __init__(
        self,
        *,
        output_root: Path | str = "reports/v2_m8_web_evidence",
        comsol_version: str = "6.2",
        cores: int = 1,
        timeout_seconds: float = 1800,
    ) -> None:
        self.output_root = Path(output_root).resolve()
        self.comsol_version = comsol_version
        self.cores = cores
        self.timeout_seconds = timeout_seconds

    async def run(
        self,
        request: TurnRequest,
        control: RunControl,
        emit: Emit,
    ) -> TurnResult:
        config = load_config()
        provider = create_provider(
            config.llm.provider,
            model=config.llm.model,
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
        )
        model_trace: list[dict[str, Any]] = []
        gateway = ModelGateway(
            ProviderBackend(provider, provider_name=config.llm.provider),
            trace_sink=model_trace.append,
        )
        current = (
            BearingSpec.model_validate(request.current_specification)
            if request.current_specification
            else None
        )
        await emit(
            V2EventKind.SPECIFICATION,
            "intake",
            "running",
            "bearing.intake",
            "Parsing the natural-language engineering specification.",
            {"utterance": request.requirement},
        )
        intake = await BearingNaturalLanguageIntake(gateway).parse(
            [request.requirement], current=current
        )
        await self._emit_model_budget(emit, intake.model_response.model_dump(mode="json"))
        if intake.status != IntakeStatus.READY or intake.specification is None:
            data = FailureView(
                error_class=f"intake_{intake.status.value}",
                message="; ".join(intake.errors or intake.clarification_questions),
                stage="intake",
                evidence=intake.model_dump(mode="json"),
            )
            await emit(
                V2EventKind.FAILURE,
                "intake",
                "failed",
                "bearing.intake",
                data.message,
                data.model_dump(mode="json"),
            )
            raise RuntimeError(data.message)
        specification = intake.specification
        specification_payload = _spec_payload(specification)
        await emit(
            V2EventKind.SPECIFICATION,
            "intake",
            "passed",
            "bearing.intake",
            "Specification parsed and locally validated.",
            {
                "specification": specification_payload,
                "provenance": {
                    key: value.value for key, value in intake.provenance.items()
                },
            },
        )

        context = _verified_context()
        await emit(
            V2EventKind.RETRIEVAL,
            "retrieve",
            "passed",
            "v2.memory",
            "Compatible evidence context retrieved; it remains non-authoritative.",
            context.model_dump(mode="json"),
        )
        goal = GoalSpec(
            objective="Build and strictly audit the requested cylindrical roller bearing",
            constraints={
                "full_model_llm_rewrite": False,
                "model_id": f"m8-bearing-{uuid4().hex[:12]}",
                "timeout_seconds": self.timeout_seconds,
                "resume_checkpoint": request.checkpoint,
            },
            acceptance=["strict_physics_audit"],
            trace_id=request.turn_id,
        )
        registry = _registry(self.comsol_version)
        runtime: ComsolRuntime | None = None

        async def stage_sink(stage_event: RuntimeStageEvent) -> None:
            record = stage_event.record
            await emit(
                V2EventKind.COMSOL_STAGE,
                record.stage.value,
                record.state.value,
                "comsol.runtime",
                f"COMSOL {record.stage.value}: {record.state.value}",
                {
                    "run_id": stage_event.run_id,
                    "model_id": stage_event.model_id,
                    "detail": record.detail,
                    "started_at": record.started_at,
                    "finished_at": record.finished_at,
                },
            )

        if request.mode == "live":
            run_root = self.output_root / request.session_id
            collector = ReviewedStrictAuditCollector(
                specification,
                run_root / request.turn_id / "strict_audit",
                case_id=f"V2-M8-WEB-{request.turn_id[:8]}",
            )
            backend = MphBackendAdapter(
                version=self.comsol_version,
                cores=self.cores,
                port=0,
                auditor=collector,
            )
            runtime = ComsolRuntime(
                backend=backend,
                artifacts=ArtifactStore(run_root),
                worker=InProcessWorkerExecutor(backend),
                stage_sink=stage_sink,
            )
        workflow = BearingWorkflowTool(runtime or SimpleNamespace())
        for extension in bearing_extensions():
            await registry.register(extension)
        await registry.register(workflow)
        manifest = None
        planner = None
        try:
            async with registry.snapshot() as snapshot:
                workflow.failure_router = ObservationRepairRouter(
                    snapshot,
                    execution_context=RepairExecutionContext(
                        agent_version=snapshot.agent_version,
                        comsol_version=snapshot.comsol_version,
                        mandatory_gates=frozenset(goal.acceptance),
                    ),
                )
                planner = await BearingPlanner(gateway).plan(
                    goal=goal,
                    requested=specification,
                    current=current,
                    registry_snapshot=snapshot,
                    budget={"max_solves": 3, "max_llm_full_model_rewrites": 0},
                    context_pack=context,
                )
                await self._emit_model_budget(
                    emit, planner.model_response.model_dump(mode="json")
                )
                await emit(
                    V2EventKind.PLAN,
                    "plan",
                    "passed",
                    "bearing.planner",
                    f"Policy accepted route: {planner.route.value}",
                    {
                        "route": planner.route.value,
                        "change_set": (
                            planner.change_set.model_dump(mode="json")
                            if planner.change_set
                            else None
                        ),
                        "plan": planner.plan.model_dump(mode="json"),
                        "cited_context_ids": planner.cited_context_ids,
                        "llm_full_model_rewrite": False,
                    },
                )
                if request.mode == "plan_only":
                    return TurnResult(specification=specification_payload)
                workflow.bind_snapshot(snapshot)
                event_bus = EventBus(goal.trace_id)

                async def kernel_event(event) -> None:
                    await self._kernel_event(emit, event)

                event_bus.subscribe(kernel_event)
                budget = RunBudget(
                    BudgetLimits(
                        max_actions=10,
                        max_repairs=3,
                        max_elapsed_seconds=self.timeout_seconds,
                    )
                )
                manifest = await AgentKernel(
                    RegistryToolExecutor(snapshot),
                    budget=budget,
                    cancellation=control.cancellation,
                    event_bus=event_bus,
                ).run(goal, planner.plan)
                manifest.versions.update(dict(snapshot.versions))
                manifest.routing_decisions.append(planner.route.value)
                manifest.retrievals.extend(item.source for item in context.observations)
                snapshot_budget = budget.snapshot()
                await emit(
                    V2EventKind.BUDGET,
                    "kernel",
                    "recorded",
                    "agent.kernel",
                    "Kernel budget usage updated.",
                    {
                        "actions_used": snapshot_budget.actions_used,
                        "repairs_used": snapshot_budget.repairs_used,
                        "elapsed_seconds": snapshot_budget.elapsed_seconds,
                        "limits": {
                            "max_actions": snapshot_budget.limits.max_actions,
                            "max_repairs": snapshot_budget.limits.max_repairs,
                            "max_elapsed_seconds": (
                                snapshot_budget.limits.max_elapsed_seconds
                            ),
                        },
                    },
                )
        finally:
            if runtime is not None:
                await runtime.stop()
        assert planner is not None
        assert manifest is not None
        for repair in manifest.repairs:
            await emit(
                V2EventKind.REPAIR,
                "repair",
                repair.outcome or "recorded",
                repair.source or "agent.kernel",
                f"Repair attempt {repair.attempt}: {repair.error_class}",
                repair.model_dump(mode="json"),
            )
        for audit in manifest.audits:
            await emit(
                V2EventKind.AUDIT,
                "D_results_audit",
                "passed" if audit.get("passed") else "failed",
                str(audit.get("auditor_id") or "bearing.auditor"),
                str(audit.get("summary") or "Strict audit evidence recorded."),
                audit,
            )
        if manifest.status != RunStatus.COMPLETED:
            observation = (
                manifest.action_records[-1].observation
                if manifest.action_records
                else None
            )
            runtime_failure = (observation.data.get("failure") if observation else None) or {}
            failure = FailureView(
                error_class=(
                    str(observation.error_class)
                    if observation and observation.error_class
                    else "run_failed"
                ),
                message=manifest.failure_reason or "V2 run failed",
                stage=manifest.current_stage,
                code=runtime_failure.get("code"),
                retryable=bool(observation and observation.retryable),
                termination_confirmed=runtime_failure.get("termination_confirmed"),
                evidence={
                    "manifest_status": manifest.status.value,
                    "observation": observation.model_dump(mode="json") if observation else None,
                    "repairs": [item.model_dump(mode="json") for item in manifest.repairs],
                },
            )
            await emit(
                V2EventKind.FAILURE,
                str(manifest.current_stage),
                "failed",
                "agent.kernel",
                failure.message,
                failure.model_dump(mode="json"),
            )
            raise RuntimeError(failure.message)
        runtime_artifacts = _runtime_artifact_index(manifest)
        artifacts = []
        for item in manifest.artifacts:
            runtime_item = runtime_artifacts.get(item.uri, {})
            artifacts.append(
                {
                    "artifact_id": item.sha256 or uuid4().hex,
                    "name": Path(item.uri).name,
                    "uri": item.uri,
                    "media_type": item.media_type,
                    "sha256": item.sha256,
                    "stage": runtime_item.get("stage"),
                    "size_bytes": runtime_item.get("size_bytes"),
                }
            )
        native_plot = _native_plot_artifact(manifest)
        if native_plot is not None:
            artifacts.append(native_plot)
        return TurnResult(
            specification=specification_payload,
            checkpoint=manifest.checkpoints[-1] if manifest.checkpoints else request.checkpoint,
            manifest=manifest.model_dump(mode="json"),
            artifacts=artifacts,
        )

    @staticmethod
    async def _emit_model_budget(emit: Emit, response: dict[str, Any]) -> None:
        usage = response.get("usage") or {}
        await emit(
            V2EventKind.BUDGET,
            "llm",
            "recorded",
            "model_gateway",
            "Model usage recorded.",
            {
                "llm_prompt_tokens": usage.get(
                    "prompt_tokens", usage.get("input_tokens", 0)
                ),
                "llm_completion_tokens": usage.get(
                    "completion_tokens", usage.get("output_tokens", 0)
                ),
                "llm_total_tokens": usage.get("total_tokens", 0),
                "provider": response.get("provider"),
                "model": response.get("model"),
                "request_id": response.get("request_id"),
            },
        )

    @staticmethod
    async def _kernel_event(emit: Emit, event) -> None:
        payload = dict(event.payload)
        if event.event_type == EventType.ACTION_STARTED:
            await emit(
                V2EventKind.TOOL,
                str(event.stage),
                "running",
                "agent.kernel",
                f"Executing {payload.get('tool')}",
                payload,
            )
        elif event.event_type == EventType.OBSERVATION_RECORDED:
            await emit(
                V2EventKind.TOOL,
                str(event.stage),
                "passed" if payload.get("success") else "failed",
                "agent.kernel",
                "Structured tool Observation recorded.",
                payload,
            )
        elif event.event_type == EventType.REPAIR_SCHEDULED:
            await emit(
                V2EventKind.REPAIR,
                str(event.stage),
                "scheduled",
                "agent.kernel",
                "Bounded repair scheduled.",
                payload,
            )
        elif event.event_type == EventType.BUDGET_EXHAUSTED:
            await emit(
                V2EventKind.BUDGET,
                str(event.stage),
                "failed",
                "agent.kernel",
                "Budget exhausted.",
                payload,
            )


def _registry(comsol_version: str) -> ExtensionRegistry:
    root = Path(__file__).resolve().parents[4]
    loader = ExtensionLoader(
        compatibility=CompatibilityPolicy(agent_version="2.0", comsol_version=comsol_version),
        permissions=PermissionPolicy(
            PermissionSet(filesystem="write", shell="none", comsol="solve", network="none")
        ),
        trusted_manifest_roots=(root,),
        trusted_code_roots=(root,),
    )
    return ExtensionRegistry(loader)


def _verified_context() -> ContextPack:
    return ContextPack(
        query_summary="M7 verified cylindrical bearing deterministic path",
        observations=[
            ContextPackBuilder.observation(
                observation_id="m7-real-gate-20260823",
                summary=(
                    "The verified signature uses the deterministic builder and strict audit; "
                    "retrieval supplies context, not authority."
                ),
                source=SourceRef(
                    kind="audit_manifest",
                    identifier="m7-bearing-real-comsol-20260823",
                    version="1",
                    uri="docs/v2/evidence/m7-bearing-real-comsol-20260823.json",
                ),
            )
        ],
    )


def _spec_payload(specification: BearingSpec) -> dict[str, Any]:
    return specification.model_dump(
        mode="json", exclude={"topology_signature", "build_signature"}
    )


def _runtime_artifact_index(manifest) -> dict[str, dict[str, Any]]:
    if not manifest.action_records:
        return {}
    runtime = manifest.action_records[-1].observation.data.get("runtime") or {}
    return {
        str(item.get("path")): item
        for item in runtime.get("artifacts", [])
        if item.get("path")
    }


def _native_plot_artifact(manifest) -> dict[str, Any] | None:
    for audit in manifest.audits:
        if audit.get("kind") != "bearing_strict_physics":
            continue
        path = Path(
            str(
                ((audit.get("evidence") or {}).get("native_plot_evidence") or {}).get(
                    "filepath", ""
                )
            )
        )
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "artifact_id": digest.hexdigest(),
            "name": path.name,
            "uri": str(path.resolve()),
            "media_type": "image/png",
            "sha256": digest.hexdigest(),
            "stage": "D_results_audit",
            "size_bytes": path.stat().st_size,
        }
    return None
