# ruff: noqa: E402
"""Generate and run a topology-specific tapered-roller COMSOL case."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import traceback
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.cli.config import load_config
from comsol_agent.simulation.bearing_builders import build_comsol_bearing
from comsol_agent.simulation.bearing_domain import build_bearing_model_input
from comsol_agent.tools.comsol.client import COMSOLClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-name", default="tapered_roller_baseline")
    parser.add_argument("--output-dir", default="runtime_smoke/tapered_roller_baseline")
    parser.add_argument("--params-json", help="JSON object or path with parameter overrides.")
    parser.add_argument("--geometry-only", action="store_true")
    parser.add_argument("--setup-only", action="store_true")
    parser.add_argument("--cores", type=int, default=1)
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    overrides = _read_params(args.params_json)
    request = build_bearing_model_input(
        "tapered_roller", overrides, allow_defaults=True
    )
    product = build_comsol_bearing(request, model_name=args.case_name)
    (output_dir / "generated_code.py").write_text(product.code + "\n", encoding="utf-8")
    (output_dir / "parameters.json").write_text(
        json.dumps(request.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "topology_manifest.json").write_text(
        json.dumps(asdict(product.manifest), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary: dict[str, Any] = {
        "case_name": args.case_name,
        "family": request.family,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "geometry_only": args.geometry_only,
        "source_model": "blank_model",
        "result_provenance": {},
        "stages": [],
        "artifacts": {},
    }
    client = COMSOLClient.get_instance()
    started = time.monotonic()
    model_name: str | None = None
    log_lines: list[str] = []
    try:
        config = load_config()
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
            port=0,
        )
        handle = client.create(args.case_name)
        model_name = handle.name
        stage_names = ["parameters", "topology"]
        if not args.geometry_only:
            stage_names.extend(
                ["contact", "loads_boundaries", "mesh", "solver", "results"]
            )
        for stage_name in stage_names:
            stage_started = time.monotonic()
            output = client.execute_java(product.sections[stage_name], model_name)
            failed = any(
                marker in output
                for marker in ("Error:", "Execution Error:", "Traceback (most recent call last)")
            )
            record = {
                "name": stage_name,
                "status": "failed" if failed else "passed",
                "elapsed_seconds": round(time.monotonic() - stage_started, 3),
                "output": output,
            }
            summary["stages"].append(record)
            log_lines.append(json.dumps(record, ensure_ascii=False))
            if failed:
                raise RuntimeError(f"{stage_name} failed: {output}")

        if not args.geometry_only and not args.setup_only:
            summary["status"] = "solving"
            summary["checkpoint_at"] = datetime.now(UTC).isoformat()
            _write_summary(output_dir, summary)
            solve_started = time.monotonic()
            handle.mph_model.solve()
            summary["stages"].append(
                {
                    "name": "solve",
                    "status": "passed",
                    "elapsed_seconds": round(time.monotonic() - solve_started, 3),
                }
            )
            max_mises = _scalar(handle.mph_model.evaluate("solid.mises"))
            max_displacement = _scalar(handle.mph_model.evaluate("solid.disp"))
            physics_audit = _physics_audit(
                handle.java_model,
                applied_force_n=(
                    request.load.radial_x.value_si,
                    request.load.radial_y.value_si,
                    request.load.axial.value_si,
                ),
                max_displacement_m=max_displacement,
                roller_count=request.common.rolling_element_count,
                has_axial_location=abs(request.load.axial.value_si) <= 1e-12,
            )
            plot_path = output_dir / "von_mises_native.png"
            plot = _export_native_stress(handle.java_model, plot_path)
            summary["results"] = {
                "max_von_mises_pa": max_mises,
                "max_displacement_m": max_displacement,
            }
            summary["result_provenance"]["max_von_mises_pa"] = "solver-derived"
            summary["result_provenance"]["max_displacement_m"] = "solver-derived"
            summary["native_plot"] = plot
            summary["physics_audit"] = physics_audit
            if plot["success"]:
                summary["artifacts"]["native_von_mises_png"] = str(plot_path)

        mph_path = output_dir / f"{args.case_name}.mph"
        client.save(model_name, mph_path)
        summary["artifacts"]["mph"] = str(mph_path)
        if args.geometry_only:
            summary["status"] = "geometry_verified"
        elif args.setup_only:
            summary["status"] = "setup_verified"
        else:
            summary["status"] = (
                "physical_gate_passed"
                if summary["physics_audit"]["passed"]
                else "physical_gate_failed"
            )
    except BaseException as exc:
        summary["status"] = "failed"
        summary["error"] = _safe_exception_text(exc)
        summary["traceback"] = traceback.format_exc()
        if model_name:
            failed_path = output_dir / f"{args.case_name}_failed.mph"
            try:
                client.save(model_name, failed_path)
                summary["artifacts"]["failed_mph"] = str(failed_path)
            except BaseException as save_exc:
                summary["failed_model_save_error"] = _safe_exception_text(save_exc)
    finally:
        summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
        summary["finished_at"] = datetime.now(UTC).isoformat()
        (output_dir / "solver.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        _write_summary(output_dir, summary)
        COMSOLClient.reset_instance()

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] in {"failed", "physical_gate_failed"}:
        raise SystemExit(1)


def _safe_exception_text(exc: BaseException) -> str:
    try:
        return str(exc)
    except BaseException:
        return f"{type(exc).__module__}.{type(exc).__name__} (exception text unavailable)"


def _write_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _read_params(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {
            "radial_load_x": "500[N]",
            "radial_load_y": "-1200[N]",
            "axial_load": "-450[N]",
        }
    candidate = Path(raw)
    text = candidate.read_text(encoding="utf-8") if candidate.is_file() else raw
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("--params-json must resolve to a JSON object.")
    return value


def _scalar(value: Any) -> float:
    import numpy as np

    array = np.asarray(value, dtype=float).reshape(-1)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        raise ValueError("COMSOL returned no finite values for the requested result.")
    return float(finite.max())


def _physics_audit(
    java_model: Any,
    *,
    applied_force_n: tuple[float, float, float],
    max_displacement_m: float,
    roller_count: int,
    has_axial_location: bool,
) -> dict[str, Any]:
    actual_applied_force = tuple(
        _surface_integral(
            java_model,
            f"audit_applied_force_{axis}",
            "sel_inner_bore_load",
            f"load_scale*{parameter}/intop_inner_bore_load(1)",
        )
        for axis, parameter in zip(
            ("x", "y", "z"),
            ("radial_load_x", "radial_load_y", "axial_load"),
            strict=True,
        )
    )
    reaction = tuple(
        _surface_integral(
            java_model,
            f"audit_reaction_{axis}",
            "geom1_outer_ring_bnd",
            f"solid.RF{axis}",
        )
        for axis in ("x", "y", "z")
    )
    axial_location_reaction = (
        _surface_integral(
            java_model,
            "audit_axial_location_reaction_z",
            "geom1_inner_ring_complete_bnd",
            "solid.RFz",
        )
        if has_axial_location
        else 0.0
    )
    contacts = {
        side: [
            _surface_integral(
                java_model,
                f"audit_contact_{side}_{index}",
                f"sel_{side}_raceway_{index}_contact",
                f"solid.Tn_cp_roller_{index}_{side}",
            )
            for index in range(1, roller_count + 1)
        ]
        for side in ("inner", "outer")
    }
    contacts["flange"] = [
        _surface_integral(
            java_model,
            f"audit_contact_flange_{index}",
            f"sel_flange_{index}_contact",
            f"solid.Tn_cp_roller_{index}_flange",
        )
        for index in range(1, roller_count + 1)
    ]
    contact_inner = sum(abs(value) for value in contacts["inner"])
    contact_outer = sum(abs(value) for value in contacts["outer"])
    contact_flange = sum(abs(value) for value in contacts["flange"])
    inner_displacement = _volume_max(
        java_model,
        "audit_inner_displacement",
        "geom1_inner_ring_complete_dom",
        "solid.disp",
    )
    roller_displacements = [
        _volume_max(
            java_model,
            f"audit_roller_displacement_{index}",
            f"geom1_tapered_roller_{index}_dom",
            "solid.disp",
        )
        for index in range(1, roller_count + 1)
    ]
    inner_spring = tuple(
        _surface_integral(
            java_model,
            f"audit_inner_spring_{axis}",
            "geom1_inner_ring_complete_bnd",
            f"-inner_stability_k*{displacement}",
        )
        for axis, displacement in zip(("x", "y", "z"), ("u", "v", "w"), strict=True)
    )
    roller_spring = tuple(
        _surface_integral(
            java_model,
            f"audit_roller_spring_{axis}",
            "sel_all_roller_boundaries",
            f"-roller_stability_k*{displacement}",
        )
        for axis, displacement in zip(("x", "y", "z"), ("u", "v", "w"), strict=True)
    )
    total_spring = tuple(inner_spring[i] + roller_spring[i] for i in range(3))
    applied_norm = math.sqrt(sum(value * value for value in applied_force_n))
    load_error = math.sqrt(
        sum(
            (actual_applied_force[i] - applied_force_n[i]) ** 2
            for i in range(3)
        )
    ) / max(applied_norm, 1e-12)
    total_physical_reaction = (
        reaction[0],
        reaction[1],
        reaction[2] + axial_location_reaction,
    )
    residual = tuple(
        total_physical_reaction[i] + total_spring[i] + actual_applied_force[i]
        for i in range(3)
    )
    balance_error = math.sqrt(sum(value * value for value in residual)) / max(
        applied_norm, 1e-12
    )
    spring_share = math.sqrt(sum(value * value for value in total_spring)) / max(
        applied_norm, 1e-12
    )
    minimum_contact_force = max(applied_norm * 0.01, 1e-6)
    checks = {
        "load_application_error_within_1_percent": load_error <= 0.01,
        "outer_reaction_balance_within_2_percent": balance_error <= 0.02,
        "weak_spring_reaction_share_within_1_percent": spring_share <= 0.01,
        "inner_contact_transmits_load": abs(contact_inner) >= minimum_contact_force,
        "outer_contact_transmits_load": abs(contact_outer) >= minimum_contact_force,
        "flange_contact_is_active": abs(contact_flange) >= minimum_contact_force,
        "inner_ring_displacement_below_1_mm": 0 <= inner_displacement <= 0.001,
        "rolling_element_displacement_below_5_mm": max(roller_displacements) <= 0.005,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "applied_force_n": applied_force_n,
        "integrated_applied_force_n": actual_applied_force,
        "load_application_relative_error": load_error,
        "outer_reaction_n": reaction,
        "inner_axial_location_reaction_n": [0.0, 0.0, axial_location_reaction],
        "total_physical_reaction_n": total_physical_reaction,
        "force_balance_residual_n": residual,
        "force_balance_relative_error": balance_error,
        "inner_weak_spring_force_n": inner_spring,
        "roller_weak_spring_force_n": roller_spring,
        "total_weak_spring_force_n": total_spring,
        "weak_spring_reaction_share": spring_share,
        "weak_spring_reaction_method": (
            "Direct COMSOL surface integral of -k*u on each weak foundation."
        ),
        "integrated_normal_contact_force_n": {
            "inner": contact_inner,
            "outer": contact_outer,
            "flange": contact_flange,
        },
        "per_roller_normal_contact_force_n": contacts,
        "max_displacement_m": max_displacement_m,
        "inner_ring_max_displacement_m": inner_displacement,
        "per_roller_max_displacement_m": roller_displacements,
        "provenance": "COMSOL solver-derived surface integrals at final load step",
    }


def _surface_integral(
    java_model: Any, tag: str, selection: str, expression: str
) -> float:
    import numpy as np

    numerical = java_model.result().numerical()
    try:
        numerical.remove(tag)
    except Exception:
        pass
    numerical.create(tag, "IntSurface")
    probe = java_model.result().numerical(tag)
    probe.selection().named(selection)
    probe.set("expr", [expression])
    matrix = [[float(item) for item in list(row)] for row in list(probe.getReal())]
    values = np.asarray(matrix, dtype=float).reshape(-1)
    finite = values[np.isfinite(values)]
    if not finite.size:
        raise ValueError(f"No finite COMSOL integral for {expression} on {selection}.")
    return float(finite[-1])


def _volume_max(java_model: Any, tag: str, selection: str, expression: str) -> float:
    import numpy as np

    numerical = java_model.result().numerical()
    try:
        numerical.remove(tag)
    except Exception:
        pass
    numerical.create(tag, "MaxVolume")
    probe = java_model.result().numerical(tag)
    probe.selection().named(selection)
    probe.set("expr", [expression])
    matrix = [[float(item) for item in list(row)] for row in list(probe.getReal())]
    values = np.asarray(matrix, dtype=float).reshape(-1)
    finite = values[np.isfinite(values)]
    if not finite.size:
        raise ValueError(f"No finite COMSOL maximum for {expression} on {selection}.")
    return float(finite[-1])


def _export_native_stress(java_model: Any, output_path: Path) -> dict[str, Any]:
    try:
        plot_group = java_model.result("pg_stress3d")
        plot_group.run()
        exports = java_model.result().export()
        try:
            exports.remove("img_stress")
        except Exception:
            pass
        exports.create("img_stress", "Image2D")
        image = java_model.result().export("img_stress")
        image.set("plotgroup", "pg_stress3d")
        image.set("pngfilename", str(output_path))
        image.run()
        valid = output_path.is_file() and output_path.stat().st_size > 1000
        return {
            "success": valid,
            "path": str(output_path),
            "format": "COMSOL-native Image2D from PlotGroup3D",
            "expression": "solid.mises",
            "provenance": "solver-derived",
            "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        }
    except Exception as exc:
        return {
            "success": False,
            "path": str(output_path),
            "error": str(exc),
            "provenance": "unavailable",
        }


if __name__ == "__main__":
    main()
