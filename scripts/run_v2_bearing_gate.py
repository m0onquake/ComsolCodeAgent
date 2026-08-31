"""Run the M7 real-COMSOL cylindrical-bearing gate and persist fresh evidence.

This is intentionally separate from pytest.  It reuses a reviewed V1 generated
model asset through a fixed argv boundary, then re-evaluates the fresh result
with the V2 geometry, selection, contact and physical audit contracts.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from comsol_agent.v2.domains.bearing import (
    BearingContactAuditor,
    BearingGeometryAuditor,
    BearingPhysicalAuditor,
    BearingSelectionAuditor,
    BearingSpec,
    LoadDirection,
)
from comsol_agent.v2.domains.bearing.builder import build_plan, deterministic_model_code
from comsol_agent.v2.domains.bearing.verified_asset import ASSET_SHA256


def _magnitude(vector: dict[str, Any]) -> float:
    return math.sqrt(sum(float(vector.get(axis, 0.0)) ** 2 for axis in ("x", "y", "z")))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_bounded_process_group(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: float,
) -> tuple[subprocess.CompletedProcess[str], bool]:
    """Run a gate command and terminate its whole process group on timeout."""

    process = subprocess.Popen(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = process.communicate(timeout=10.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate(timeout=10.0)
    return (
        subprocess.CompletedProcess(command, process.returncode, stdout, stderr),
        timed_out,
    )


async def _v2_audits(spec: BearingSpec, summary: dict[str, Any]) -> dict[str, Any]:
    strict = summary.get("strict_global_contact_solve") or {}
    selection = strict.get("pre_solve_selection_audit") or {}
    final = strict.get("final_audit") or {}
    result_evidence = final.get("target_results") or {}
    stress = (result_evidence.get("stress") or {}).get("value")
    displacement = (result_evidence.get("displacement") or {}).get("value")
    solved_path = Path((strict.get("solved_model_save") or {}).get("saved_to") or "")
    plot_path = Path((strict.get("native_stress_plot") or {}).get("filepath") or "")
    sign = "+" if int(strict.get("load_sign", 1)) > 0 else "-"
    direction = sign + str(strict.get("load_axis", "x")).upper()
    solver_bindings = list(strict.get("initialization_solver_tolerance_bindings") or [])
    for stage in strict.get("force_stage_results") or []:
        solver_bindings.extend(stage.get("solver_relative_tolerance_bindings") or [])
    geometry = await BearingGeometryAuditor().audit(spec)
    selections = await BearingSelectionAuditor().audit(
        {"spec": spec, "selections": selection.get("selections", {})}
    )
    contact = await BearingContactAuditor().audit({"pairs": selection.get("pairs", {})})
    physical = await BearingPhysicalAuditor().audit(
        {
            "spec": spec,
            "metrics": {
                "returned_target_load_n": final.get("target_load_n"),
                "applied_load_n": final.get("applied_load_n"),
                "support_reaction_n": _magnitude(final.get("support_reaction_vector_n") or {}),
                "outer_contact_resultant_n": _magnitude(final.get("outer_contact_vector_n") or {}),
                "stabilization_force_n": final.get("spring_resultant_n"),
                "loaded_zone_direction": direction,
                "max_von_mises_pa": stress,
                "max_displacement_m": displacement,
            },
            "native_plot": str(plot_path) if plot_path.is_file() else "",
            "native_plot_evidence": strict.get("native_stress_plot") or {},
            "result_evidence": result_evidence,
            "solver_evidence": {
                "requested": spec.solver_relative_tolerance,
                "bindings": solver_bindings,
            },
            "solved_mph": str(solved_path) if solved_path.is_file() else "",
        }
    )
    return {
        "geometry": geometry,
        "selection": selections,
        "contact": contact,
        "physical": physical,
        "all_passed": all(item["passed"] for item in (geometry, selections, contact, physical)),
    }


def _spec(spec_json: str | None = None) -> BearingSpec:
    if spec_json:
        return BearingSpec.model_validate_json(Path(spec_json).read_text(encoding="utf-8"))
    return BearingSpec(
        roller_count=10,
        inner_diameter_mm=45,
        outer_diameter_mm=90,
        bearing_width_mm=20,
        roller_diameter_mm=7.5,
        roller_length_mm=17,
        pitch_radius_mm=34,
        inner_race_outer_radius_mm=29.5,
        outer_race_inner_radius_mm=38.5,
        cage_inner_radius_mm=29.8,
        cage_outer_radius_mm=38.2,
        cage_pocket_clearance_mm=0.3,
        radial_clearance_mm=1.5,
        roller_phase_deg=7.5,
        load_direction=LoadDirection.POSITIVE_X,
        target_radial_load_n=1.0,
        provenance={"source": "M7 fresh real-COMSOL gate"},
    )


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    spec = _spec(arguments.spec_json)
    source = (
        Path(arguments.segmented_code).resolve(strict=True) if arguments.segmented_code else None
    )
    evidence_dir = Path(arguments.output_root).resolve() / (
        datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    )
    evidence_dir.mkdir(parents=True, exist_ok=False)
    builder_code = evidence_dir / "v2_builder_code.pyfrag"
    builder_code.write_text(deterministic_model_code(spec), encoding="utf-8")
    model_name = f"v2_m7_bearing_{uuid4().hex}"
    command = [
        sys.executable,
        "scripts/run_agent_3d_bearing_full_demo.py",
        "--direct-fixture-run",
        "--segmented-code-path",
        str(builder_code),
        "--require-free-generated-code",
        "--artifact-root",
        str(evidence_dir),
        "--model-name",
        model_name,
        "--cores",
        str(arguments.cores),
        "--strict-case-id",
        str(arguments.case_id),
        "--strict-target-load-n",
        f"{spec.target_radial_load_n:.15g}",
        "--strict-load-axis",
        spec.comsol_parameters()["load_axis"],
        "--strict-load-sign",
        spec.comsol_parameters()["load_sign"],
        "--strict-cage-pocket-clearance-mm",
        f"{spec.cage_pocket_clearance_mm:.15g}",
        "--strict-roller-angular-offset-deg",
        f"{spec.roller_phase_deg:.15g}",
        "--strict-roller-count",
        str(spec.roller_count),
        "--strict-inner-diameter-mm",
        f"{spec.inner_diameter_mm:.15g}",
        "--strict-outer-diameter-mm",
        f"{spec.outer_diameter_mm:.15g}",
        "--strict-bearing-width-mm",
        f"{spec.bearing_width_mm:.15g}",
        "--strict-roller-diameter-mm",
        f"{spec.roller_diameter_mm:.15g}",
        "--strict-roller-length-mm",
        f"{spec.roller_length_mm:.15g}",
        "--strict-pitch-radius-mm",
        f"{spec.pitch_radius_mm:.15g}",
        "--strict-inner-race-outer-radius-mm",
        f"{spec.inner_race_outer_radius_mm:.15g}",
        "--strict-outer-race-inner-radius-mm",
        f"{spec.outer_race_inner_radius_mm:.15g}",
        "--strict-cage-inner-radius-mm",
        f"{spec.cage_inner_radius_mm:.15g}",
        "--strict-cage-outer-radius-mm",
        f"{spec.cage_outer_radius_mm:.15g}",
        "--strict-solver-relative-tolerance",
        f"{spec.solver_relative_tolerance:.15g}",
    ]
    started = datetime.now().astimezone()
    process, timed_out = _run_bounded_process_group(
        command,
        cwd=Path(__file__).resolve().parents[1],
        timeout_seconds=arguments.timeout_seconds,
    )
    summary_path = evidence_dir / "direct_3d_bearing_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
    audits = asyncio.run(_v2_audits(spec, summary))
    artifacts = []
    for path in evidence_dir.rglob("*"):
        if path.is_file():
            artifacts.append(
                {
                    "relative_path": str(path.relative_to(evidence_dir)),
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    evidence = {
        "success": process.returncode == 0 and audits["all_passed"],
        "gate": "v2_m7_real_comsol_bearing_a_d",
        "started_at": started.isoformat(),
        "finished_at": datetime.now().astimezone().isoformat(),
        "fresh_run": True,
        "model_name": model_name,
        "specification": spec.model_dump(mode="json"),
        "build_plan": build_plan(spec).model_dump(mode="json"),
        "source_asset": {
            "kind": "bundled_content_addressed_asset",
            "sha256": ASSET_SHA256,
            "optional_original_path": str(source) if source else None,
            "original_hash_matches": _sha256(source) == ASSET_SHA256 if source else None,
        },
        "v2_builder_code": {
            "path": str(builder_code),
            "sha256": _sha256(builder_code),
            "generated_by": "bearing.cylindrical-roller.builder@1.0.0",
            "llm_calls": 0,
        },
        "process": {
            "returncode": process.returncode,
            "timed_out": timed_out,
            "timeout_seconds": arguments.timeout_seconds,
            "termination_scope": "process_group",
            "stdout_tail": process.stdout[-8000:],
            "stderr_tail": process.stderr[-8000:],
        },
        "legacy_strict_gate_success": bool(
            (summary.get("strict_global_contact_solve") or {}).get("success")
        ),
        "v2_audits": audits,
        "artifacts": artifacts,
        "verified_memory_promotion": False,
    }
    output = evidence_dir / "v2_m7_audit_evidence.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence["evidence_path"] = str(output)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=1200)
    parser.add_argument("--output-root", default="reports/v2_m7_bearing_evidence")
    parser.add_argument("--spec-json", default=None)
    parser.add_argument("--case-id", default="V2-M7-PARAM10-1N")
    parser.add_argument(
        "--segmented-code",
        default=None,
        help="optional original V1 asset used only for provenance/hash comparison",
    )
    evidence = run(parser.parse_args())
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    raise SystemExit(0 if evidence["success"] else 1)


if __name__ == "__main__":
    main()
