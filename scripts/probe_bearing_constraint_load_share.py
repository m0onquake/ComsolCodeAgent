"""Audit which artificial bearing constraints carry the applied X load in a solved MPH."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.cli.config import load_config
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.tools.comsol.model_ops import comsol_close_model, comsol_load_model
from comsol_agent.tools.comsol.solve import comsol_execute_java
from scripts.run_agent_3d_bearing_full_demo import (
    VERIFIED_ROLLER_COUNT,
    _evaluate_global_expression_via_java,
    _evaluate_surface_integral_expression_on_entities_via_java,
    _evaluate_surface_integral_expression_via_java,
    _get_selection_entities_via_java,
)


def _latest_max_volume(
    model_name: str,
    expression: str,
    tag: str,
    selection_name: str | None = None,
) -> dict[str, object]:
    marker = f"LATEST_MAX_VOLUME|tag={tag}|"
    code = f"""
import json
try:
    if {tag!r} in [str(item) for item in list(model.result().numerical().tags())]:
        model.result().numerical().remove({tag!r})
    datasets = [str(item) for item in list(model.result().dataset().tags())]
    dataset = datasets[-1]
    model.result().numerical().create({tag!r}, 'MaxVolume')
    numerical = model.result().numerical({tag!r})
    numerical.set('expr', {expression!r})
    numerical.set('data', dataset)
    if {selection_name!r}:
        numerical.selection().named({selection_name!r})
    raw = numerical.getReal()
    values = []
    def flatten(value):
        try:
            items = list(value)
        except Exception:
            items = [value]
        for item in items:
            try:
                nested = list(item)
            except Exception:
                nested = None
            if nested is not None:
                flatten(nested)
            else:
                try:
                    values.append(float(item))
                except Exception:
                    pass
    globals()['flatten'] = flatten
    flatten(raw)
    output.write({marker!r} + json.dumps({{'success': True, 'dataset': dataset, 'selection': {selection_name!r}, 'values': values, 'value': values[-1] if values else None}}) + '\\n')
except Exception as error:
    output.write({marker!r} + json.dumps({{'success': False, 'error': str(error)}}) + '\\n')
"""
    execution = comsol_execute_java(code, model_name=model_name)
    stdout = execution.get("stdout") or execution.get("output") or ""
    if marker not in stdout:
        return {"success": False, "error": execution.get("error") or "missing marker"}
    return json.loads(stdout.split(marker, 1)[1].splitlines()[0])


def _latest_selection_max(
    model_name: str,
    expression: str,
    operator_tag: str,
    selection_name: str | None = None,
) -> dict[str, object]:
    code = f"""
try:
    if {operator_tag!r} in [str(item) for item in list(model.component('comp1').cpl().tags())]:
        model.component('comp1').cpl().remove({operator_tag!r})
    model.component('comp1').cpl().create({operator_tag!r}, 'Maximum')
    operator = model.component('comp1').cpl({operator_tag!r})
    if {selection_name!r}:
        operator.selection().named({selection_name!r})
    else:
        operator.selection().all()
    output.write('LATEST_SELECTION_MAX_SETUP|tag=' + {operator_tag!r} + '|success=true\\n')
except Exception as error:
    output.write('LATEST_SELECTION_MAX_SETUP|tag=' + {operator_tag!r} + '|success=false|error=' + str(error) + '\\n')
    raise
"""
    setup = comsol_execute_java(code, model_name=model_name)
    if not setup.get("success"):
        return {"success": False, "selection": selection_name, "error": setup.get("error")}
    result = _evaluate_global_expression_via_java(
        model_name,
        f"{operator_tag}({expression})",
        tag=f"eval_{operator_tag}",
        result_index="last",
        dataset_tag="latest",
    )
    result["selection"] = selection_name
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mph")
    parser.add_argument("--output", required=True)
    parser.add_argument("--cores", type=int, default=1)
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    config = load_config()
    client = COMSOLClient.get_instance()
    model_name = None
    report: dict[str, object] = {"mph": args.mph, "dataset_policy": "latest", "probes": []}
    try:
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        loaded = comsol_load_model(args.mph)
        if not loaded.get("success"):
            raise RuntimeError(str(loaded.get("error") or "failed to load MPH"))
        model_name = str(loaded["model_name"])
        probe_specs = [
            ("outer_fixed_reaction_x", "sel_outer_support_surface", "solid.RFx"),
            ("inner_bore_constraint_reaction_x", "sel_inner_bore_load_surface", "solid.RFx"),
            ("cage_fixed_reaction_x", "geom1_cage_bnd", "solid.RFx"),
            (
                "weak_inner_guidance_force_x",
                "geom1_inner_ring_bnd",
                "-weak_inner_guidance_k*u",
            ),
        ]
        probe_specs.extend(
            (
                f"weak_roller_{roller}_foundation_force_x",
                f"geom1_roller_{roller}_bnd",
                "-weak_roller_foundation_k*u",
            )
            for roller in range(1, VERIFIED_ROLLER_COUNT + 1)
        )
        probes = []
        for index, (label, selection, expression) in enumerate(probe_specs, start=1):
            result = _evaluate_surface_integral_expression_via_java(
                model_name,
                expression,
                selection_name=selection,
                tag=f"constraint_share_{index}",
                result_index="last",
                dataset_tag="latest",
            )
            probes.append(
                {
                    "label": label,
                    "selection": selection,
                    "expression": expression,
                    "success": bool(result.get("success")),
                    "value_n": result.get("value"),
                    "selected_dataset": result.get("selected_dataset"),
                    "error": result.get("error"),
                }
            )
        report["probes"] = probes
        load_entities = _get_selection_entities_via_java(
            model_name,
            selection_name="sel_inner_bore_load_surface",
        ).get("entities") or []
        report["inner_bore_load_entity_areas_m2"] = [
            {
                "entity": int(entity),
                "area_m2": _evaluate_surface_integral_expression_on_entities_via_java(
                    model_name,
                    "1",
                    entities=[int(entity)],
                    tag=f"inner_bore_area_{entity}",
                ).get("value"),
            }
            for entity in load_entities
        ]
        roller_contact_loads = []
        for roller in range(1, VERIFIED_ROLLER_COUNT + 1):
            row = {"roller": roller}
            for side in ("inner", "outer"):
                pair_tag = f"cp_roller_{roller}_{side}_raceway"
                evaluation = _evaluate_surface_integral_expression_via_java(
                    model_name,
                    f"abs(solid.Tn_{pair_tag})",
                    selection_name=f"sel_{side}_raceway_{roller}_contact",
                    tag=f"roller_{roller}_{side}_normal_load",
                    result_index="last",
                    dataset_tag="latest",
                )
                row[f"{side}_normal_load_n"] = evaluation.get("value")
                row[f"{side}_selected_dataset"] = evaluation.get("selected_dataset")
                row[f"{side}_success"] = bool(evaluation.get("success"))
            roller_contact_loads.append(row)
        report["roller_contact_loads"] = roller_contact_loads
        report["global_max_von_mises"] = _latest_selection_max(
            model_name, "solid.mises", "maxop_latest_global_mises"
        )
        report["global_max_displacement"] = _latest_selection_max(
            model_name, "solid.disp", "maxop_latest_global_disp"
        )
        report["component_max_von_mises"] = {
            "inner_ring": _latest_selection_max(
                model_name, "solid.mises", "maxop_latest_inner_ring", "geom1_inner_ring_dom"
            ),
            "outer_ring": _latest_selection_max(
                model_name, "solid.mises", "maxop_latest_outer_ring", "geom1_outer_ring_dom"
            ),
            "cage": _latest_selection_max(
                model_name, "solid.mises", "maxop_latest_cage", "geom1_cage_dom"
            ),
        }
        report["inner_ring_max_von_mises"] = _evaluate_global_expression_via_java(
            model_name,
            "maxop_inner_ring(solid.mises)",
            tag="latest_inner_ring_max_mises",
            result_index="last",
            dataset_tag="latest",
        )
        report["cage_max_von_mises"] = _evaluate_global_expression_via_java(
            model_name,
            "maxop_cage(solid.mises)",
            tag="latest_cage_max_mises",
            result_index="last",
            dataset_tag="latest",
        )
        report["roller_max_von_mises"] = [
            {
                "roller": roller,
                **_latest_selection_max(
                    model_name,
                    "solid.mises",
                    f"maxop_latest_roller_{roller}",
                    f"geom1_roller_{roller}_dom",
                ),
            }
            for roller in range(1, VERIFIED_ROLLER_COUNT + 1)
        ]
        report["weak_roller_foundation_sum_x_n"] = sum(
            float(item["value_n"])
            for item in probes
            if item["label"].startswith("weak_roller_") and item.get("value_n") is not None
        )
        report["success"] = True
    except Exception as exc:
        report["success"] = False
        report["error"] = str(exc)
    finally:
        if model_name:
            comsol_close_model(model_name, save=False)
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
