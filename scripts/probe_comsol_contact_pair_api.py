"""Probe COMSOL 6.x Java/API calls for 2D contact-pair setup.

This script is intentionally diagnostic: it creates fresh throwaway models and
tries small API variants so the project can move from the current pressure-load
smoke case toward a real contact-pair model without guessing API calls.
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
from comsol_agent.tools.comsol.model_ops import comsol_close_model, comsol_create_model
from comsol_agent.tools.comsol.solve import (
    comsol_evaluate,
    comsol_execute_java,
    comsol_get_model_summary,
    comsol_solve,
)


BASE_GEOMETRY = """model.param().set('ball_diameter', '7.94[mm]');
model.param().set('contact_interference', '2[um]');
model.param().set('contact_span', '12[mm]');
model.param().set('raceway_height', '6[mm]');
model.component().create('comp1', True);
model.component('comp1').geom().create('geom1', 2);
model.component('comp1').geom('geom1').lengthUnit('mm');
model.component('comp1').geom('geom1').create('raceway', 'Rectangle');
model.component('comp1').geom('geom1').feature('raceway').set('size', ['contact_span', 'raceway_height']);
model.component('comp1').geom('geom1').feature('raceway').set('base', 'center');
model.component('comp1').geom('geom1').feature('raceway').set('pos', ['0', '-raceway_height/2']);
model.component('comp1').geom('geom1').create('ball', 'Circle');
model.component('comp1').geom('geom1').feature('ball').set('r', 'ball_diameter/2');
model.component('comp1').geom('geom1').feature('ball').set('pos', ['0', 'ball_diameter/2-contact_interference']);
"""


PAIR_TYPE_PROBE_CODE = BASE_GEOMETRY + """model.component('comp1').geom('geom1').run();
candidate_types = ['Contact', 'Identity', 'ContactPair', 'IdentityPair', 'Pair', 'contact', 'identity']
for candidate in candidate_types:
    tag = 'pair_' + candidate.lower()
    try:
        pair = model.component('comp1').pair().create(tag, candidate)
        output.write(candidate + ': create_ok type=' + str(pair.type()) + ' tags=' + str(list(model.component('comp1').pair().tags())) + '\\n')
        try:
            output.write(candidate + ': source_class=' + str(pair.source().getClass().getName()) + ' dest_class=' + str(pair.destination().getClass().getName()) + '\\n')
        except Exception as detail_error:
            output.write(candidate + ': selection_detail_error=' + str(detail_error) + '\\n')
    except Exception as error:
        output.write(candidate + ': create_error=' + str(error) + '\\n')
"""


MANUAL_PAIR_CONTACT_PROBE_CODE = BASE_GEOMETRY + """model.component('comp1').geom('geom1').run();
model.component('comp1').material().create('mat_steel', 'Common');
model.component('comp1').material('mat_steel').propertyGroup('def').set('youngsmodulus', '210[GPa]');
model.component('comp1').material('mat_steel').propertyGroup('def').set('poissonsratio', '0.30');
model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
pair = model.component('comp1').pair().create('cp1', 'Contact')
pair.manualSelection(True)
output.write('pair_type=' + str(pair.type()) + ' manual=' + str(pair.manualSelection()) + '\\n')
try:
    pair.source().geom('geom1', 1)
    output.write('src_geom_boundary: ok\\n')
except Exception as error:
    output.write('src_geom_boundary: error=' + str(error) + '\\n')
try:
    pair.destination().geom('geom1', 1)
    output.write('dst_geom_boundary: ok\\n')
except Exception as error:
    output.write('dst_geom_boundary: error=' + str(error) + '\\n')
try:
    pair.source().set([5])
    output.write('src_set_ball_boundary_5: ok entities=' + str(list(pair.source().entities())) + '\\n')
except Exception as error:
    output.write('src_set_ball_boundary_5: error=' + str(error) + '\\n')
try:
    pair.destination().set([3])
    output.write('dst_set_race_boundary_3: ok entities=' + str(list(pair.destination().entities())) + '\\n')
except Exception as error:
    output.write('dst_set_race_boundary_3: error=' + str(error) + '\\n')
output.write('pair_tags=' + str(list(model.component('comp1').pair().tags())) + '\\n')
contact = model.component('comp1').physics('solid').create('contact_probe', 'Contact', 1)
for key, value in [('pairs', ['cp1']), ('pairs', 'cp1'), ('pair', 'cp1'), ('Pair', 'cp1'), ('contactPair', 'cp1'), ('pairname', 'cp1')]:
    try:
        contact.set(key, value)
        output.write('contact_set_' + key + ': ok\\n')
    except Exception as error:
        output.write('contact_set_' + key + ': error=' + str(error) + '\\n')
try:
    output.write('contact_props=' + str(list(contact.properties())) + '\\n')
except Exception as error:
    output.write('contact_props_error=' + str(error) + '\\n')
output.write('physics_features=' + str(list(model.component('comp1').physics('solid').feature().tags())) + '\\n')
"""


PROBES = [
    {
        "name": "default_union_tags",
        "code": BASE_GEOMETRY
        + """model.component('comp1').geom('geom1').run();
output.write('geom_tags=' + str(list(model.component('comp1').geom('geom1').feature().tags())) + '\\n');
output.write('pair_tags=' + str(list(model.component('comp1').pair().tags())) + '\\n');
output.write('selection_tags=' + str(list(model.component('comp1').selection().tags())) + '\\n');
""",
    },
    {
        "name": "fin_action_assembly_createpairs",
        "code": BASE_GEOMETRY
        + """model.component('comp1').geom('geom1').feature('fin').set('action', 'assembly');
model.component('comp1').geom('geom1').feature('fin').set('createpairs', 'on');
model.component('comp1').geom('geom1').run();
output.write('geom_tags=' + str(list(model.component('comp1').geom('geom1').feature().tags())) + '\\n');
output.write('pair_tags=' + str(list(model.component('comp1').pair().tags())) + '\\n');
output.write('selection_tags=' + str(list(model.component('comp1').selection().tags())) + '\\n');
""",
    },
    {
        "name": "solid_contact_feature_after_union",
        "code": BASE_GEOMETRY
        + """model.component('comp1').geom('geom1').run();
model.component('comp1').material().create('mat_steel', 'Common');
model.component('comp1').material('mat_steel').propertyGroup('def').set('youngsmodulus', '210[GPa]');
model.component('comp1').material('mat_steel').propertyGroup('def').set('poissonsratio', '0.30');
model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
model.component('comp1').physics('solid').create('contact_probe', 'Contact', 1);
output.write('physics_features=' + str(list(model.component('comp1').physics('solid').feature().tags())) + '\\n');
""",
    },
    {
        "name": "solid_pair_contact_feature_after_assembly",
        "code": BASE_GEOMETRY
        + """model.component('comp1').geom('geom1').feature('fin').set('action', 'assembly');
model.component('comp1').geom('geom1').feature('fin').set('createpairs', 'on');
model.component('comp1').geom('geom1').run();
model.component('comp1').material().create('mat_steel', 'Common');
model.component('comp1').material('mat_steel').propertyGroup('def').set('youngsmodulus', '210[GPa]');
model.component('comp1').material('mat_steel').propertyGroup('def').set('poissonsratio', '0.30');
model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
output.write('pair_tags=' + str(list(model.component('comp1').pair().tags())) + '\\n');
model.component('comp1').physics('solid').create('contact_probe', 'Contact', 2);
output.write('physics_features=' + str(list(model.component('comp1').physics('solid').feature().tags())) + '\\n');
""",
    },
    {
        "name": "pair_type_candidates",
        "code": PAIR_TYPE_PROBE_CODE,
    },
    {
        "name": "manual_pair_contact_feature_properties",
        "code": MANUAL_PAIR_CONTACT_PROBE_CODE,
    },
    {
        "name": "solid_contact_feature_solve_smoke",
        "solve": True,
        "code": BASE_GEOMETRY
        + """model.param().set('bearing_width', '15[mm]');
model.param().set('radial_load', '1000[N]');
model.param().set('load_share_factor', '0.22');
model.param().set('contact_pressure_guess', 'radial_load*load_share_factor/(bearing_width*ball_diameter)');
model.component('comp1').geom('geom1').run();
model.component('comp1').material().create('mat_steel', 'Common');
model.component('comp1').material('mat_steel').propertyGroup('def').set('youngsmodulus', '210[GPa]');
model.component('comp1').material('mat_steel').propertyGroup('def').set('poissonsratio', '0.30');
model.component('comp1').material('mat_steel').propertyGroup('def').set('density', '7850[kg/m^3]');
model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
model.component('comp1').physics('solid').create('fix_race', 'Fixed', 1);
model.component('comp1').physics('solid').feature('fix_race').selection().set([2]);
pair = model.component('comp1').pair().create('cp1', 'Contact');
pair.manualSelection(True);
pair.source().geom('geom1', 1);
pair.destination().geom('geom1', 1);
pair.source().set([5]);
pair.destination().set([3]);
model.component('comp1').physics('solid').create('contact_probe', 'Contact', 1);
model.component('comp1').physics('solid').feature('contact_probe').set('pairs', ['cp1']);
model.component('comp1').physics('solid').create('ball_load', 'BoundaryLoad', 1);
model.component('comp1').physics('solid').feature('ball_load').selection().all();
model.component('comp1').physics('solid').feature('ball_load').set('FperArea', ['0', '-contact_pressure_guess', '0']);
model.component('comp1').mesh().create('mesh1');
model.component('comp1').mesh('mesh1').autoMeshSize(3);
model.study().create('std1');
model.study('std1').create('stat', 'Stationary');
model.study('std1').feature('stat').set('activate', ['solid', 'on']);
output.write('pair_source=' + str(list(pair.source().entities())) + ' pair_destination=' + str(list(pair.destination().entities())) + '\\n');
output.write('physics_features=' + str(list(model.component('comp1').physics('solid').feature().tags())) + '\\n');
""",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe COMSOL contact-pair API variants.")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--only", default=None, help="Optional probe name to run.")
    args = parser.parse_args()

    config = load_config()
    client = COMSOLClient.get_instance()
    results = []
    try:
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        for probe in PROBES:
            if args.only and probe["name"] != args.only:
                continue
            model_name = f"contact_probe_{probe['name']}"
            create_result = comsol_create_model(model_name)
            if not create_result.get("success"):
                results.append({"name": probe["name"], "create": create_result})
                continue
            actual_model = create_result["model_name"]
            execution = comsol_execute_java(probe["code"], model_name=actual_model)
            solve = comsol_solve(actual_model) if probe.get("solve") and execution.get("success") else None
            evaluation = (
                comsol_evaluate(actual_model, "solid.mises")
                if solve and solve.get("success")
                else None
            )
            summary = comsol_get_model_summary(actual_model)
            close = comsol_close_model(actual_model, save=False)
            results.append({
                "name": probe["name"],
                "create": create_result,
                "execution": _compact_execution(execution),
                "solve": _compact_result(solve),
                "evaluation": _compact_result(evaluation),
                "summary": summary.get("summary") if summary.get("success") else summary,
                "close": close,
            })
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    finally:
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def _compact_execution(result: dict) -> dict:
    return {
        "success": result.get("success"),
        "stdout": result.get("stdout"),
        "error": result.get("error"),
        "exception_type": result.get("exception_type"),
        "error_type": result.get("error_type"),
    }


def _compact_result(result: dict | None) -> dict | None:
    if result is None:
        return None
    return {
        key: result.get(key)
        for key in (
            "success",
            "error",
            "study",
            "elapsed_seconds",
            "status",
            "expression",
            "statistics",
            "value",
        )
        if key in result
    }


if __name__ == "__main__":
    main()
