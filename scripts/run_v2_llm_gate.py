"""Opt-in real-provider M7.5 smoke and optional real COMSOL end-to-end gate."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
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
from comsol_agent.v2.kernel import AgentKernel
from comsol_agent.v2.memory import ContextPack, ContextPackBuilder
from comsol_agent.v2.model_gateway import ModelGateway, ProviderBackend
from comsol_agent.v2.repair import ObservationRepairRouter, RepairExecutionContext
from comsol_agent.v2.runtime.comsol import (
    ArtifactStore,
    ComsolRuntime,
    InProcessWorkerExecutor,
    MphBackendAdapter,
)

DEFAULT_REQUIREMENT = (
    "创建一个三维单列圆柱滚子轴承：10个滚子，内径45 mm，外径90 mm，宽20 mm；"
    "滚子直径7.5 mm、长17 mm，节圆半径34 mm，内滚道外半径29.5 mm，外滚道内半径38.5 mm；"
    "保持架内外半径29.8和38.2 mm，兜孔间隙0.3 mm，总径向游隙1.5 mm，相位7.5度；"
    "在+X方向施加1 N径向载荷，体网格5 mm，接触网格2.4 mm，求解器相对容差0.001。"
)


async def run(arguments: argparse.Namespace) -> dict:
    config = load_config()
    provider = create_provider(
        config.llm.provider,
        model=config.llm.model,
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
    )
    trace: list[dict] = []
    gateway = ModelGateway(
        ProviderBackend(provider, provider_name=config.llm.provider),
        trace_sink=trace.append,
    )
    output_dir = Path(arguments.output_root).resolve() / (
        datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    current = (
        BearingSpec.model_validate_json(
            Path(arguments.current_spec_json).read_text(encoding="utf-8")
        )
        if arguments.current_spec_json
        else None
    )
    intake = await BearingNaturalLanguageIntake(gateway).parse(
        [arguments.requirement], current=current
    )
    if intake.status != IntakeStatus.READY or intake.specification is None:
        evidence = {
            "success": False,
            "stage": "intake",
            "provider": config.llm.provider,
            "model": config.llm.model,
            "intake": intake.model_dump(mode="json"),
            "trace": trace,
        }
        return _write(output_dir, evidence)
    context = ContextPack(
        query_summary="M7 verified cylindrical bearing deterministic path",
        observations=[
            ContextPackBuilder.observation(
                observation_id="m7-real-gate-20260823",
                summary=(
                    "The verified cylindrical-bearing signature uses the deterministic builder "
                    "and strict COMSOL audit; retrieval supplies context, not authority."
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
    goal = GoalSpec(
            objective="Build and strictly audit the requested cylindrical roller bearing",
            constraints={
                "full_model_llm_rewrite": False,
                "model_id": arguments.model_id or f"bearing-{uuid4().hex[:16]}",
                "timeout_seconds": arguments.comsol_timeout_seconds,
                "resume_checkpoint": arguments.resume_checkpoint,
            },
            acceptance=["strict_physics_audit"],
    )
    runtime = None
    if arguments.run_comsol:
        collector = ReviewedStrictAuditCollector(
            intake.specification,
            output_dir / "strict_audit",
            case_id="V2-M7.5.1-KERNEL-E2E",
        )
        backend = MphBackendAdapter(
            version="6.2", cores=arguments.cores, port=0, auditor=collector
        )
        runtime = ComsolRuntime(
            backend=backend,
            # A stable gate root permits an explicitly supplied compatible B
            # checkpoint from an earlier failed run while every run/model still
            # receives its own isolated subdirectory.
            artifacts=ArtifactStore(Path(arguments.output_root).resolve()),
            worker=InProcessWorkerExecutor(backend),
        )
    workflow = BearingWorkflowTool(runtime or SimpleNamespace())
    registry = _registry()
    for extension in bearing_extensions():
        await registry.register(extension)
    await registry.register(workflow)
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
            requested=intake.specification,
            current=current,
            registry_snapshot=snapshot,
            budget={"max_solves": 3, "max_llm_full_model_rewrites": 0},
            context_pack=context,
        )
        manifest = None
        if arguments.run_comsol:
            workflow.bind_snapshot(snapshot)
            manifest = await AgentKernel(RegistryToolExecutor(snapshot)).run(
                goal, planner.plan
            )
            manifest.versions.update(dict(snapshot.versions))
            manifest.routing_decisions.append(planner.route.value)
            manifest.retrievals.extend(
                item.source for item in context.observations
            )
            manifest.tests.append(
                {
                    "kind": "real_llm_gateway",
                    "provider": config.llm.provider,
                    "model": config.llm.model,
                    "policy_validated": planner.policy_validated,
                    "prompt_contracts": [
                        "bearing.requirement.intake@1.0.0",
                        "bearing.execution.planner@1.0.0",
                    ],
                }
            )
        snapshot_catalog = [
            item.model_dump(mode="json") for item in snapshot.capability_catalog()
        ]
        snapshot_versions = dict(snapshot.versions)
    if runtime is not None:
        await runtime.stop()
    (output_dir / "validated_bearing_spec.json").write_text(
        intake.specification.model_dump_json(
            indent=2, exclude={"topology_signature", "build_signature"}
        ),
        encoding="utf-8",
    )
    kernel_success = bool(manifest and manifest.status == RunStatus.COMPLETED)
    evidence = {
        "success": bool(
            planner.policy_validated
            and (kernel_success if arguments.run_comsol else True)
        ),
        "gate": "v2_m7_5_1_kernel_e2e" if arguments.run_comsol else "v2_m7_5_llm_smoke",
        "provider": config.llm.provider,
        "model": config.llm.model,
        "prompt_contracts": [
            "bearing.requirement.intake@1.0.0",
            "bearing.execution.planner@1.0.0",
        ],
        "requirement": arguments.requirement,
        "intake": intake.model_dump(mode="json"),
        "planner": planner.model_dump(mode="json"),
        "extension_snapshot": {
            "versions": snapshot_versions,
            "capabilities": snapshot_catalog,
        },
        "kernel_manifest": manifest.model_dump(mode="json") if manifest else None,
        "trace": trace,
        "api_key_recorded": False,
        "llm_full_model_rewrite": False,
        "comsol": {
            "requested": bool(arguments.run_comsol),
            "executed_by_kernel": bool(manifest),
            "legacy_gate_subprocess": False,
        },
    }
    return _write(output_dir, evidence)


def _write(output_dir: Path, evidence: dict) -> dict:
    path = output_dir / "v2_m7_5_llm_evidence.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence["evidence_path"] = str(path)
    return evidence


def _registry() -> ExtensionRegistry:
    root = Path(__file__).resolve().parents[1]
    loader = ExtensionLoader(
        compatibility=CompatibilityPolicy(agent_version="2.0", comsol_version="6.2"),
        permissions=PermissionPolicy(
            PermissionSet(
                filesystem="write", shell="none", comsol="solve", network="none"
            )
        ),
        trusted_manifest_roots=(root,),
        trusted_code_roots=(root,),
    )
    return ExtensionRegistry(loader)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirement", default=DEFAULT_REQUIREMENT)
    parser.add_argument("--output-root", default="reports/v2_m7_5_llm_evidence")
    parser.add_argument("--run-comsol", action="store_true")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--comsol-timeout-seconds", type=float, default=1200)
    parser.add_argument("--resume-checkpoint", default=None)
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--current-spec-json", default=None)
    evidence = asyncio.run(run(parser.parse_args()))
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    raise SystemExit(0 if evidence["success"] else 1)


if __name__ == "__main__":
    main()
