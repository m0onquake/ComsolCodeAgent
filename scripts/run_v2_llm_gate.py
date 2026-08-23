"""Opt-in real-provider M7.5 smoke and optional real COMSOL end-to-end gate."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from comsol_agent.cli.config import load_config
from comsol_agent.llm.router import create_provider
from comsol_agent.v2.contracts import GoalSpec, SourceRef
from comsol_agent.v2.domains.bearing import (
    BearingNaturalLanguageIntake,
    BearingPlanner,
    IntakeStatus,
)
from comsol_agent.v2.memory import ContextPack, ContextPackBuilder
from comsol_agent.v2.model_gateway import ModelGateway, ProviderBackend

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
    intake = await BearingNaturalLanguageIntake(gateway).parse([arguments.requirement])
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
    planner = await BearingPlanner(gateway).plan(
        goal=GoalSpec(
            objective="Build and strictly audit the requested cylindrical roller bearing",
            constraints={"full_model_llm_rewrite": False},
            acceptance=["strict_physics_audit"],
        ),
        requested=intake.specification,
        current=None,
        registry_snapshot=[
            "bearing.cylindrical-roller.builder",
            "bearing.load-continuation",
            "bearing.strict-audit",
        ],
        budget={"max_solves": 3, "max_llm_full_model_rewrites": 0},
        context_pack=context,
    )
    spec_path = output_dir / "validated_bearing_spec.json"
    spec_path.write_text(
        intake.specification.model_dump_json(
            indent=2,
            exclude={"topology_signature", "build_signature"},
        ),
        encoding="utf-8",
    )
    comsol = None
    if arguments.run_comsol:
        comsol_root = output_dir / "comsol"
        command = [
            sys.executable,
            "scripts/run_v2_bearing_gate.py",
            "--cores",
            str(arguments.cores),
            "--timeout-seconds",
            str(arguments.comsol_timeout_seconds),
            "--output-root",
            str(comsol_root),
            "--spec-json",
            str(spec_path),
            "--case-id",
            "V2-M7.5-REAL-LLM-E2E",
        ]
        process = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=arguments.comsol_timeout_seconds + 60,
            check=False,
        )
        evidence_files = list(comsol_root.glob("*/v2_m7_audit_evidence.json"))
        gate_evidence = (
            json.loads(evidence_files[-1].read_text(encoding="utf-8"))
            if evidence_files
            else None
        )
        comsol = {
            "returncode": process.returncode,
            "success": bool(gate_evidence and gate_evidence.get("success")),
            "evidence_path": str(evidence_files[-1]) if evidence_files else None,
            "stdout_tail": process.stdout[-2000:],
            "stderr_tail": process.stderr[-2000:],
        }
    evidence = {
        "success": bool(planner.policy_validated and (comsol is None or comsol["success"])),
        "gate": "v2_m7_5_real_llm" + ("_comsol_e2e" if arguments.run_comsol else "_smoke"),
        "provider": config.llm.provider,
        "model": config.llm.model,
        "prompt_contracts": [
            "bearing.requirement.intake@1.0.0",
            "bearing.execution.planner@1.0.0",
        ],
        "requirement": arguments.requirement,
        "intake": intake.model_dump(mode="json"),
        "planner": planner.model_dump(mode="json"),
        "trace": trace,
        "api_key_recorded": False,
        "llm_full_model_rewrite": False,
        "comsol": comsol,
    }
    return _write(output_dir, evidence)


def _write(output_dir: Path, evidence: dict) -> dict:
    path = output_dir / "v2_m7_5_llm_evidence.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence["evidence_path"] = str(path)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirement", default=DEFAULT_REQUIREMENT)
    parser.add_argument("--output-root", default="reports/v2_m7_5_llm_evidence")
    parser.add_argument("--run-comsol", action="store_true")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--comsol-timeout-seconds", type=float, default=1200)
    evidence = asyncio.run(run(parser.parse_args()))
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    raise SystemExit(0 if evidence["success"] else 1)


if __name__ == "__main__":
    main()
