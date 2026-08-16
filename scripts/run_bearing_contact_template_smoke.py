"""Run the bearing-contact template directly through local COMSOL tools."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.cli.config import load_config
from comsol_agent.memory.archive_store import ArchiveStore
from comsol_agent.simulation.skills import seed_builtin_templates
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.tools.comsol.evaluate import comsol_plot
from comsol_agent.tools.comsol.model_ops import comsol_close_model
from comsol_agent.tools.comsol.solve import comsol_evaluate, comsol_execute_java, comsol_solve
from comsol_agent.tools.simulation import (
    simulation_export_bearing_contact_package,
    simulation_run_template,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the bearing-contact template smoke test.")
    parser.add_argument("--cores", type=int, default=1, help="COMSOL core limit.")
    parser.add_argument("--template-name", default="bearing_contact_hertz_seed")
    parser.add_argument("--model-name", default="bearing_contact_template_smoke")
    parser.add_argument("--archive-path", default="runtime_smoke/bearing_contact_template_smoke.sqlite3")
    parser.add_argument("--artifact-dir", default="runtime_smoke/bearing_contact_template_smoke")
    parser.add_argument("--plot-path", default="runtime_smoke/bearing_contact_template_smoke/von_mises.png")
    parser.add_argument("--package-dir", default="runtime_smoke/bearing_contact_template_smoke/packages")
    parser.add_argument(
        "--params-json",
        default=None,
        help="Inline JSON object of executable template parameter overrides.",
    )
    parser.add_argument("--skip-solve", action="store_true", help="Only build the model/template artifact.")
    args = parser.parse_args()

    archive_path = Path(args.archive_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    Path(args.artifact_dir).mkdir(parents=True, exist_ok=True)

    config = load_config()
    client = COMSOLClient.get_instance()
    model_name: str | None = None
    summary: dict[str, object] = {}
    try:
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        seed_builtin_templates(ArchiveStore(archive_path))
        params = json.loads(args.params_json) if args.params_json else None
        template_result = simulation_run_template(
            name=args.template_name,
            params=params,
            create_model_name=args.model_name,
            close_model=False,
            artifact_dir=args.artifact_dir,
            artifact_name="bearing_contact_template_smoke",
            archive_path=str(archive_path),
        )
        summary["template"] = _compact_result(template_result)
        if not template_result.get("success"):
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
            raise SystemExit(1)

        model_name = str(template_result["model_name"])
        contact_policy_audit = _apply_contact_policy_runtime_audit(model_name, params or {})
        summary["contact_policy_runtime_audit"] = _compact_result(contact_policy_audit)
        if contact_policy_audit.get("attempts"):
            summary["contact_policy_runtime_audit"]["attempts"] = contact_policy_audit.get("attempts")
        if not args.skip_solve:
            solve_result = comsol_solve(model_name)
            summary["solve"] = _compact_result(solve_result)
            if solve_result.get("success"):
                summary["evaluations"] = [
                    _compact_result(comsol_evaluate(model_name, "solid.mises")),
                    _compact_result(comsol_evaluate(model_name, "contact_pressure_guess")),
                ]
                plot_result = comsol_plot(
                    model_name,
                    expression="solid.mises",
                    plot_type="surface",
                    filename=args.plot_path,
                )
                summary["plot"] = _compact_result(plot_result)
                if not plot_result.get("success"):
                    fallback_plot = _render_field_heatmap_from_open_model(
                        model_name,
                        expression="solid.mises",
                        filename=args.plot_path,
                    )
                    summary["plot_fallback"] = _compact_result(fallback_plot)
                    if fallback_plot.get("success"):
                        summary["plot"] = _compact_result(fallback_plot)
                if summary["plot"].get("success"):
                    summary["package"] = _compact_result(
                        simulation_export_bearing_contact_package(
                            model_name=model_name,
                            template_run_id=template_result.get("artifacts", {}).get("run_id"),
                            plot_path=args.plot_path,
                            output_dir=args.package_dir,
                            package_name="bearing_contact_template_package",
                            archive_path=str(archive_path),
                        )
                    )

        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    finally:
        if model_name:
            close_result = comsol_close_model(model_name, save=False)
            if summary:
                print(json.dumps({"close": _compact_result(close_result)}, ensure_ascii=False, indent=2))
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def _compact_result(result: dict) -> dict:
    keys = (
        "success",
        "model_name",
        "template_name",
        "study",
        "elapsed_seconds",
        "status",
        "expression",
        "shape",
        "statistics",
        "value",
        "plot_type",
        "filepath",
        "export_method",
        "fallback_for",
        "directory",
        "json_path",
        "markdown_path",
        "model_path",
        "plot_path",
        "metrics",
        "error",
        "message",
        "contact_policy",
        "friction_effective",
        "accepted_property_count",
    )
    compact = {key: result.get(key) for key in keys if key in result}
    artifacts = result.get("artifacts")
    if isinstance(artifacts, dict):
        compact["run_id"] = artifacts.get("run_id")
        compact["json_path"] = artifacts.get("json_path")
    return compact


def _apply_contact_policy_runtime_audit(model_name: str, params: dict) -> dict:
    """Try to map high-level contact policy onto the COMSOL Contact feature."""
    raw_policy = str(params.get("contact_policy") or params.get("contact_model") or "").lower()
    friction_value = str(params.get("friction_coefficient") or "0.05")
    if "frictionless" in raw_policy or "无摩擦" in raw_policy:
        policy = "frictionless"
    elif "frictional" in raw_policy or "摩擦" in raw_policy or float(_numeric_prefix(friction_value) or 0.0) > 0:
        policy = "frictional"
    else:
        policy = "frictionless"

    if policy == "frictionless":
        candidates = [
            ("friction", "off"),
            ("fric", "off"),
            ("mu", "0"),
            ("fmu", "0"),
        ]
    else:
        candidates = [
            ("friction", "on"),
            ("fric", "on"),
            ("frictionmodel", "coulomb"),
            ("fricmodel", "coulomb"),
            ("mu", "friction_coefficient"),
            ("fmu", "friction_coefficient"),
            ("mufric", "friction_coefficient"),
        ]

    code = [
        "attempts = []",
        "contact_feature = model.component('comp1').physics('solid').feature('contact_ball_race')",
    ]
    for key, value in candidates:
        code.extend([
            "try:",
            f"    contact_feature.set({key!r}, {value!r})",
            f"    attempts.append({{'property': {key!r}, 'value': {value!r}, 'accepted': True}})",
            "except Exception as exc:",
            f"    attempts.append({{'property': {key!r}, 'value': {value!r}, 'accepted': False, 'error': str(exc)}})",
        ])
    code.append("output.write('CONTACT_POLICY_AUDIT|' + repr(attempts))")
    result = comsol_execute_java("\n".join(code), model_name=model_name)
    stdout = str(result.get("stdout") or result.get("output") or "")
    attempts = _extract_contact_policy_attempts(stdout)
    accepted = [item for item in attempts if item.get("accepted")]
    result.update({
        "contact_policy": policy,
        "attempts": attempts,
        "accepted_property_count": len(accepted),
        "friction_effective": policy == "frictional" and any(
            item.get("property") in {"mu", "fmu", "mufric"}
            for item in accepted
        ),
    })
    if policy == "frictional" and not result["friction_effective"]:
        result["message"] = (
            "Frictional contact was requested, but this COMSOL runtime did not accept a recognized "
            "Coulomb friction coefficient property on contact_ball_race; treat this run as normal-contact only."
        )
    return result


def _numeric_prefix(value: str) -> float | None:
    import re

    match = re.match(r"\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", value)
    return float(match.group(1)) if match else None


def _extract_contact_policy_attempts(stdout: str) -> list[dict]:
    import ast
    import re

    match = re.search(r"CONTACT_POLICY_AUDIT\|(\[.*\])", stdout, flags=re.DOTALL)
    if not match:
        return []
    try:
        parsed = ast.literal_eval(match.group(1))
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _render_field_heatmap_from_open_model(model_name: str, *, expression: str, filename: str) -> dict:
    """Render a non-spatial COMSOL field-value heatmap when headless image export is blank."""
    try:
        import numpy as np

        client = COMSOLClient.get_instance()
        handle = client.get_model(model_name)
        values = np.asarray(handle.mph_model.evaluate(expression), dtype=float).reshape(-1)
        values = values[np.isfinite(values)]
        if values.size == 0:
            return {"success": False, "error": f"No finite values for {expression}."}
        side = int(np.ceil(np.sqrt(values.size)))
        padded = np.full(side * side, np.nan)
        padded[:values.size] = values
        field = padded.reshape(side, side)
        low = float(np.nanpercentile(field, 2))
        high = float(np.nanpercentile(field, 98))
        if not high > low:
            low = float(np.nanmin(field))
            high = float(np.nanmax(field))
        if not high > low:
            high = low + 1.0
        normalized = np.nan_to_num((field - low) / (high - low), nan=0.0)
        normalized = np.clip(normalized, 0.0, 1.0)
        image = _resize_nearest(_colorize_heatmap(normalized), width=800, height=600)
        output = Path(filename).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        _write_rgb_png(output, image)
        return {
            "success": True,
            "model_name": model_name,
            "expression": expression,
            "plot_type": "field_value_heatmap",
            "filepath": str(output),
            "export_method": "numpy:comsol_field_heatmap",
            "fallback_for": "blank_headless_comsol_image_export",
            "native_geometry_surface_plot": False,
            "summary_note": (
                "Fallback heatmap rendered from solved COMSOL field values; it is not a COMSOL-native "
                "geometry surface plot."
            ),
        }
    except Exception as exc:
        return {"success": False, "error": f"Fallback heatmap failed: {exc}"}


def _colorize_heatmap(normalized):
    import numpy as np

    red = np.clip(255 * normalized, 0, 255)
    green = np.clip(255 * (1.0 - np.abs(normalized - 0.5) * 2.0), 0, 255)
    blue = np.clip(255 * (1.0 - normalized), 0, 255)
    return np.dstack([red, green, blue]).astype(np.uint8)


def _resize_nearest(image, *, width: int, height: int):
    import numpy as np

    rows = np.linspace(0, image.shape[0] - 1, height).astype(int)
    cols = np.linspace(0, image.shape[1] - 1, width).astype(int)
    return image[rows][:, cols]


def _write_rgb_png(path: Path, image) -> None:
    height, width, channels = image.shape
    if channels != 3:
        raise ValueError("Expected RGB image.")
    raw_rows = [b"\x00" + image[row].tobytes() for row in range(height)]
    compressed = zlib.compress(b"".join(raw_rows), level=9)
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(_png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
    png.extend(_png_chunk(b"IDAT", compressed))
    png.extend(_png_chunk(b"IEND", b""))
    path.write_bytes(bytes(png))


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    import binascii

    payload = kind + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", binascii.crc32(payload) & 0xFFFFFFFF)


if __name__ == "__main__":
    main()
