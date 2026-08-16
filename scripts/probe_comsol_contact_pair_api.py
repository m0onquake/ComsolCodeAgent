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
        "name": "named_box_selection_candidates",
        "code": BASE_GEOMETRY
        + """model.component('comp1').geom('geom1').feature('fin').set('action', 'assembly');
model.component('comp1').geom('geom1').run();
for selection_type in ['Box', 'Ball', 'Explicit']:
    tag = 'sel_' + selection_type.lower()
    try:
        sel = model.component('comp1').selection().create(tag, selection_type)
        output.write(selection_type + ': create_ok class=' + str(sel.getClass().getName()) + '\\n')
        for key, value in [
            ('entitydim', 1),
            ('xmin', '-1[mm]'),
            ('xmax', '1[mm]'),
            ('ymin', '-1[mm]'),
            ('ymax', '8[mm]'),
            ('condition', 'intersects'),
        ]:
            try:
                sel.set(key, value)
                output.write(selection_type + ': set_' + key + '_ok\\n')
            except Exception as error:
                output.write(selection_type + ': set_' + key + '_error=' + str(error) + '\\n')
        try:
            output.write(selection_type + ': entities=' + str(list(sel.entities())) + '\\n')
        except Exception as error:
            output.write(selection_type + ': entities_error=' + str(error) + '\\n')
    except Exception as error:
        output.write(selection_type + ': create_error=' + str(error) + '\\n')
model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
model.component('comp1').physics('solid').create('load_named_probe', 'BoundaryLoad', 1);
for call in ['named', 'set']:
    try:
        if call == 'named':
            model.component('comp1').physics('solid').feature('load_named_probe').selection().named('sel_box')
        else:
            model.component('comp1').physics('solid').feature('load_named_probe').selection().set([1])
        output.write('physics_selection_' + call + '_ok\\n')
    except Exception as error:
        output.write('physics_selection_' + call + '_error=' + str(error) + '\\n')
pair = model.component('comp1').pair().create('cp_named_probe', 'Contact');
pair.manualSelection(True);
pair.source().geom('geom1', 1);
pair.destination().geom('geom1', 1);
for side_name, side in [('source', pair.source()), ('destination', pair.destination())]:
    for call in ['named', 'set']:
        try:
            if call == 'named':
                side.named('sel_box')
            else:
                side.set([1])
            output.write('pair_' + side_name + '_' + call + '_ok\\n')
        except Exception as error:
            output.write('pair_' + side_name + '_' + call + '_error=' + str(error) + '\\n')
output.write('selection_tags=' + str(list(model.component('comp1').selection().tags())) + '\\n');
""",
    },
    {
        "name": "named_box_selection_3d_candidates",
        "code": """model.component().create('comp1', True);
model.component('comp1').geom().create('geom1', 3);
model.component('comp1').geom('geom1').lengthUnit('mm');
model.component('comp1').geom('geom1').create('left_cyl', 'Cylinder');
model.component('comp1').geom('geom1').feature('left_cyl').set('r', '4[mm]');
model.component('comp1').geom('geom1').feature('left_cyl').set('h', '8[mm]');
model.component('comp1').geom('geom1').feature('left_cyl').set('pos', ['-4[mm]', '0', '-4[mm]']);
model.component('comp1').geom('geom1').create('right_cyl', 'Cylinder');
model.component('comp1').geom('geom1').feature('right_cyl').set('r', '4[mm]');
model.component('comp1').geom('geom1').feature('right_cyl').set('h', '8[mm]');
model.component('comp1').geom('geom1').feature('right_cyl').set('pos', ['4[mm]', '0', '-4[mm]']);
model.component('comp1').geom('geom1').feature('fin').set('action', 'assembly');
model.component('comp1').geom('geom1').run();
sel_left = model.component('comp1').selection().create('sel_left_contact', 'Box');
for key, value in [('entitydim', '2'), ('xmin', '-8[mm]'), ('xmax', '0.5[mm]'), ('ymin', '-5[mm]'), ('ymax', '5[mm]'), ('zmin', '-5[mm]'), ('zmax', '5[mm]'), ('condition', 'intersects')]:
    try:
        sel_left.set(key, value)
        output.write('sel_left_set_' + key + '_ok\\n')
    except Exception as error:
        output.write('sel_left_set_' + key + '_error=' + str(error) + '\\n')
sel_right = model.component('comp1').selection().create('sel_right_contact', 'Box');
for key, value in [('entitydim', '2'), ('xmin', '-0.5[mm]'), ('xmax', '8[mm]'), ('ymin', '-5[mm]'), ('ymax', '5[mm]'), ('zmin', '-5[mm]'), ('zmax', '5[mm]'), ('condition', 'intersects')]:
    try:
        sel_right.set(key, value)
        output.write('sel_right_set_' + key + '_ok\\n')
    except Exception as error:
        output.write('sel_right_set_' + key + '_error=' + str(error) + '\\n')
try:
    output.write('sel_left_entities=' + str(list(sel_left.entities())) + '\\n')
    output.write('sel_right_entities=' + str(list(sel_right.entities())) + '\\n')
except Exception as error:
    output.write('selection_entities_error=' + str(error) + '\\n')
model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
model.component('comp1').physics('solid').create('load_named_probe', 'BoundaryLoad', 2);
try:
    model.component('comp1').physics('solid').feature('load_named_probe').selection().named('sel_left_contact')
    output.write('physics_selection_named_ok\\n')
except Exception as error:
    output.write('physics_selection_named_error=' + str(error) + '\\n')
pair = model.component('comp1').pair().create('cp_named_probe', 'Contact');
pair.manualSelection(True);
pair.source().geom('geom1', 2);
pair.destination().geom('geom1', 2);
try:
    pair.source().named('sel_left_contact')
    output.write('pair_source_named_ok\\n')
except Exception as error:
    output.write('pair_source_named_error=' + str(error) + '\\n')
try:
    pair.destination().named('sel_right_contact')
    output.write('pair_destination_named_ok\\n')
except Exception as error:
    output.write('pair_destination_named_error=' + str(error) + '\\n')
output.write('selection_tags=' + str(list(model.component('comp1').selection().tags())) + '\\n');
""",
    },
    {
        "name": "numerical_named_selection_3d_candidates",
        "code": """model.param().set('E', '210[GPa]');
model.param().set('nu', '0.3');
model.component().create('comp1', True);
model.component('comp1').geom().create('geom1', 3);
model.component('comp1').geom('geom1').lengthUnit('mm');
model.component('comp1').geom('geom1').create('blk1', 'Block');
model.component('comp1').geom('geom1').feature('blk1').set('size', ['2[mm]', '2[mm]', '2[mm]']);
model.component('comp1').geom('geom1').run();
sel = model.component('comp1').selection().create('sel_blk_body', 'Box');
sel.set('entitydim', '3');
sel.set('xmin', '-1[mm]');
sel.set('xmax', '3[mm]');
sel.set('ymin', '-1[mm]');
sel.set('ymax', '3[mm]');
sel.set('zmin', '-1[mm]');
sel.set('zmax', '3[mm]');
sel.set('condition', 'intersects');
output.write('selection_entities=' + str(list(sel.entities())) + '\\n');
model.component('comp1').material().create('mat1', 'Common');
model.component('comp1').material('mat1').propertyGroup('def').set('youngsmodulus', 'E');
model.component('comp1').material('mat1').propertyGroup('def').set('poissonsratio', 'nu');
model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
model.result().numerical().create('probe_named_method', 'MaxVolume');
model.result().numerical('probe_named_method').set('expr', 'solid.mises');
try:
    model.result().numerical('probe_named_method').selection().named('sel_blk_body');
    output.write('numerical_selection_named_ok\\n');
except Exception as error:
    output.write('numerical_selection_named_error=' + str(error) + '\\n');
model.result().numerical().create('probe_set_method', 'MaxVolume');
model.result().numerical('probe_set_method').set('expr', 'solid.mises');
try:
    model.result().numerical('probe_set_method').selection().set(list(sel.entities()));
    output.write('numerical_selection_set_ok\\n');
except Exception as error:
    output.write('numerical_selection_set_error=' + str(error) + '\\n');
model.result().numerical().create('probe_selection_prop_method', 'MaxVolume');
model.result().numerical('probe_selection_prop_method').set('expr', 'solid.mises');
try:
    model.result().numerical('probe_selection_prop_method').set('selection', 'sel_blk_body');
    output.write('numerical_set_selection_prop_ok\\n');
except Exception as error:
    output.write('numerical_set_selection_prop_error=' + str(error) + '\\n');
model.result().numerical().create('probe_maximumobj_method', 'MaxVolume');
model.result().numerical('probe_maximumobj_method').set('expr', 'solid.mises');
for value in ['sel_blk_body', ['sel_blk_body'], 'blk1', ['blk1']]:
    try:
        model.result().numerical('probe_maximumobj_method').set('maximumobj', value);
        output.write('numerical_set_maximumobj_' + str(value) + '_ok\\n');
    except Exception as error:
        output.write('numerical_set_maximumobj_' + str(value) + '_error=' + str(error) + '\\n');
try:
    output.write('probe_named_props=' + str(list(model.result().numerical('probe_named_method').properties())) + '\\n');
except Exception as error:
    output.write('probe_props_error=' + str(error) + '\\n');
try:
    maxop = model.component('comp1').cpl().create('maxop_sel_body', 'Maximum');
    output.write('cpl_max_create_ok\\n');
    try:
        maxop.selection().named('sel_blk_body');
        output.write('cpl_max_selection_named_ok\\n');
    except Exception as error:
        output.write('cpl_max_selection_named_error=' + str(error) + '\\n');
    try:
        maxop.selection().set(list(sel.entities()));
        output.write('cpl_max_selection_set_ok\\n');
    except Exception as error:
        output.write('cpl_max_selection_set_error=' + str(error) + '\\n');
    model.result().numerical().create('probe_cpl_eval_method', 'EvalGlobal');
    model.result().numerical('probe_cpl_eval_method').set('expr', 'maxop_sel_body(solid.mises)');
    output.write('cpl_evalglobal_create_ok\\n');
except Exception as error:
    output.write('cpl_max_create_error=' + str(error) + '\\n');
""",
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
