"""Run a generated-code fallback smoke without relying on a saved template.

The script simulates the P7 path after an LLM has produced raw COMSOL Java/API
setup code: plan the generated-code context, validate the raw code, run it on a
new model, solve/evaluate/plot, and optionally promote the raw code to a
reusable template.
"""

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
from comsol_agent.tools.comsol.evaluate import comsol_plot
from comsol_agent.tools.comsol.model_ops import comsol_close_model
from comsol_agent.tools.comsol.solve import comsol_evaluate, comsol_solve
from comsol_agent.tools.simulation import (
    simulation_plan_generated_code,
    simulation_run_template,
    simulation_save_template,
    simulation_validate_template,
)


GENERATED_STRUCTURAL_CODE = """model.param().set('L', '50[mm]');
model.param().set('H', '10[mm]');
model.param().set('E_steel', '210[GPa]');
model.param().set('nu_steel', '0.30');
model.param().set('rho_steel', '7850[kg/m^3]');
model.param().set('edge_load', '2[MPa]');
model.component().create('comp1', True);
model.component('comp1').geom().create('geom1', 2);
model.component('comp1').geom('geom1').lengthUnit('mm');
model.component('comp1').geom('geom1').create('plate', 'Rectangle');
model.component('comp1').geom('geom1').feature('plate').set('size', ['L', 'H']);
model.component('comp1').geom('geom1').feature('plate').set('base', 'center');
model.component('comp1').geom('geom1').run();
model.component('comp1').material().create('mat_steel', 'Common');
model.component('comp1').material('mat_steel').label('Generated steel');
model.component('comp1').material('mat_steel').propertyGroup('def').set('youngsmodulus', 'E_steel');
model.component('comp1').material('mat_steel').propertyGroup('def').set('poissonsratio', 'nu_steel');
model.component('comp1').material('mat_steel').propertyGroup('def').set('density', 'rho_steel');
model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
model.component('comp1').physics('solid').create('fix_left', 'Fixed', 1);
model.component('comp1').physics('solid').feature('fix_left').selection().set([1]);
model.component('comp1').physics('solid').create('load_right', 'BoundaryLoad', 1);
model.component('comp1').physics('solid').feature('load_right').selection().set([4]);
model.component('comp1').physics('solid').feature('load_right').set('FperArea', ['edge_load', '0', '0']);
model.component('comp1').mesh().create('mesh1');
model.component('comp1').mesh('mesh1').autoMeshSize(4);
model.study().create('std1');
model.study('std1').create('stat', 'Stationary');
model.study('std1').feature('stat').set('activate', ['solid', 'on']);
model.result().create('pg_generated_stress', 'PlotGroup2D');
model.result('pg_generated_stress').label('Generated von Mises stress');
model.result('pg_generated_stress').create('surf_stress', 'Surface');
model.result('pg_generated_stress').feature('surf_stress').set('expr', 'solid.mises');
output.write('Generated structural plate model created with Solid Mechanics, mesh, stationary study, and von Mises plot group.');
"""


GENERATED_PARAMS = {
    "geometry": "2D rectangular steel plate, 50[mm] by 10[mm]",
    "physics": "Solid Mechanics",
    "material": "steel, E=210[GPa], nu=0.30",
    "boundary_conditions": "left boundary fixed, right boundary horizontal traction",
    "study_type": "stationary",
    "outputs": "solid.mises and von Mises stress PNG",
    "L": "50[mm]",
    "H": "10[mm]",
    "edge_load": "2[MPa]",
}


GENERATED_CODE_PARAMS = {
    "L": "50[mm]",
    "H": "10[mm]",
    "E_steel": "210[GPa]",
    "nu_steel": "0.30",
    "rho_steel": "7850[kg/m^3]",
    "edge_load": "2[MPa]",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a generated COMSOL code fallback smoke.")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--model-name", default="generated_code_structural_smoke")
    parser.add_argument("--archive-path", default="runtime_smoke/generated_code_fallback.sqlite3")
    parser.add_argument("--artifact-dir", default="runtime_smoke/generated_code_fallback/template_runs")
    parser.add_argument("--plot-path", default="runtime_smoke/generated_code_fallback/von_mises.png")
    parser.add_argument("--template-name", default="generated_structural_plate_seed")
    parser.add_argument("--skip-comsol", action="store_true", help="Only plan and validate the raw generated code.")
    args = parser.parse_args()

    plan = simulation_plan_generated_code(
        user_request=(
            "Generate a custom COMSOL structural simulation for a rectangular steel plate "
            "with a fixed edge, a loaded edge, stationary solve, and von Mises stress plot."
        ),
        known_params=GENERATED_PARAMS,
        domain="structural",
        allow_defaults=False,
        archive_path=args.archive_path,
    )
    validation = simulation_validate_template(
        name=args.template_name,
        java_code=GENERATED_STRUCTURAL_CODE,
        params=GENERATED_CODE_PARAMS,
        archive_path=args.archive_path,
    )
    result: dict = {"plan": _compact_plan(plan), "validation": validation}
    if args.skip_comsol:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    config = load_config()
    client = COMSOLClient.get_instance()
    model_name = args.model_name
    try:
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        run = simulation_run_template(
            name=args.template_name,
            java_code=GENERATED_STRUCTURAL_CODE,
            params=GENERATED_CODE_PARAMS,
            execution_context={
                "workflow": "generated_code_structural_smoke",
                "draft_quality": validation,
                "repair_history": [],
                "require_free_generated_code": False,
            },
            create_model_name=model_name,
            close_model=False,
            artifact_dir=args.artifact_dir,
            artifact_name="generated_code_structural_smoke",
            archive_path=args.archive_path,
        )
        result["run"] = _compact_run(run)
        if run.get("success"):
            solve = comsol_solve(model_name)
            evaluation = comsol_evaluate(model_name, "solid.mises") if solve.get("success") else None
            plot = (
                comsol_plot(model_name, expression="solid.mises", filename=args.plot_path)
                if solve.get("success")
                else None
            )
            saved_template = simulation_save_template(
                name=args.template_name,
                java_code=GENERATED_STRUCTURAL_CODE,
                domain="structural",
                params=GENERATED_CODE_PARAMS,
                archive_path=args.archive_path,
            )
            result.update(
                {
                    "solve": _compact_result(solve),
                    "evaluation": _compact_result(evaluation),
                    "plot": plot,
                    "saved_template": {
                        "success": saved_template.get("success"),
                        "template": (saved_template.get("template") or {}).get("name"),
                        "archive_path": saved_template.get("archive_path"),
                    },
                }
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        if model_name in client.models:
            print(json.dumps({"close": comsol_close_model(model_name, save=False)}, ensure_ascii=False, indent=2))
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def _compact_plan(plan: dict) -> dict:
    return {
        "success": plan.get("success"),
        "mode": plan.get("mode"),
        "ready_to_generate": plan.get("ready_to_generate"),
        "domain": plan.get("domain"),
        "missing_decisions": plan.get("missing_decisions"),
        "retrieval_count": (plan.get("retrieval") or {}).get("count"),
        "candidate_count": (plan.get("template_policy") or {}).get("candidate_count"),
        "next_tool_chain": plan.get("next_tool_chain"),
    }


def _compact_run(run: dict) -> dict:
    return {
        "success": run.get("success"),
        "template_name": run.get("template_name"),
        "model_name": run.get("model_name"),
        "run_id": ((run.get("artifacts") or {}).get("run_id")),
        "json_path": ((run.get("artifacts") or {}).get("json_path")),
        "execution": {
            "success": (run.get("execution") or {}).get("success"),
            "error_type": (run.get("execution") or {}).get("error_type"),
            "error": (run.get("execution") or {}).get("error"),
        },
    }


def _compact_result(result: dict | None) -> dict | None:
    if result is None:
        return None
    return {
        key: result.get(key)
        for key in ("success", "error", "elapsed_seconds", "status", "expression", "statistics", "value")
        if key in result
    }


if __name__ == "__main__":
    main()
