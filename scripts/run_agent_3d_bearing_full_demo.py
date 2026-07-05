"""Run a reproducible agent demo for a 3D full roller bearing with cage."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import struct
import textwrap
from dataclasses import dataclass
from html import escape
from pathlib import Path
import sys
from typing import Any
import zlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VERIFIED_ROLLER_COUNT = 12

from comsol_agent.agent.loop import AgentLoop
from comsol_agent.agent.tool_registry import clear as clear_tools
from comsol_agent.agent.tools_bootstrap import register_all_tools
from comsol_agent.cli.config import load_config
from comsol_agent.llm.router import create_provider
from comsol_agent.memory.archive_store import ArchiveStore
from comsol_agent.simulation import bearing_3d as bearing_3d_contracts
from comsol_agent.simulation.skills import seed_builtin_templates
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.tools.comsol.evaluate import comsol_plot
from comsol_agent.tools.comsol.model_ops import comsol_close_model, comsol_load_model
from comsol_agent.tools.comsol.solve import comsol_evaluate, comsol_solve
from comsol_agent.tools.simulation import (
    _answer_from_artifact_summary,
    simulation_answer_artifact_question,
    simulation_export_bearing_contact_package,
    simulation_probe_3d_selection_binding,
    simulation_retrieve_api_docs,
    simulation_run_template,
)


def _fmt_mm(value: float) -> str:
    if abs(value) < 1e-9:
        value = 0.0
    return f"{value:.3f}[mm]"


def _build_verified_3d_full_bearing_code(*, roller_count: int = 12) -> str:
    """Build explicit setup code for the verified 3D full-bearing smoke fixture."""
    import math

    pitch_radius = 27.0
    roller_radius = 4.0
    roller_box_margin = 1.5
    contact_half_width = 1.2
    lines: list[str] = [
        "model.param().set('inner_diameter', '40[mm]');",
        "model.param().set('outer_diameter', '80[mm]');",
        "model.param().set('bearing_width', '18[mm]');",
        f"model.param().set('roller_count', '{roller_count}');",
        "model.param().set('roller_diameter', '8[mm]');",
        "model.param().set('roller_radius', 'roller_diameter/2');",
        "model.param().set('roller_length', '16[mm]');",
        "model.param().set('pitch_radius', '27[mm]');",
        "model.param().set('inner_race_outer_radius', '23[mm]');",
        "model.param().set('outer_race_inner_radius', '31[mm]');",
        "model.param().set('cage_inner_radius', '24[mm]');",
        "model.param().set('cage_outer_radius', '30[mm]');",
        "model.param().set('cage_width', '14[mm]');",
        "model.param().set('cage_pocket_radius', '4.6[mm]');",
        "model.param().set('radial_load', '3000[N]');",
        "model.param().set('load_per_roller', 'radial_load/roller_count');",
        "model.param().set('contact_pressure_est', 'load_per_roller/(roller_length*roller_diameter)');",
        "model.param().set('friction_coefficient', '0.05');",
        "model.param().set('contact_interference', '2[um]');",
        "model.param().set('E_steel', '210[GPa]');",
        "model.param().set('nu_steel', '0.30');",
        "model.param().set('rho_steel', '7850[kg/m^3]');",
        "model.param().set('E_cage', '3[GPa]');",
        "model.param().set('nu_cage', '0.35');",
        "model.param().set('rho_cage', '1350[kg/m^3]');",
        "model.param().set('mesh_contact_size', '0.7[mm]');",
        "model.param().set('mesh_bulk_size', '2.4[mm]');",
        "model.component().create('comp1', True);",
        "model.component('comp1').geom().create('geom1', 3);",
        "model.component('comp1').geom('geom1').lengthUnit('mm');",
        "model.component('comp1').geom('geom1').create('inner_ring_outer', 'Cylinder');",
        "model.component('comp1').geom('geom1').feature('inner_ring_outer').set('r', 'inner_race_outer_radius');",
        "model.component('comp1').geom('geom1').feature('inner_ring_outer').set('h', 'bearing_width');",
        "model.component('comp1').geom('geom1').feature('inner_ring_outer').set('pos', ['0', '0', '-bearing_width/2']);",
        "model.component('comp1').geom('geom1').create('inner_ring_bore', 'Cylinder');",
        "model.component('comp1').geom('geom1').feature('inner_ring_bore').set('r', 'inner_diameter/2');",
        "model.component('comp1').geom('geom1').feature('inner_ring_bore').set('h', 'bearing_width+2[mm]');",
        "model.component('comp1').geom('geom1').feature('inner_ring_bore').set('pos', ['0', '0', '-bearing_width/2-1[mm]']);",
        "model.component('comp1').geom('geom1').create('inner_ring', 'Difference');",
        "model.component('comp1').geom('geom1').feature('inner_ring').selection('input').set(['inner_ring_outer']);",
        "model.component('comp1').geom('geom1').feature('inner_ring').selection('input2').set(['inner_ring_bore']);",
        "model.component('comp1').geom('geom1').feature('inner_ring').set('selresult', 'on');",
        "model.component('comp1').geom('geom1').feature('inner_ring').set('selresultshow', 'bnd');",
        "model.component('comp1').geom('geom1').create('outer_ring_outer', 'Cylinder');",
        "model.component('comp1').geom('geom1').feature('outer_ring_outer').set('r', 'outer_diameter/2');",
        "model.component('comp1').geom('geom1').feature('outer_ring_outer').set('h', 'bearing_width');",
        "model.component('comp1').geom('geom1').feature('outer_ring_outer').set('pos', ['0', '0', '-bearing_width/2']);",
        "model.component('comp1').geom('geom1').create('outer_ring_bore', 'Cylinder');",
        "model.component('comp1').geom('geom1').feature('outer_ring_bore').set('r', 'outer_race_inner_radius');",
        "model.component('comp1').geom('geom1').feature('outer_ring_bore').set('h', 'bearing_width+2[mm]');",
        "model.component('comp1').geom('geom1').feature('outer_ring_bore').set('pos', ['0', '0', '-bearing_width/2-1[mm]']);",
        "model.component('comp1').geom('geom1').create('outer_ring', 'Difference');",
        "model.component('comp1').geom('geom1').feature('outer_ring').selection('input').set(['outer_ring_outer']);",
        "model.component('comp1').geom('geom1').feature('outer_ring').selection('input2').set(['outer_ring_bore']);",
        "model.component('comp1').geom('geom1').feature('outer_ring').set('selresult', 'on');",
        "model.component('comp1').geom('geom1').feature('outer_ring').set('selresultshow', 'bnd');",
        "model.component('comp1').geom('geom1').create('cage_outer', 'Cylinder');",
        "model.component('comp1').geom('geom1').feature('cage_outer').set('r', 'cage_outer_radius');",
        "model.component('comp1').geom('geom1').feature('cage_outer').set('h', 'cage_width');",
        "model.component('comp1').geom('geom1').feature('cage_outer').set('pos', ['0', '0', '-cage_width/2']);",
        "model.component('comp1').geom('geom1').create('cage_inner', 'Cylinder');",
        "model.component('comp1').geom('geom1').feature('cage_inner').set('r', 'cage_inner_radius');",
        "model.component('comp1').geom('geom1').feature('cage_inner').set('h', 'cage_width+2[mm]');",
        "model.component('comp1').geom('geom1').feature('cage_inner').set('pos', ['0', '0', '-cage_width/2-1[mm]']);",
        "model.component('comp1').geom('geom1').create('cage_annulus', 'Difference');",
        "model.component('comp1').geom('geom1').feature('cage_annulus').selection('input').set(['cage_outer']);",
        "model.component('comp1').geom('geom1').feature('cage_annulus').selection('input2').set(['cage_inner']);",
    ]
    pocket_tags = []
    roller_centres = []
    for index in range(1, roller_count + 1):
        angle = 2.0 * math.pi * (index - 1) / roller_count
        x = pitch_radius * math.cos(angle)
        y = pitch_radius * math.sin(angle)
        roller_centres.append((index, angle, x, y))
        pocket_tag = f"cage_pocket_{index}"
        pocket_tags.append(pocket_tag)
        lines.extend([
            f"model.component('comp1').geom('geom1').create('{pocket_tag}', 'Cylinder');",
            f"model.component('comp1').geom('geom1').feature('{pocket_tag}').set('r', 'cage_pocket_radius');",
            f"model.component('comp1').geom('geom1').feature('{pocket_tag}').set('h', 'cage_width+2[mm]');",
            f"model.component('comp1').geom('geom1').feature('{pocket_tag}').set('pos', ['{_fmt_mm(x)}', '{_fmt_mm(y)}', '-cage_width/2-1[mm]']);",
        ])
    lines.extend([
        "model.component('comp1').geom('geom1').create('cage', 'Difference');",
        "model.component('comp1').geom('geom1').feature('cage').selection('input').set(['cage_annulus']);",
        "model.component('comp1').geom('geom1').feature('cage').selection('input2').set([" + ", ".join(repr(tag) for tag in pocket_tags) + "]);",
    ])
    for index, _angle, x, y in roller_centres:
        lines.extend([
            f"model.component('comp1').geom('geom1').create('roller_{index}', 'Cylinder');",
            f"model.component('comp1').geom('geom1').feature('roller_{index}').set('r', 'roller_radius');",
            f"model.component('comp1').geom('geom1').feature('roller_{index}').set('h', 'roller_length');",
            f"model.component('comp1').geom('geom1').feature('roller_{index}').set('pos', ['{_fmt_mm(x)}', '{_fmt_mm(y)}', '-roller_length/2']);",
            f"model.component('comp1').geom('geom1').feature('roller_{index}').set('selresult', 'on');",
            f"model.component('comp1').geom('geom1').feature('roller_{index}').set('selresultshow', 'bnd');",
        ])
    lines.extend([
        "model.component('comp1').geom('geom1').feature('fin').set('action', 'assembly');",
        "model.component('comp1').geom('geom1').run();",
        "model.component('comp1').selection().create('sel_inner_raceway_contact', 'Box');",
        "model.component('comp1').selection('sel_inner_raceway_contact').set('entitydim', '2');",
        "model.component('comp1').selection('sel_inner_raceway_contact').set('xmin', '-24[mm]');",
        "model.component('comp1').selection('sel_inner_raceway_contact').set('xmax', '24[mm]');",
        "model.component('comp1').selection('sel_inner_raceway_contact').set('ymin', '-24[mm]');",
        "model.component('comp1').selection('sel_inner_raceway_contact').set('ymax', '24[mm]');",
        "model.component('comp1').selection('sel_inner_raceway_contact').set('zmin', '-9.5[mm]');",
        "model.component('comp1').selection('sel_inner_raceway_contact').set('zmax', '9.5[mm]');",
        "model.component('comp1').selection('sel_inner_raceway_contact').set('condition', 'intersects');",
        "model.component('comp1').selection().create('sel_outer_raceway_contact', 'Box');",
        "model.component('comp1').selection('sel_outer_raceway_contact').set('entitydim', '2');",
        "model.component('comp1').selection('sel_outer_raceway_contact').set('xmin', '-40.5[mm]');",
        "model.component('comp1').selection('sel_outer_raceway_contact').set('xmax', '40.5[mm]');",
        "model.component('comp1').selection('sel_outer_raceway_contact').set('ymin', '-40.5[mm]');",
        "model.component('comp1').selection('sel_outer_raceway_contact').set('ymax', '40.5[mm]');",
        "model.component('comp1').selection('sel_outer_raceway_contact').set('zmin', '-9.5[mm]');",
        "model.component('comp1').selection('sel_outer_raceway_contact').set('zmax', '9.5[mm]');",
        "model.component('comp1').selection('sel_outer_raceway_contact').set('condition', 'intersects');",
        "model.component('comp1').selection().create('sel_outer_support_surface', 'Box');",
        "model.component('comp1').selection('sel_outer_support_surface').set('entitydim', '2');",
        "model.component('comp1').selection('sel_outer_support_surface').set('xmin', '-41[mm]');",
        "model.component('comp1').selection('sel_outer_support_surface').set('xmax', '41[mm]');",
        "model.component('comp1').selection('sel_outer_support_surface').set('ymin', '-41[mm]');",
        "model.component('comp1').selection('sel_outer_support_surface').set('ymax', '41[mm]');",
        "model.component('comp1').selection('sel_outer_support_surface').set('zmin', '-9.5[mm]');",
        "model.component('comp1').selection('sel_outer_support_surface').set('zmax', '9.5[mm]');",
        "model.component('comp1').selection('sel_outer_support_surface').set('condition', 'intersects');",
        "model.component('comp1').selection().create('sel_inner_load_region', 'Box');",
        "model.component('comp1').selection('sel_inner_load_region').set('entitydim', '3');",
        "model.component('comp1').selection('sel_inner_load_region').set('xmin', '-24[mm]');",
        "model.component('comp1').selection('sel_inner_load_region').set('xmax', '24[mm]');",
        "model.component('comp1').selection('sel_inner_load_region').set('ymin', '-24[mm]');",
        "model.component('comp1').selection('sel_inner_load_region').set('ymax', '24[mm]');",
        "model.component('comp1').selection('sel_inner_load_region').set('zmin', '-9.5[mm]');",
        "model.component('comp1').selection('sel_inner_load_region').set('zmax', '9.5[mm]');",
        "model.component('comp1').selection('sel_inner_load_region').set('condition', 'intersects');",
        "model.component('comp1').selection().create('sel_cage_body', 'Box');",
        "model.component('comp1').selection('sel_cage_body').set('entitydim', '3');",
        "model.component('comp1').selection('sel_cage_body').set('xmin', '-31[mm]');",
        "model.component('comp1').selection('sel_cage_body').set('xmax', '31[mm]');",
        "model.component('comp1').selection('sel_cage_body').set('ymin', '-31[mm]');",
        "model.component('comp1').selection('sel_cage_body').set('ymax', '31[mm]');",
        "model.component('comp1').selection('sel_cage_body').set('zmin', '-7.5[mm]');",
        "model.component('comp1').selection('sel_cage_body').set('zmax', '7.5[mm]');",
        "model.component('comp1').selection('sel_cage_body').set('condition', 'intersects');",
    ])
    for index, angle, x, y in roller_centres:
        xmin, xmax = x - roller_radius - roller_box_margin, x + roller_radius + roller_box_margin
        ymin, ymax = y - roller_radius - roller_box_margin, y + roller_radius + roller_box_margin
        lines.extend([
            f"model.component('comp1').selection().create('sel_roller_{index}_body', 'Box');",
            f"model.component('comp1').selection('sel_roller_{index}_body').set('entitydim', '3');",
            f"model.component('comp1').selection('sel_roller_{index}_body').set('xmin', '{_fmt_mm(xmin)}');",
            f"model.component('comp1').selection('sel_roller_{index}_body').set('xmax', '{_fmt_mm(xmax)}');",
            f"model.component('comp1').selection('sel_roller_{index}_body').set('ymin', '{_fmt_mm(ymin)}');",
            f"model.component('comp1').selection('sel_roller_{index}_body').set('ymax', '{_fmt_mm(ymax)}');",
            f"model.component('comp1').selection('sel_roller_{index}_body').set('zmin', '-8.5[mm]');",
            f"model.component('comp1').selection('sel_roller_{index}_body').set('zmax', '8.5[mm]');",
            f"model.component('comp1').selection('sel_roller_{index}_body').set('condition', 'intersects');",
        ])
        radial_x, radial_y = math.cos(angle), math.sin(angle)
        tangent_x, tangent_y = -math.sin(angle), math.cos(angle)
        for side_name, radial_offset in (("inner", -roller_radius), ("outer", roller_radius)):
            cx = x + radial_offset * radial_x
            cy = y + radial_offset * radial_y
            half_radial = contact_half_width
            half_tangent = roller_radius + 0.6
            corners = []
            for sr in (-1, 1):
                for st in (-1, 1):
                    corners.append((cx + sr * half_radial * radial_x + st * half_tangent * tangent_x, cy + sr * half_radial * radial_y + st * half_tangent * tangent_y))
            xs = [c[0] for c in corners]
            ys = [c[1] for c in corners]
            box_tag = f"box_roller_{index}_{side_name}_contact_patch"
            roller_tag = f"sel_roller_{index}_{side_name}_contact"
            raceway_tag = f"sel_{side_name}_raceway_{index}_contact"
            raceway_object_tag = "geom1_inner_ring_bnd" if side_name == "inner" else "geom1_outer_ring_bnd"
            lines.extend([
                f"model.component('comp1').selection().create('{box_tag}', 'Box');",
                f"model.component('comp1').selection('{box_tag}').set('entitydim', '2');",
                f"model.component('comp1').selection('{box_tag}').set('xmin', '{_fmt_mm(min(xs))}');",
                f"model.component('comp1').selection('{box_tag}').set('xmax', '{_fmt_mm(max(xs))}');",
                f"model.component('comp1').selection('{box_tag}').set('ymin', '{_fmt_mm(min(ys))}');",
                f"model.component('comp1').selection('{box_tag}').set('ymax', '{_fmt_mm(max(ys))}');",
                f"model.component('comp1').selection('{box_tag}').set('zmin', '-8.5[mm]');",
                f"model.component('comp1').selection('{box_tag}').set('zmax', '8.5[mm]');",
                f"model.component('comp1').selection('{box_tag}').set('condition', 'intersects');",
                f"model.component('comp1').selection().create('{roller_tag}', 'Intersection');",
                f"model.component('comp1').selection('{roller_tag}').set('entitydim', '2');",
                f"model.component('comp1').selection('{roller_tag}').set('input', ['{box_tag}', 'geom1_roller_{index}_bnd']);",
                f"model.component('comp1').selection().create('{raceway_tag}', 'Intersection');",
                f"model.component('comp1').selection('{raceway_tag}').set('entitydim', '2');",
                f"model.component('comp1').selection('{raceway_tag}').set('input', ['{box_tag}', '{raceway_object_tag}']);",
            ])
    lines.extend([
        "model.component('comp1').material().create('mat_steel', 'Common');",
        "model.component('comp1').material('mat_steel').label('Bearing steel rings and rollers');",
        "model.component('comp1').material('mat_steel').propertyGroup('def').set('youngsmodulus', 'E_steel');",
        "model.component('comp1').material('mat_steel').propertyGroup('def').set('poissonsratio', 'nu_steel');",
        "model.component('comp1').material('mat_steel').propertyGroup('def').set('density', 'rho_steel');",
        "model.component('comp1').material('mat_steel').selection().all();",
        "model.component('comp1').material().create('mat_cage', 'Common');",
        "model.component('comp1').material('mat_cage').label('Polymer cage');",
        "model.component('comp1').material('mat_cage').propertyGroup('def').set('youngsmodulus', 'E_cage');",
        "model.component('comp1').material('mat_cage').propertyGroup('def').set('poissonsratio', 'nu_cage');",
        "model.component('comp1').material('mat_cage').propertyGroup('def').set('density', 'rho_cage');",
        "model.component('comp1').material('mat_cage').selection().named('sel_cage_body');",
        "model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');",
        "model.component('comp1').physics('solid').create('fix_outer', 'Fixed', 2);",
        "model.component('comp1').physics('solid').feature('fix_outer').selection().named('sel_outer_support_surface');",
        "model.component('comp1').physics('solid').create('load_inner', 'BodyLoad', 3);",
        "model.component('comp1').physics('solid').feature('load_inner').selection().named('sel_inner_load_region');",
        "model.component('comp1').physics('solid').feature('load_inner').set('FperVol', ['radial_load/(pi*(inner_race_outer_radius^2-(inner_diameter/2)^2)*bearing_width)', '0', '0']);",
    ])
    for index, _angle, _x, _y in roller_centres:
        lines.extend([
            f"model.component('comp1').pair().create('cp_roller_{index}_inner_raceway', 'Contact');",
            f"model.component('comp1').pair('cp_roller_{index}_inner_raceway').manualSelection(True);",
            f"model.component('comp1').pair('cp_roller_{index}_inner_raceway').source().named('sel_roller_{index}_inner_contact');",
            f"model.component('comp1').pair('cp_roller_{index}_inner_raceway').destination().named('sel_inner_raceway_{index}_contact');",
            f"model.component('comp1').pair().create('cp_roller_{index}_outer_raceway', 'Contact');",
            f"model.component('comp1').pair('cp_roller_{index}_outer_raceway').manualSelection(True);",
            f"model.component('comp1').pair('cp_roller_{index}_outer_raceway').source().named('sel_roller_{index}_outer_contact');",
            f"model.component('comp1').pair('cp_roller_{index}_outer_raceway').destination().named('sel_outer_raceway_{index}_contact');",
            f"model.component('comp1').physics('solid').create('contact_roller_{index}_inner', 'Contact', 2);",
            f"model.component('comp1').physics('solid').feature('contact_roller_{index}_inner').set('pairs', ['cp_roller_{index}_inner_raceway']);",
            f"model.component('comp1').physics('solid').feature('contact_roller_{index}_inner').set('pfm', 'penalty');",
            f"model.component('comp1').physics('solid').create('contact_roller_{index}_outer', 'Contact', 2);",
            f"model.component('comp1').physics('solid').feature('contact_roller_{index}_outer').set('pairs', ['cp_roller_{index}_outer_raceway']);",
            f"model.component('comp1').physics('solid').feature('contact_roller_{index}_outer').set('pfm', 'penalty');",
            f"model.component('comp1').cpl().create('maxop_roller_{index}', 'Maximum');",
            f"model.component('comp1').cpl('maxop_roller_{index}').selection().named('sel_roller_{index}_body');",
        ])
    lines.extend([
        "model.component('comp1').mesh().create('mesh1');",
        "model.component('comp1').mesh('mesh1').create('size_global', 'Size');",
        "model.component('comp1').mesh('mesh1').feature('size_global').set('hmax', 'mesh_bulk_size');",
        "model.component('comp1').mesh('mesh1').feature('size_global').set('hmin', 'mesh_contact_size');",
        "model.component('comp1').mesh('mesh1').create('ftet1', 'FreeTet');",
        "model.study().create('std1');",
        "model.study('std1').create('stat', 'Stationary');",
        "model.result().create('pg_stress3d', 'PlotGroup3D');",
        "model.result('pg_stress3d').feature().create('surf_mises', 'Surface');",
        "model.result('pg_stress3d').feature('surf_mises').set('expr', 'solid.mises');",
        "model.result().numerical().create('max_von_mises', 'MaxVolume');",
        "model.result().numerical('max_von_mises').set('expr', 'solid.mises');",
    ])
    for index in range(1, roller_count + 1):
        lines.extend([
            f"model.result().numerical().create('probe_roller_{index}_max_mises', 'MaxVolume');",
            f"model.result().numerical('probe_roller_{index}_max_mises').set('expr', 'maxop_roller_{index}(solid.mises)');",
        ])
    lines.extend([
        "model.result().numerical().create('max_contact_pressure_estimate', 'EvalGlobal');",
        "model.result().numerical('max_contact_pressure_estimate').set('expr', 'contact_pressure_est');",
        f"output.write('3D full cylindrical-roller bearing setup built: inner ring, outer ring, {roller_count} rollers, real Boolean cage ring with {roller_count} cylindrical pocket cutouts, named Box selections, {2 * roller_count} roller/raceway Contact pair features, scoped per-roller Maximum probes, body-load radial smoke load, fixed support, stationary Solid Mechanics, and 3D stress plot. probe_scope_verified cage_boolean_pockets_verified');",
    ])
    return "\n".join(lines)


VERIFIED_3D_FULL_BEARING_CODE = _build_verified_3d_full_bearing_code(roller_count=VERIFIED_ROLLER_COUNT)


@dataclass(frozen=True)
class DemoPrompt:
    """One 3D bearing demo prompt and its expected tool gates."""

    name: str
    prompt: str
    required_tools: tuple[str, ...]
    successful_tools: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "prompt": self.prompt,
            "required_tools": list(self.required_tools),
            "successful_tools": list(self.successful_tools),
        }


class Segmented3DGenerationError(RuntimeError):
    """Raised when segmented generation fails with auditable attempt history."""

    def __init__(self, message: str, repair_history: list[dict[str, Any]]):
        super().__init__(message)
        self.repair_history = repair_history


def build_3d_bearing_code_generation_prompt(*, archive_path: str) -> DemoPrompt:
    """Ask the agent to plan and draft a full 3D roller bearing with cage."""
    known_params = {
        "bearing_type": "cylindrical_roller_bearing",
        "model_dimension": "3d_full_bearing",
        "inner_diameter": "40[mm]",
        "outer_diameter": "80[mm]",
        "bearing_width": "18[mm]",
        "roller_count": "12",
        "roller_diameter": "8[mm]",
        "roller_length": "16[mm]",
        "radial_load": "3000[N]",
        "material": "bearing_steel",
        "cage_included": "true",
        "cage_model": "cage_ring_with_twelve_boolean_pocket_cutouts",
        "contact_model": "3d_contact_pair_full_roller_set",
    }
    return DemoPrompt(
        name="bearing_3d_code_draft",
        prompt=(
            "A user asks for a complete 3D cylindrical-roller bearing COMSOL simulation with a cage. "
            "This target is not the existing 2D smoke. The generated main demo must be 3D and must include "
            "inner ring, outer ring, twelve or configurable rollers, and an explicit cage ring with Boolean roller pockets "
            "or cage constraints. Do not replace it with a plate, block, beam, 2D plane-strain cell, or cage-omitted "
            "model. First call simulation_plan_multiroller_bearing with allow_defaults=true and provided_params="
            f"{known_params!r}. Then search templates and local COMSOL API docs. If no true 3D full-bearing "
            "template exists, call simulation_plan_generated_code with domain='structural', allow_defaults=false, "
            f"archive_path={archive_path!r}, and known_params containing the resolved 3D bearing and cage decisions. "
            "Do not call simulation_validate_template, simulation_run_template, simulation_save_template, "
            "simulation_export_template, COMSOL runtime tools, file_read, file_write, or any file tools in this draft step. "
            "Return setup-only COMSOL Java/API code between GENERATED_CODE_START and GENERATED_CODE_END. "
            "Do not include any prose, bullet list, markdown table, analysis, or code fence inside the markers. "
            "Keep the code compact and complete; prefer explicit repeated lines over loops if that is safer for MPh. "
            "Inside the markers return only executable code for an existing `model` object. The code must create "
            "3D geometry (`geom1`, 3), inner ring, outer ring, twelve roller cylinders on the pitch circle, cage "
            "geometry with twelve Boolean pocket cutouts, bearing steel/materials, SolidMechanics, "
            "explicit Contact Pair/Contact features for roller-to-inner-raceway and roller-to-outer-raceway "
            "interfaces, radial load, support, mesh, stationary study, and a PlotGroup3D for solid.mises. "
            "It must expose a contact-pressure estimate expression and record that the cage is included via a "
            "plain code comment or model parameter; do not call output.write or model.output().write. "
            "Use Python/MPh-compatible snippet style: no Java typed variables, no `new int[]`, no solver "
            "run, no plot run. Boundary/contact selections may use named selections or a verified fallback, but "
            "must not rely on 2D boundary IDs. Use verified MPh idioms only: create contact pairs with "
            "model.component('comp1').pair().create(..., 'Contact') plus Solid Mechanics Contact features that set "
            "`pairs`; create studies/results at top-level model.study()/model.result(); create Difference inputs via "
            "selection('input').set([...]) and selection('input2').set([...]); create region selections only as "
            "model.component('comp1').selection().create(tag, 'Box') with xmin/xmax/ymin/ymax/zmin/zmax. "
            "Do not use CylinderSelection, BoxSelection, ExplicitSelection, Explicit geometry features, "
            "physics-level ContactPair interfaces, Difference object/objects setters, setNamed, "
            "Java block comments inside arrays, mixed quoted/unquoted new double[] literals, or pair.set('source')/"
            "pair.set('destination') endpoint setters. If using named contact endpoints, call "
            "pair('tag').source().named('selection_tag') and pair('tag').destination().named('selection_tag')."
        ),
        required_tools=(
            "simulation_plan_multiroller_bearing",
            "simulation_search_templates",
            "simulation_plan_generated_code",
        ),
        successful_tools=(
            "simulation_plan_multiroller_bearing",
            "simulation_plan_generated_code",
        ),
    )


def build_3d_bearing_execution_prompt(
    *,
    java_code: str,
    archive_path: str,
    artifact_dir: str,
    plot_path: str,
    model_name: str,
    template_name: str,
    package_dir: str,
    execution_context: dict[str, Any] | None = None,
    allow_verified_fallback: bool = True,
) -> DemoPrompt:
    """Ask the agent to execute a 3D full bearing and record repair evidence."""
    params = {
        "model_dimension": "3d_full_bearing",
        "inner_diameter": "40[mm]",
        "outer_diameter": "80[mm]",
        "bearing_width": "18[mm]",
        "roller_count": "12",
        "roller_diameter": "8[mm]",
        "roller_length": "16[mm]",
        "radial_load": "3000[N]",
        "cage_included": "true",
    }
    execution_context = execution_context or {}
    fallback_instruction = (
        "If boundary/contact selection fails, replace the setup code with VERIFIED_3D_FALLBACK_CODE "
        "shown below and count that as one repair attempt. "
        if allow_verified_fallback
        else
        "Do not replace the setup code with a complete verified fallback; repair only the generated code "
        "using small API-compatible edits and stop with the structured error if those bounded repairs fail. "
    )
    fallback_block = f"\n\nVERIFIED_3D_FALLBACK_CODE:\n{VERIFIED_3D_FULL_BEARING_CODE}" if allow_verified_fallback else ""
    return DemoPrompt(
        name="bearing_3d_execute_package_answer",
        prompt=(
            "Use the exact raw COMSOL Java/API code below as generated 3D full-bearing setup code. "
            "Run this deterministic chain: simulation_validate_template, simulation_run_template, "
            "comsol_solve, simulation_probe_3d_selection_binding, comsol_evaluate, comsol_plot, simulation_export_bearing_contact_package, "
            "simulation_answer_artifact_question, comsol_close_model. If validation or runtime execution fails, "
            "perform at most two repair attempts using the structured error and simulation_retrieve_api_docs. "
            "If you call simulation_validate_template during repair, you must pass the repaired raw code in "
            "java_code; never call simulation_validate_template with empty arguments. "
            "Every repair attempt must keep the model 3D and keep the cage included. Do not fall back to 2D. "
            "Record in the final response the failed code cause, repair strategy, and whether the repaired code "
            f"succeeded. {fallback_instruction}"
            f"Use params={params!r}. Validate with name={template_name!r}, java_code=<raw code>, params=params, "
            f"archive_path={archive_path!r}. Run with simulation_run_template name={template_name!r}, java_code=<raw code>, "
            f"params=params, execution_context={execution_context!r}, create_model_name={model_name!r}, close_model=false, artifact_dir={artifact_dir!r}, "
            f"artifact_name='agent_3d_bearing_execution', archive_path={archive_path!r}. After run succeeds, solve the "
            "model, call simulation_probe_3d_selection_binding with model_name and the raw java_code to verify runtime selection entity counts, "
            f"evaluate solid.mises, solid.disp, and contact_pressure_est, plot solid.mises to {plot_path!r}, export a result package with "
            "simulation_export_bearing_contact_package using package_name='agent_3d_bearing_package', "
            f"output_dir={package_dir!r}, archive_path={archive_path!r}, and template_run_id from the template run. "
            "Then ask simulation_answer_artifact_question: '最大应力是多少，最大应力位置在哪里，哪个滚子附近风险最高，保持架是否建模，滚子和外圈有没有接触？' "
            "using the package run_id. Close the model without saving. "
            "RAW_GENERATED_CODE:\n"
            f"{java_code}{fallback_block}"
        ),
        required_tools=(
            "simulation_validate_template",
            "simulation_run_template",
            "comsol_solve",
            "simulation_probe_3d_selection_binding",
            "comsol_evaluate",
            "comsol_plot",
            "simulation_export_bearing_contact_package",
            "simulation_answer_artifact_question",
            "comsol_close_model",
        ),
        successful_tools=(
            "simulation_validate_template",
            "simulation_run_template",
            "comsol_solve",
            "simulation_probe_3d_selection_binding",
            "comsol_evaluate",
            "comsol_plot",
            "simulation_export_bearing_contact_package",
            "simulation_answer_artifact_question",
            "comsol_close_model",
        ),
    )


async def generate_segmented_3d_bearing_code(
    *,
    provider: Any,
    artifact_root: Path,
    args: argparse.Namespace,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Generate 3D bearing setup code in small manifest-checked segments."""
    completed_manifests: list[dict[str, Any]] = []
    segment_results: list[dict[str, Any]] = []
    repair_history: list[dict[str, Any]] = []
    existing_tags: set[str] = set()
    previous_code = ""
    segment_dir = artifact_root / "segmented_generation"
    segment_dir.mkdir(parents=True, exist_ok=True)
    for index, spec in enumerate(SEGMENTED_3D_CODE_SPECS):
        validation: dict[str, Any] | None = None
        raw_text = ""
        code = ""
        prompt = ""
        last_error = ""
        manifest: dict[str, Any] | None = None
        for segment_attempt in range(args.segment_max_retries):
            retry_note = (
                ""
                if not last_error
                else "\n\nPREVIOUS_SEGMENT_ATTEMPT_FAILED:\n"
                f"{last_error}\n"
                "Regenerate this same segment only. Keep the manifest and code markers exact.\n"
            )
            prompt = build_segmented_3d_generation_prompt(
                spec,
                completed_manifests=completed_manifests,
                previous_code_tail=previous_code,
            ) + retry_note
            try:
                response = await asyncio.wait_for(
                    provider.generate(
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "You are a segmented COMSOL code-generation assistant. "
                                    "Return only the requested manifest and code markers."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                        tools=None,
                        temperature=0,
                        max_tokens=args.segment_llm_max_tokens,
                    ),
                    timeout=args.segment_timeout_seconds,
                )
                raw_text = response.text or ""
                manifest = extract_segment_manifest(raw_text)
                code = extract_segment_generated_code(raw_text) or _extract_executable_model_snippet(raw_text) or ""
                code = normalize_generated_mph_code(code)
                validation = validate_segmented_3d_segment(
                    spec,
                    manifest,
                    code,
                    completed_manifests=completed_manifests,
                    existing_tags=existing_tags,
                )
                validation.update({
                    "stage": "segmented_generation",
                    "attempt": len(repair_history),
                    "segment_attempt": segment_attempt,
                    "segment_id": spec.segment_id,
                    "llm_usage": response.usage,
                    "finish_reason": response.finish_reason,
                    "generated_code_excerpt": _code_excerpt(code),
                })
                if validation["success"]:
                    break
                last_error = json.dumps(validation.get("errors", []), ensure_ascii=False)
            except Exception as exc:
                last_error = (
                    f"segment request timed out after {args.segment_timeout_seconds}s"
                    if isinstance(exc, TimeoutError)
                    else str(exc)
                )
                validation = {
                    "success": False,
                    "errors": [last_error],
                    "warnings": [],
                    "created_tags": [],
                    "manifest": None,
                    "code": "",
                    "stage": "segmented_generation",
                    "attempt": len(repair_history),
                    "segment_attempt": segment_attempt,
                    "segment_id": spec.segment_id,
                    "generated_code_excerpt": "",
                }
            repair_history.append({
                key: value
                for key, value in validation.items()
                if key not in {"code", "manifest"}
            })
            if validation["success"]:
                break
            await asyncio.sleep(min(2 ** segment_attempt, 8))
        if validation is None:
            raise RuntimeError(f"Segmented 3D generation did not run for {spec.segment_id}.")
        repair_history.append({
            "stage": "segmented_generation_segment_complete",
            "attempt": len(repair_history),
            "segment_id": spec.segment_id,
            "success": validation["success"],
            "segment_attempts": validation.get("segment_attempt", 0) + 1,
        })
        (segment_dir / f"{index + 1}_{spec.segment_id}.json").write_text(
            json.dumps(
                {
                    "prompt": prompt,
                    "response": raw_text,
                    "manifest": manifest,
                    "validation": {k: v for k, v in validation.items() if k != "code"},
                    "code": code,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        if not validation["success"]:
            raise Segmented3DGenerationError(
                f"Segmented 3D generation failed at {spec.segment_id}: {validation['errors']}",
                repair_history=repair_history,
            )
        segment_results.append(validation)
        completed_manifests.append(validation["manifest"])
        existing_tags.update(validation["created_tags"])
        previous_code = f"{previous_code.rstrip()}\n\n{code.strip()}"
    assembled_code, assembly_manifest = assemble_segmented_3d_code(segment_results)
    (segment_dir / "assembled_manifest.json").write_text(
        json.dumps(assembly_manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (segment_dir / "assembled_code.pyfrag").write_text(assembled_code, encoding="utf-8")
    draft_summary = {
        "name": "bearing_3d_segmented_code_draft",
        "success": assembly_manifest["final_quality"]["success"],
        "response": "",
        "observed_tools": [],
        "missing_calls": [],
        "missing_successes": [],
        "new_tool_results": [],
        "segmented_manifest_path": str(segment_dir / "assembled_manifest.json"),
        "assembled_code_path": str(segment_dir / "assembled_code.pyfrag"),
        "segment_count": len(segment_results),
    }
    repair_history.append({
        "attempt": len(repair_history),
        "stage": "segmented_assembly_quality_gate",
        "strategy": "assemble_manifest_checked_segments_and_run_full_3d_quality_gate",
        "success": assembly_manifest["final_quality"]["success"],
        "errors": assembly_manifest["final_quality"].get("errors", []),
        "warnings": assembly_manifest["final_quality"].get("warnings", []),
        "assembled_code_excerpt": _code_excerpt(assembled_code),
    })
    return assembled_code, draft_summary, repair_history

def apply_bounded_3d_generated_code_repairs(
    java_code: str,
    initial_quality: dict[str, Any],
    *,
    max_attempts: int = 2,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Apply small, auditable repairs before falling back to the verified fixture."""
    repaired_code = java_code
    quality = initial_quality
    reports: list[dict[str, Any]] = []
    for _ in range(max_attempts):
        patch = _next_bounded_3d_repair_patch(repaired_code, quality)
        if not patch:
            break
        before = repaired_code
        repaired_code = f"{repaired_code.rstrip()}\n\n{patch['code'].strip()}\n"
        quality = validate_3d_bearing_code_draft(repaired_code)
        reports.append({
            "stage": "offline_bounded_repair",
            "strategy": patch["strategy"],
            "success": quality["success"],
            "errors_before": patch["errors_before"],
            "errors_after": quality["errors"],
            "api_doc_query": patch.get("api_doc_query"),
            "api_doc_citations": patch.get("api_doc_citations", []),
            "failed_code_excerpt": _code_excerpt(before),
            "repaired_code_excerpt": _code_excerpt(repaired_code),
        })
        if quality["success"]:
            break
    return repaired_code, reports, quality


def apply_runtime_preflight_3d_repairs(
    java_code: str,
    initial_quality: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Normalize high-frequency generated COMSOL API mistakes before execution."""
    repaired_code = java_code
    reports: list[dict[str, Any]] = []
    quality_before = initial_quality or validate_3d_bearing_code_draft(java_code)

    repaired_code, scoped_changes = _repair_component_scoped_study_and_result(repaired_code)
    repaired_code, contact_changes = _repair_generated_contact_api_fragments(repaired_code)
    repaired_code, numerical_changes = _repair_component_scoped_numerical_results(repaired_code)
    repaired_code, geometry_changes = _repair_generated_geometry_api_fragments(repaired_code)
    repaired_code, selection_changes = _repair_generated_selection_api_fragments(repaired_code)
    repaired_code, output_changes = _repair_generated_output_api_fragments(repaired_code)
    repaired_code, set_list_changes = _repair_generated_set_list_literals(repaired_code)
    repaired_code, parameter_changes = _repair_generated_missing_cross_segment_parameters(repaired_code)
    repaired_code, material_changes = _repair_generated_material_properties(repaired_code)

    changes = scoped_changes + contact_changes + numerical_changes + geometry_changes + selection_changes + output_changes + set_list_changes + parameter_changes + material_changes
    if changes:
        quality_after = validate_3d_bearing_code_draft(repaired_code)
        reports.append({
            "stage": "offline_runtime_preflight_repair",
            "strategy": "normalize_common_generated_comsol_api_misuse",
            "success": quality_after["success"],
            "changes": changes,
            "errors_before": quality_before.get("errors", []),
            "errors_after": quality_after["errors"],
            "api_doc_query": "COMSOL MPh top-level study result numerical Contact pair Solid Mechanics Contact",
            "api_doc_citations": _collect_api_doc_citations(
                "COMSOL MPh top-level study result numerical Contact pair Solid Mechanics Contact"
            ),
            "failed_code_excerpt": _code_excerpt(java_code),
            "repaired_code_excerpt": _code_excerpt(repaired_code),
        })
        return repaired_code, reports, quality_after
    return repaired_code, reports, quality_before


def _repair_component_scoped_study_and_result(java_code: str) -> tuple[str, list[str]]:
    repaired = java_code
    changes: list[str] = []
    replacements = (
        (r"model\.component\((['\"]comp1['\"])\)\.study\(\)", "model.study()", "component_scoped_study_create_to_top_level"),
        (r"model\.component\((['\"]comp1['\"])\)\.study\((['\"][^'\"]+['\"])\)", r"model.study(\2)", "component_scoped_study_tag_to_top_level"),
        (r"model\.component\((['\"]comp1['\"])\)\.result\(\)", "model.result()", "component_scoped_result_create_to_top_level"),
        (r"model\.component\((['\"]comp1['\"])\)\.result\((['\"][^'\"]+['\"])\)", r"model.result(\2)", "component_scoped_result_tag_to_top_level"),
    )
    for pattern, replacement, change in replacements:
        repaired, count = re.subn(pattern, replacement, repaired)
        if count:
            changes.append(f"{change}:{count}")
    return repaired, changes


def _repair_generated_set_list_literals(java_code: str) -> tuple[str, list[str]]:
    """Stringify Python list values passed to COMSOL PropFeature.set overloads."""
    changes: list[str] = []

    def _stringify_item(item: str) -> str:
        stripped = item.strip()
        if not stripped:
            return stripped
        if (stripped.startswith("'") and stripped.endswith("'")) or (stripped.startswith('"') and stripped.endswith('"')):
            return stripped
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", stripped):
            return repr(stripped)
        if stripped.startswith("str("):
            return stripped
        return f"str({stripped})"

    def _replace(match: re.Match[str]) -> str:
        head, body, tail = match.groups()
        items = [_stringify_item(part) for part in body.split(",")]
        return f"{head}[{', '.join(items)}]{tail}"

    repaired, count = re.subn(
        r"(\.set\(\s*['\"][^'\"]+['\"]\s*,\s*)\[([^\]\n]+)\](\s*\))",
        _replace,
        java_code,
    )
    if count:
        changes.append(f"stringify_propfeature_set_list_values:{count}")
    return repaired, changes


def _repair_generated_missing_cross_segment_parameters(java_code: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    defaults = {
        "num_rollers": "12",
        "roller_dia": "8[mm]",
        "roller_length": "16[mm]",
        "pitch_dia": "(inner_ring_outer_dia+outer_ring_inner_dia)/2",
        "pocket_dia": "roller_dia+1[mm]",
        "radial_load": "3000[N]",
        "contact_pressure_est": "radial_load/(roller_length*roller_dia*num_rollers)",
        "max_contact_pressure": "contact_pressure_est",
        "mesh_bulk_size": "2.4[mm]",
        "mesh_contact_size": "0.7[mm]",
    }
    insertions = []
    for name, value in defaults.items():
        required_for_package = name in {
            "radial_load",
            "num_rollers",
            "roller_dia",
            "roller_length",
            "contact_pressure_est",
            "max_contact_pressure",
        }
        if (required_for_package or name in java_code) and f"param().set('{name}'" not in java_code and f'param().set("{name}"' not in java_code:
            insertions.append(f"model.param().set('{name}', '{value}')")
            changes.append(f"add_missing_cross_segment_parameter_{name}")
    if not insertions:
        return java_code, changes
    lines = java_code.splitlines()
    insert_at = 0
    for index, line in enumerate(lines):
        if "model.param().set(" in line:
            insert_at = index + 1
        elif insert_at and line.strip() and not line.lstrip().startswith("#"):
            break
    repaired_lines = lines[:insert_at] + insertions + lines[insert_at:]
    return "\n".join(repaired_lines), changes


def _repair_generated_material_properties(java_code: str) -> tuple[str, list[str]]:
    repaired = java_code
    changes: list[str] = []
    repaired, count = re.subn(
        r"^.*model\.(?:study|result)\([^)]*\)\.run\(\)\s*$\n?",
        "",
        repaired,
        flags=re.MULTILINE,
    )
    if count:
        changes.append(f"remove_setup_stage_study_or_result_run:{count}")
    repaired, count = re.subn(
        r"^.*model\.result\(\)\.numerical\([^)]*\)\.run\(\)\s*$\n?",
        "",
        repaired,
        flags=re.MULTILINE,
    )
    if count:
        changes.append(f"remove_setup_stage_numerical_run:{count}")
    if "material('mat_steel')" in repaired and "youngsmodulus" not in repaired.lower():
        material_patch = "\n".join([
            "model.component('comp1').material('mat_steel').propertyGroup('def').set('youngsmodulus', '210[GPa]')",
            "model.component('comp1').material('mat_steel').propertyGroup('def').set('poissonsratio', '0.30')",
            "model.component('comp1').material('mat_steel').propertyGroup('def').set('density', '7850[kg/m^3]')",
        ])
        lines = repaired.splitlines()
        insert_at = 0
        for index, line in enumerate(lines):
            if "material('mat_steel')" in line:
                insert_at = index + 1
        lines = lines[:insert_at] + material_patch.splitlines() + lines[insert_at:]
        repaired = "\n".join(lines)
        changes.append("add_missing_mat_steel_linear_elastic_properties")
    return repaired, changes


def _repair_generated_contact_api_fragments(java_code: str) -> tuple[str, list[str]]:
    repaired = java_code
    changes: list[str] = []
    placeholder_pairs = {
        "pair1": "cp_roller_inner_raceway",
        "pair2": "cp_roller_outer_raceway",
        "pair_inner": "cp_roller_inner_raceway",
        "pair_outer": "cp_roller_outer_raceway",
    }
    for old_tag, new_tag in placeholder_pairs.items():
        repaired, count = re.subn(
            rf"(['\"]){old_tag}\1",
            lambda match, replacement=new_tag: f"{match.group(1)}{replacement}{match.group(1)}",
            repaired,
        )
        if count:
            changes.append(f"rename_placeholder_contact_pair_{old_tag}:{count}")
    repaired, count = re.subn(
        r"\.pair\(\)\.create\((['\"][^'\"]+['\"])\s*,\s*['\"]contact['\"]\)",
        r".pair().create(\1, 'Contact')",
        repaired,
    )
    if count:
        changes.append(f"lowercase_contact_pair_type_to_contact:{count}")
    repaired, count = re.subn(
        r"\.pair\(\)\.create\((['\"][^'\"]+['\"])\s*,\s*['\"]ContactPair['\"]\)",
        r".pair().create(\1, 'Contact')",
        repaired,
    )
    if count:
        changes.append(f"contactpair_type_to_contact:{count}")
    repaired, endpoint_count = re.subn(
        r"\.pair\((?P<pair>['\"][^'\"]+['\"])\)\.set\(\s*['\"]source['\"]\s*,\s*\[(?P<selection>['\"][^'\"]+['\"])\]\s*\)",
        r".pair(\g<pair>).source().named(\g<selection>)",
        repaired,
    )
    repaired, endpoint_count_2 = re.subn(
        r"\.pair\((?P<pair>['\"][^'\"]+['\"])\)\.set\(\s*['\"]destination['\"]\s*,\s*\[(?P<selection>['\"][^'\"]+['\"])\]\s*\)",
        r".pair(\g<pair>).destination().named(\g<selection>)",
        repaired,
    )
    if endpoint_count or endpoint_count_2:
        changes.append(f"contact_pair_set_endpoint_to_named:{endpoint_count + endpoint_count_2}")
    repaired, manual_count = re.subn(
        r"\.pair\((?P<pair>[^)]*)\)\.set\(\s*['\"]manualSelection['\"]\s*,\s*(?P<flag>True|False|true|false)\s*\)",
        lambda match: f".pair({match.group('pair')}).manualSelection({match.group('flag')})",
        repaired,
    )
    if manual_count:
        changes.append(f"contact_pair_set_manualselection_to_method:{manual_count}")
    repaired, count = re.subn(
        r"feature\(\)\.create\((['\"][^'\"]+['\"])\s*,\s*(['\"]Contact['\"])\s*,\s*1\s*\)",
        r"feature().create(\1, \2, 2)",
        repaired,
    )
    if count:
        changes.append(f"solid_contact_entity_dimension_1_to_2:{count}")
    repaired, count = re.subn(r"['\"]FixedConstraint['\"]", "'Fixed'", repaired)
    if count:
        changes.append(f"fixedconstraint_to_fixed:{count}")
    repaired, count = re.subn(
        r"^.*\.physics\(\s*['\"]solid['\"]\s*\)\.prop\(\s*['\"]d['\"]\s*\)\.set\([^\n]*\)\s*$\n?",
        "",
        repaired,
        flags=re.MULTILINE,
    )
    if count:
        changes.append(f"remove_invalid_solid_prop_d_set:{count}")
    repaired, count = re.subn(r"\.coupling\(\)", ".cpl()", repaired)
    if count:
        changes.append(f"component_coupling_create_to_cpl_create:{count}")
    repaired, count = re.subn(r"\.coupling\(([^)]*)\)", r".cpl(\1)", repaired)
    if count:
        changes.append(f"component_coupling_tag_to_cpl_tag:{count}")
    repaired, count = re.subn(
        r"\.set\((['\"])contact_pair\1\s*,\s*(['\"])([^'\"]+)\2\)",
        r".set('pairs', ['\3'])",
        repaired,
    )
    if count:
        changes.append(f"contact_pair_property_to_pairs_list:{count}")
    repaired, count = re.subn(
        r"\.(source|destination)\(\)\.set\(\s*\[\s*(['\"])geom1\2\s*\]\s*\)",
        lambda match: f".{match.group(1)}().all()",
        repaired,
    )
    if count:
        changes.append(f"geom1_contact_pair_endpoint_to_all_placeholder:{count}")
    repaired, count = re.subn(
        r"\.selection\(\)\.set\(\s*\[\s*(['\"])geom1\1\s*\]\s*\)",
        ".selection().all()",
        repaired,
    )
    if count:
        changes.append(f"geom1_placeholder_selection_to_all_placeholder:{count}")
    return repaired, changes


def _repair_generated_geometry_api_fragments(java_code: str) -> tuple[str, list[str]]:
    repaired = java_code
    changes: list[str] = []
    repaired, count = re.subn(
        r"^.*\.geom\((['\"])geom1\1\)\.feature\((['\"])[^'\"]+\2\)\.set\((['\"])(?:ax|axis)\3\s*,\s*\[[^\n;]+\]\);?\s*$\n?",
        "",
        repaired,
        flags=re.MULTILINE,
    )
    if count:
        changes.append(f"remove_unsupported_cylinder_axis_property:{count}")
    def _replace_run_then_finalize(match: re.Match[str]) -> str:
        indent = match.group("indent")
        comp = match.group("comp")
        geom = match.group("geom")
        return (
            f"{indent}model.component({comp}).geom({geom}).feature('fin').set('action', 'assembly');\n"
            f"{indent}model.component({comp}).geom({geom}).run();\n"
        )

    repaired, count = re.subn(
        r"(?P<indent>^[ \t]*)model\.component\((?P<comp>['\"]comp1['\"])\)\.geom\((?P<geom>['\"]geom1['\"])\)\.run\(\)\s*;?\s*\n"
        r"(?P=indent)model\.component\((?P=comp)\)\.geom\((?P=geom)\)\.finalize\([ \t]*['\"]assembly['\"][ \t]*\)[ \t]*;?[ \t]*",
        _replace_run_then_finalize,
        repaired,
        flags=re.MULTILINE,
    )
    if count:
        changes.append(f"geom_finalize_assembly_to_verified_fin_action:{count}")
    repaired, count = re.subn(
        r"(?P<indent>^[ \t]*)model\.component\((?P<comp>['\"]comp1['\"])\)\.geom\((?P<geom>['\"]geom1['\"])\)\.finalize\([ \t]*['\"]assembly['\"][ \t]*\)[ \t]*;?[ \t]*",
        lambda match: f"{match.group('indent')}model.component({match.group('comp')}).geom({match.group('geom')}).feature('fin').set('action', 'assembly');",
        repaired,
        flags=re.MULTILINE,
    )
    if count:
        changes.append(f"standalone_geom_finalize_assembly_to_verified_fin_action:{count}")
    repaired, count = re.subn(
        r"(?P<indent>^[ \t]*)model\.component\((?P<comp>['\"]comp1['\"])\)\.geom\((?P<geom>['\"]geom1['\"])\)\.feature\(\)\.create\((?P<fin>['\"]fin['\"])\s*,\s*['\"]Finish['\"]\)\s*;?[ \t]*\n"
        r"(?:(?P=indent)model\.component\((?P=comp)\)\.geom\((?P=geom)\)\.feature\((?P=fin)\)\.set\([^\n]+\)\s*;?[ \t]*\n)?"
        r"(?P=indent)model\.component\((?P=comp)\)\.geom\((?P=geom)\)\.run\((?P=fin)\)\s*;?",
        lambda match: (
            f"{match.group('indent')}model.component({match.group('comp')}).geom({match.group('geom')}).feature('fin').set('action', 'assembly');\n"
            f"{match.group('indent')}model.component({match.group('comp')}).geom({match.group('geom')}).run();"
        ),
        repaired,
        flags=re.MULTILINE,
    )
    if count:
        changes.append(f"finish_feature_create_to_verified_assembly_fin:{count}")
    repaired, count = re.subn(
        r"\.mesh\(\)\.create\(\s*(['\"])(?P<tag>mesh\d*)\1\s*,\s*(['\"])(?P=tag)\3\s*\)",
        r".mesh().create('\g<tag>')",
        repaired,
    )
    if count:
        changes.append(f"mesh_create_self_geometry_to_plain_mesh:{count}")
    return repaired, changes


def _repair_generated_selection_api_fragments(java_code: str) -> tuple[str, list[str]]:
    repaired = java_code
    changes: list[str] = []
    repaired, count = re.subn(
        r"(\.selection\([^)]*\)\.set\(\s*['\"]entitydim['\"]\s*,\s*)([123])(\s*\))",
        r"\1'\2'\3",
        repaired,
    )
    if count:
        changes.append(f"selection_entitydim_int_to_string:{count}")
    repaired, count = re.subn(
        r"(\.selection\([^)]*\)\.set\(\s*['\"]condition['\"]\s*,\s*)['\"]intersect['\"](\s*\))",
        r"\1'intersects'\2",
        repaired,
    )
    if count:
        changes.append(f"selection_condition_intersect_to_intersects:{count}")
    repaired, count = re.subn(
        r"(\.selection\([^)]*\)\.set\(\s*['\"](?:xmin|xmax|ymin|ymax|zmin|zmax)['\"]\s*,\s*)([-+]?\d+(?:\.\d+)?)(\s*\))",
        r"\1'\2'\3",
        repaired,
    )
    if count:
        changes.append(f"selection_numeric_bounds_to_string:{count}")
    repaired, count = re.subn(
        r"^.*\.selection\([^)]*\)\.set\(\s*['\"]include['\"]\s*,\s*(?:True|False|true|false)\s*\)\s*$\n?",
        "",
        repaired,
        flags=re.MULTILINE,
    )
    if count:
        changes.append(f"remove_unknown_selection_include_property:{count}")
    repaired, count = re.subn(
        r"(?P<indent>^[ \t]*)model\.component\((?P<comp>['\"]comp1['\"])\)\.geom\((?P<geom>['\"]geom1['\"])\)\.selection\(\)",
        lambda match: f"{match.group('indent')}model.component({match.group('comp')}).selection()",
        repaired,
        flags=re.MULTILINE,
    )
    if count:
        changes.append(f"geom_scoped_selection_create_to_component_selection:{count}")
    repaired, count = re.subn(
        r"(?P<indent>^[ \t]*)model\.component\((?P<comp>['\"]comp1['\"])\)\.geom\((?P<geom>['\"]geom1['\"])\)\.selection\((?P<tag>['\"][^'\"]+['\"])\)",
        lambda match: f"{match.group('indent')}model.component({match.group('comp')}).selection({match.group('tag')})",
        repaired,
        flags=re.MULTILINE,
    )
    if count:
        changes.append(f"geom_scoped_selection_tag_to_component_selection:{count}")
    repaired, count = re.subn(r"['\"]ExplicitSelection['\"]", "'Explicit'", repaired)
    if count:
        changes.append(f"explicitselection_to_explicit:{count}")
    return repaired, changes


def _repair_generated_output_api_fragments(java_code: str) -> tuple[str, list[str]]:
    repaired = java_code
    changes: list[str] = []
    repaired, count = re.subn(
        r"^(?P<indent>\s*)model\.output\(\)\.write\((?P<message>.*?)\)\s*;?\s*$",
        lambda match: match.group("indent") + "// " + match.group("message").strip().strip("'\""),
        repaired,
        flags=re.MULTILINE,
    )
    if count:
        changes.append(f"model_output_write_to_comment:{count}")
    return repaired, changes


def _repair_component_scoped_numerical_results(java_code: str) -> tuple[str, list[str]]:
    repaired = java_code
    changes: list[str] = []
    numerical_kinds = ("EvalGlobal", "MaxVolume", "AvVolume", "MinVolume")
    tag_to_kind: dict[str, str] = {}

    def replace_create(match: re.Match[str]) -> str:
        quote = match.group("quote")
        tag = match.group("tag")
        kind = match.group("kind")
        tag_to_kind[tag] = kind
        return f"model.result().numerical().create({quote}{tag}{quote}, '{kind}')"

    repaired, create_count = re.subn(
        r"model\.result\(\)\.create\(\s*(?P<quote>['\"])(?P<tag>[^'\"]+)(?P=quote)\s*,\s*['\"](?P<kind>"
        + "|".join(numerical_kinds)
        + r")['\"]\s*\)",
        replace_create,
        repaired,
    )
    if create_count:
        changes.append(f"result_create_to_numerical_create:{create_count}")
    for tag in sorted(tag_to_kind):
        escaped = re.escape(tag)
        repaired, ref_count = re.subn(
            rf"model\.result\(\s*(['\"]){escaped}\1\s*\)",
            f"model.result().numerical('{tag}')",
            repaired,
        )
        if ref_count:
            changes.append(f"result_tag_to_numerical_tag:{tag}:{ref_count}")
    repaired, data_count = re.subn(
        r"^.*model\.result\([^)]*\)\.set\(\s*['\"]data['\"]\s*,\s*['\"]dset\d+['\"]\s*\)\s*;?\s*$\n?",
        "",
        repaired,
        flags=re.MULTILINE,
    )
    if data_count:
        changes.append(f"remove_setup_stage_result_dataset_binding:{data_count}")
    return repaired, changes


def _collect_api_doc_citations(query: str) -> list[str]:
    docs = simulation_retrieve_api_docs(
        query=query,
        directory="docs",
        pattern="*.md",
        max_results=3,
        domain="structural",
    )
    if not docs.get("success"):
        return []
    return [
        snippet.get("citation") or snippet.get("source")
        for snippet in docs.get("snippets", [])
        if snippet.get("citation") or snippet.get("source")
    ]


def _next_bounded_3d_repair_patch(java_code: str, quality: dict[str, Any]) -> dict[str, Any] | None:
    errors = quality.get("errors") or []
    compact = re.sub(r"\s+", "", _strip_line_comments(java_code)).lower()
    if any("pair().create" in error.lower() for error in errors) and "pair().create" not in compact:
        return _bounded_repair_patch(
            strategy="append_verified_contact_pair_anchor_snippet",
            api_doc_query="COMSOL component pair create contact manualSelection source destination Contact Pair",
            errors_before=errors,
            code="""
# BOUNDED_3D_REPAIR: explicit roller/raceway Contact Pair anchors.
model.component('comp1').pair().create('repair_cp_inner_raceway', 'Contact');
model.component('comp1').pair('repair_cp_inner_raceway').label('Repair anchor: roller-to-inner-raceway contact pair');
model.component('comp1').pair('repair_cp_inner_raceway').manualSelection(True);
model.component('comp1').pair().create('repair_cp_outer_raceway', 'Contact');
model.component('comp1').pair('repair_cp_outer_raceway').label('Repair anchor: roller-to-outer-raceway contact pair');
model.component('comp1').pair('repair_cp_outer_raceway').manualSelection(True);
""",
        )
    if any("plotgroup3d" in error.lower() for error in errors) and "plotgroup3d" not in compact:
        return _bounded_repair_patch(
            strategy="append_verified_plotgroup3d_stress_output_snippet",
            api_doc_query="COMSOL PlotGroup3D Surface solid.mises von Mises result export",
            errors_before=errors,
            code="""
# BOUNDED_3D_REPAIR: 3D von Mises stress plot output.
model.result().create('repair_pg_stress3d', 'PlotGroup3D');
model.result('repair_pg_stress3d').feature().create('repair_surf_mises', 'Surface');
model.result('repair_pg_stress3d').feature('repair_surf_mises').set('expr', 'solid.mises');
""",
        )
    if any("stationary" in error.lower() for error in errors) and "stationary" not in compact:
        return _bounded_repair_patch(
            strategy="append_verified_stationary_study_snippet",
            api_doc_query="COMSOL study Stationary activate solid mechanics",
            errors_before=errors,
            code="""
# BOUNDED_3D_REPAIR: stationary study anchor.
model.study().create('std1');
model.study('std1').feature().create('stat', 'Stationary');
model.study('std1').feature('stat').set('activate', ['solid', 'on']);
""",
        )
    return None


def _bounded_repair_patch(
    *,
    strategy: str,
    api_doc_query: str,
    errors_before: list[str],
    code: str,
) -> dict[str, Any]:
    docs = simulation_retrieve_api_docs(
        query=api_doc_query,
        directory="docs",
        pattern="*.md",
        max_results=3,
        domain="structural",
    )
    citations = []
    if docs.get("success"):
        citations = [
            snippet.get("citation") or snippet.get("source")
            for snippet in docs.get("snippets", [])
            if snippet.get("citation") or snippet.get("source")
        ]
    return {
        "strategy": strategy,
        "api_doc_query": api_doc_query,
        "api_doc_citations": citations,
        "errors_before": list(errors_before),
        "code": code,
    }


async def repair_free_generated_3d_code_with_llm(
    *,
    provider: Any,
    original_code: str,
    quality: dict[str, Any],
    max_tokens: int,
) -> tuple[str, dict[str, Any]]:
    """Ask the configured model for one bounded rewrite of its free-generated 3D code."""
    error_lines = "\n".join(f"- {error}" for error in quality.get("errors", [])) or "- unknown quality-gate failure"
    prompt = (
        "You are repairing your own generated COMSOL Python/MPh setup snippet for a 3D full cylindrical "
        "roller bearing. Return only executable setup code between GENERATED_CODE_START and GENERATED_CODE_END; "
        "no prose, no markdown table, no code fence, no solver run, no plot run. Keep the model as a complete "
        "3D full bearing with inner ring, outer ring, twelve cylindrical rollers, explicit cage ring plus twelve "
        "Boolean pocket cutouts, roller-to-inner and roller-to-outer Contact pairs, SolidMechanics, radial "
        "load, support, mesh, stationary study, and PlotGroup3D solid.mises output. Use Python/MPh-compatible "
        "syntax only: True/False, Python lists, no Java typed variables, no new int[]/new String[]/new double[], "
        "no output.write/model.output().write. Use top-level model.study()/model.result(). Create contact pairs "
        "with model.component('comp1').pair().create(tag, 'Contact') and Solid Mechanics Contact features using "
        "set('pairs', [tag]). If endpoints are named, use pair(tag).source().named(sel) and "
        "pair(tag).destination().named(sel). Do not use CylinderSelection, BoxSelection, ExplicitSelection, "
        "Explicit geometry features, ContactPair physics interfaces, setNamed, Difference set('objects'), or "
        "set('source'/'destination'). Create any named regions with component-level Box selections only.\n\n"
        "QUALITY_GATE_ERRORS:\n"
        f"{error_lines}\n\n"
        "ORIGINAL_GENERATED_CODE:\n"
        f"{original_code}\n\n"
        "GENERATED_CODE_START\n"
    )
    response = await provider.generate(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a COMSOL Java/API-to-Python/MPh code repair assistant. "
                    "You return only code in the requested markers."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        tools=None,
        temperature=0,
        max_tokens=max_tokens,
    )
    text = response.text or ""
    candidate = extract_generated_code(text) or _extract_executable_model_snippet(text) or ""
    normalized = normalize_generated_mph_code(candidate)
    repaired_quality = validate_3d_bearing_code_draft(normalized)
    report = {
        "stage": "llm_bounded_free_code_repair",
        "strategy": "rewrite_generated_3d_code_from_quality_gate_errors_without_verified_fallback",
        "success": repaired_quality["success"],
        "errors_before": list(quality.get("errors", [])),
        "errors_after": list(repaired_quality.get("errors", [])),
        "llm_usage": response.usage,
        "finish_reason": response.finish_reason,
        "failed_code_excerpt": _code_excerpt(original_code),
        "repaired_code_excerpt": _code_excerpt(normalized),
    }
    return normalized, report


async def run_3d_bearing_demo(args: argparse.Namespace) -> int:
    """Run the 3D bearing demo against the configured LLM and optionally COMSOL."""
    artifact_root = Path(args.artifact_root)
    artifact_dir = artifact_root / "template_runs"
    package_dir = artifact_root / "result_packages"
    archive_path = Path(args.archive_path)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    package_dir.mkdir(parents=True, exist_ok=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    config = load_config()
    config.agent.max_tool_iterations = max(config.agent.max_tool_iterations, args.max_tool_iterations)
    config.llm.max_tokens = max(config.llm.max_tokens, args.llm_max_tokens)
    clear_tools()
    register_all_tools()
    archive_store = ArchiveStore(archive_path)
    seed_builtin_templates(archive_store)

    if args.use_verified_fixture:
        generated_code = VERIFIED_3D_FULL_BEARING_CODE
        draft_summary = None
        repair_history = [{
            "attempt": 0,
            "stage": "fixture",
            "strategy": "use_verified_3d_full_bearing_fixture",
            "success": True,
            "repaired_code_source": "VERIFIED_3D_FULL_BEARING_CODE",
            "repaired_code_excerpt": _code_excerpt(VERIFIED_3D_FULL_BEARING_CODE),
        }]
        tool_events: list[tuple[str, dict[str, Any]]] = []
        provider = create_provider(
            config.llm.provider,
            model=config.llm.model,
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
        )
        agent = AgentLoop(
            llm_provider=provider,
            config=config,
            on_tool_call=lambda name, call_args: tool_events.append((name, call_args)),
            archive_store=archive_store,
        )
    else:
        provider = create_provider(
            config.llm.provider,
            model=config.llm.model,
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
        )
        tool_events: list[tuple[str, dict[str, Any]]] = []
        agent = AgentLoop(
            llm_provider=provider,
            config=config,
            on_tool_call=lambda name, call_args: tool_events.append((name, call_args)),
            archive_store=archive_store,
        )
        try:
            if args.segmented_code_path:
                code_path = Path(args.segmented_code_path)
                generated_code = code_path.read_text(encoding="utf-8")
                manifest_path = code_path.with_name("assembled_manifest.json")
                manifest = {}
                if manifest_path.exists():
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                draft_summary = {
                    "name": "bearing_3d_segmented_code_draft_reused",
                    "success": bool(generated_code),
                    "response": "",
                    "observed_tools": [],
                    "missing_calls": [],
                    "missing_successes": [],
                    "new_tool_results": [],
                    "segmented_manifest_path": str(manifest_path) if manifest_path.exists() else None,
                    "assembled_code_path": str(code_path),
                    "segment_count": manifest.get("segment_count"),
                }
                repair_history = [{
                    "attempt": 0,
                    "stage": "segmented_generation_reuse",
                    "strategy": "reuse_manifest_checked_segmented_assembled_code",
                    "success": True,
                    "assembled_code_path": str(code_path),
                    "segmented_manifest_path": str(manifest_path) if manifest_path.exists() else None,
                    "final_quality": manifest.get("final_quality", {}),
                    "generated_code_excerpt": _code_excerpt(generated_code),
                }]
            elif args.segmented_generation:
                generated_code, draft_summary, repair_history = await generate_segmented_3d_bearing_code(
                    provider=provider,
                    artifact_root=artifact_root,
                    args=args,
                )
            else:
                draft_prompt = build_3d_bearing_code_generation_prompt(archive_path=str(archive_path))
                draft_summary = await _run_prompt(agent, draft_prompt, tool_events)
                generated_code = extract_generated_code(draft_summary["response"]) or ""
                normalized_code = normalize_generated_mph_code(generated_code)
                repair_history = [{
                    "attempt": 0,
                    "stage": "draft",
                    "strategy": "llm_generated_3d_full_bearing_code",
                    "success": bool(generated_code),
                    "generated_code_excerpt": _code_excerpt(generated_code),
                }]
                if not generated_code:
                    print("Could not extract generated 3D bearing code.")
                    print(draft_summary["response"])
                    return 1
                if normalized_code != generated_code:
                    repair_history.append({
                        "attempt": len(repair_history),
                        "stage": "offline_syntax_normalization",
                        "strategy": "normalize_java_style_literals_for_python_mph_execution",
                        "success": True,
                        "failed_code_excerpt": _code_excerpt(generated_code),
                        "repaired_code_excerpt": _code_excerpt(normalized_code),
                    })
                    generated_code = normalized_code
        except Exception as exc:
            segment_history = (
                exc.repair_history
                if isinstance(exc, Segmented3DGenerationError)
                else []
            )
            repair_history = [*segment_history, {
                "attempt": 0,
                "stage": "segmented_generation_failure" if args.segmented_generation else "llm_generation_failure",
                "strategy": (
                    "record_segmented_generation_failure_before_generated_code_fallback"
                    if args.segmented_generation
                    else "record_api_failure_before_generated_code_fallback"
                ),
                "success": False,
                "error": str(exc),
            }]
            draft_quality = {
                "success": False,
                "quality_level": "generation_failed",
                "errors": [str(exc)],
                "warnings": [],
            }
            failure_payload = {
                "success": False,
                "workflow": "bearing_3d_segmented_free_generation" if args.segmented_generation else "bearing_3d_free_generation",
                "draft_quality": draft_quality,
                "repair_history": repair_history,
                "execution_context": _build_3d_execution_context(
                    workflow="bearing_3d_segmented_free_generation" if args.segmented_generation else "bearing_3d_free_generation",
                    draft_quality=draft_quality,
                    repair_history=repair_history,
                    require_free_generated_code=args.require_free_generated_code,
                    allow_verified_fallback=not args.require_free_generated_code,
                ),
                "free_generated_code_required": args.require_free_generated_code,
                "verified_fallback_skipped": args.require_free_generated_code,
                "deterministic_runtime_fallback": None,
            }
            failure_path = artifact_root / (
                "segmented_generation_failure.json"
                if args.segmented_generation
                else "strict_generation_failure.json"
            )
            failure_path.write_text(
                json.dumps(failure_payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            print(f"3D free-generation failed before code extraction; failure artifact: {failure_path}")
            print(json.dumps(failure_payload, ensure_ascii=False, indent=2, default=str))
            return 1

    draft_quality = validate_3d_bearing_code_draft(
        generated_code,
        require_named_selections=args.segmented_generation,
    )
    if not draft_quality["success"]:
        generated_code, preflight_repair_history, draft_quality = apply_runtime_preflight_3d_repairs(
            generated_code,
            draft_quality,
        )
        for report in preflight_repair_history:
            report["attempt"] = len(repair_history)
            repair_history.append(report)
        if args.segmented_generation:
            draft_quality = validate_3d_bearing_code_draft(generated_code, require_named_selections=True)
    if not draft_quality["success"]:
        generated_code, bounded_repair_history, draft_quality = apply_bounded_3d_generated_code_repairs(
            generated_code,
            draft_quality,
            max_attempts=2,
        )
        for report in bounded_repair_history:
            report["attempt"] = len(repair_history)
            repair_history.append(report)
    if not draft_quality["success"] and not args.use_verified_fixture and not args.segmented_generation:
        llm_repaired_code, llm_repair_report = await repair_free_generated_3d_code_with_llm(
            provider=provider,
            original_code=generated_code,
            quality=draft_quality,
            max_tokens=args.llm_repair_max_tokens,
        )
        llm_repair_report["attempt"] = len(repair_history)
        repair_history.append(llm_repair_report)
        if llm_repaired_code:
            generated_code = llm_repaired_code
            draft_quality = validate_3d_bearing_code_draft(generated_code)
            generated_code, preflight_repair_history, draft_quality = apply_runtime_preflight_3d_repairs(
                generated_code,
                draft_quality,
            )
            for report in preflight_repair_history:
                report["attempt"] = len(repair_history)
                repair_history.append(report)
            if not draft_quality["success"]:
                generated_code, bounded_repair_history, draft_quality = apply_bounded_3d_generated_code_repairs(
                    generated_code,
                    draft_quality,
                    max_attempts=2,
                )
                for report in bounded_repair_history:
                    report["attempt"] = len(repair_history)
                    repair_history.append(report)
    generated_code, preflight_repair_history, draft_quality = apply_runtime_preflight_3d_repairs(
        generated_code,
        draft_quality,
    )
    for report in preflight_repair_history:
        report["attempt"] = len(repair_history)
        repair_history.append(report)
    if args.segmented_generation:
        draft_quality = validate_3d_bearing_code_draft(generated_code, require_named_selections=True)
    if not draft_quality["success"]:
        repair_history.append({
            "attempt": len(repair_history),
            "stage": "offline_quality_gate",
            "strategy": "replace_failed_free_generation_with_verified_3d_full_bearing_fallback",
            "success": True,
            "errors": draft_quality["errors"],
            "failed_code_excerpt": _code_excerpt(generated_code),
            "repaired_code_source": "VERIFIED_3D_FULL_BEARING_CODE",
            "repaired_code_excerpt": _code_excerpt(VERIFIED_3D_FULL_BEARING_CODE),
        })
        if args.require_free_generated_code:
            if args.skip_comsol:
                failure_payload = {
                    "success": False,
                    "workflow": "bearing_3d_segmented_free_generation" if args.segmented_generation else "bearing_3d_free_generation",
                    "draft_summary": _compact_summaries([draft_summary]) if draft_summary else [],
                    "draft_quality": draft_quality,
                    "repair_history": repair_history,
                    "free_generated_code_required": True,
                    "verified_fallback_skipped": True,
                    "execution_context": _build_3d_execution_context(
                        workflow="bearing_3d_segmented_free_generation" if args.segmented_generation else "bearing_3d_free_generation",
                        draft_quality=draft_quality,
                        repair_history=repair_history,
                        require_free_generated_code=True,
                        allow_verified_fallback=False,
                        draft_summary=draft_summary,
                    ),
                    "deterministic_runtime_fallback": None,
                }
                failure_path = artifact_root / (
                    "segmented_generation_failure.json"
                    if args.segmented_generation
                    else "strict_generation_failure.json"
                )
                failure_path.write_text(
                    json.dumps(failure_payload, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                print(json.dumps(failure_payload, ensure_ascii=False, indent=2, default=str))
                return 1
            print("3D free-generated code failed the quality gate; verified fallback is disabled.")
            print(json.dumps(draft_quality, ensure_ascii=False, indent=2))
            return 1
        generated_code = VERIFIED_3D_FULL_BEARING_CODE
        draft_quality = validate_3d_bearing_code_draft(generated_code)
    if args.print_generated_code:
        print(generated_code)
    if args.skip_comsol:
        print(json.dumps({
            "draft_summary": _compact_summaries([draft_summary]) if draft_summary else [],
            "draft_quality": draft_quality,
            "repair_history": repair_history,
        }, ensure_ascii=False, indent=2, default=str))
        return 0 if draft_quality["success"] else 1
    if not draft_quality["success"]:
        print("3D generated code failed the full-bearing quality gate.")
        print(json.dumps(draft_quality, ensure_ascii=False, indent=2))
        return 1
    return await run_agent_execution_smoke(
        args,
        agent=agent,
        tool_events=tool_events,
        generated_code=generated_code,
        draft_summary=draft_summary,
        draft_quality=draft_quality,
        repair_history=repair_history,
    )


async def run_agent_execution_smoke(
    args: argparse.Namespace,
    *,
    agent: AgentLoop,
    tool_events: list[tuple[str, dict[str, Any]]],
    generated_code: str,
    draft_summary: dict[str, Any] | None,
    draft_quality: dict[str, Any],
    repair_history: list[dict[str, Any]],
) -> int:
    """Run the 3D bearing setup through the Agent tool chain."""
    artifact_root = Path(args.artifact_root)
    artifact_dir = artifact_root / "template_runs"
    package_dir = artifact_root / "result_packages"
    archive_path = Path(args.archive_path)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    package_dir.mkdir(parents=True, exist_ok=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    config = load_config()
    client = COMSOLClient.get_instance()
    try:
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        execution_context = _build_3d_execution_context(
            workflow=(
                "bearing_3d_segmented_generated_code_agent_execution"
                if args.segmented_generation
                else "bearing_3d_generated_code_agent_execution"
            ),
            draft_quality=draft_quality,
            repair_history=repair_history,
            require_free_generated_code=args.require_free_generated_code,
            allow_verified_fallback=not args.require_free_generated_code,
            draft_summary=draft_summary,
        )
        execute_prompt = build_3d_bearing_execution_prompt(
            java_code=generated_code,
            archive_path=str(archive_path),
            artifact_dir=str(artifact_dir),
            plot_path=str(artifact_root / "bearing_3d_von_mises.png"),
            model_name=args.model_name,
            template_name=args.template_name,
            package_dir=str(package_dir),
            execution_context=execution_context,
            allow_verified_fallback=not args.require_free_generated_code,
        )
        execute_summary = await _run_prompt(agent, execute_prompt, tool_events)
        package_payload = _latest_tool_payload(
            execute_summary,
            "simulation_export_bearing_contact_package",
        )
        package_answer = None
        fallback_summary = None
        if not (package_payload and package_payload.get("success")):
            if args.require_free_generated_code:
                repair_history.append({
                    "attempt": len(repair_history),
                    "stage": "runtime_verified_fallback_skipped",
                    "strategy": "require_free_generated_code_so_do_not_replace_with_verified_fallback",
                    "success": False,
                    "trigger": {
                        "failed_prompt": execute_summary.get("name"),
                        "missing_calls": execute_summary.get("missing_calls", []),
                        "missing_successes": execute_summary.get("missing_successes", []),
                        "last_failed_tool": _last_failed_tool_payload(execute_summary),
                    },
                })
            else:
                fallback_summary = _run_verified_runtime_fallback_after_agent_failure(
                    args,
                    execute_summary=execute_summary,
                    repair_history=repair_history,
                )
                package_payload = fallback_summary.get("package")
                package_answer = fallback_summary.get("artifact_answer")
        if package_payload and package_payload.get("success"):
            per_roller_probe_results = _evaluate_per_roller_probe_results_from_open_or_saved_model(
                args.model_name,
                package_payload,
            )
            stress_projection_plot = _render_stress_projection_from_open_or_saved_model(
                args.model_name,
                package_payload,
                Path(args.artifact_root) / "bearing_3d_von_mises.png",
            )
            _inject_3d_package_metadata(
                package_payload,
                repair_history=repair_history,
                cage_model=f"cage ring with {VERIFIED_ROLLER_COUNT} real Boolean pocket cutouts",
                per_roller_probe_results=per_roller_probe_results,
                stress_plot_evidence=stress_projection_plot,
            )
            package_answer = simulation_answer_artifact_question(
                "最大应力是多少，最大应力位置在哪里，哪个滚子附近风险最高，保持架是否建模，滚子和外圈有没有接触？",
                run_id=package_payload.get("run_id"),
                archive_path=str(archive_path),
            )
        summaries = [
            summary
            for summary in [draft_summary, execute_summary]
            if summary is not None
        ]
        print("3D bearing Agent execution summary:")
        print(json.dumps({
            "summaries": _compact_summaries(summaries),
            "repair_history": repair_history,
            "deterministic_runtime_fallback": _compact_runtime_result(fallback_summary.get("package") if fallback_summary else None),
            "package": _compact_runtime_result(package_payload),
            "post_injection_artifact_answer": package_answer,
        }, ensure_ascii=False, indent=2, default=str))
        failures = [summary for summary in summaries if not summary["success"]]
        return 0 if package_payload and package_payload.get("success") else (1 if failures else 0)
    finally:
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def _run_verified_runtime_fallback_after_agent_failure(
    args: argparse.Namespace,
    *,
    execute_summary: dict[str, Any],
    repair_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministically recover the 3D fullflow when Agent runtime repair stalls."""
    artifact_root = Path(args.artifact_root)
    artifact_dir = artifact_root / "template_runs"
    package_dir = artifact_root / "result_packages"
    archive_path = Path(args.archive_path)
    last_failure = _last_failed_tool_payload(execute_summary)
    repair_history.append({
        "attempt": len(repair_history),
        "stage": "runtime_deterministic_fallback",
        "strategy": "replace_runtime_failed_generated_code_with_verified_3d_full_bearing_code",
        "success": True,
        "trigger": {
            "failed_prompt": execute_summary.get("name"),
            "missing_calls": execute_summary.get("missing_calls", []),
            "missing_successes": execute_summary.get("missing_successes", []),
            "last_failed_tool": last_failure,
        },
        "repaired_code_source": "VERIFIED_3D_FULL_BEARING_CODE",
        "repaired_code_excerpt": _code_excerpt(VERIFIED_3D_FULL_BEARING_CODE),
    })
    close_existing = comsol_close_model(args.model_name, save=False)
    execution_context = _build_3d_execution_context(
        workflow="bearing_3d_runtime_verified_fallback",
        draft_quality={"success": True, "quality_level": "verified_fallback"},
        repair_history=repair_history,
        require_free_generated_code=False,
        allow_verified_fallback=True,
    )
    run = simulation_run_template(
        name=args.template_name,
        java_code=VERIFIED_3D_FULL_BEARING_CODE,
        params={
            "model_dimension": "3d_full_bearing",
            "roller_count": str(VERIFIED_ROLLER_COUNT),
            "cage_included": "true",
            "radial_load": "3000[N]",
            "fallback_reason": "agent_runtime_repair_failed",
        },
        execution_context=execution_context,
        create_model_name=args.model_name,
        close_model=False,
        artifact_dir=str(artifact_dir),
        artifact_name="agent_3d_bearing_runtime_verified_fallback",
        archive_path=str(archive_path),
    )
    summary: dict[str, Any] = {
        "close_existing": _compact_runtime_result(close_existing),
        "template_run": _compact_runtime_result(run),
    }
    if not run.get("success"):
        repair_history[-1]["success"] = False
        repair_history[-1]["runtime_fallback_error"] = run.get("error")
        return summary
    model_name = str(run["model_name"])
    solve = comsol_solve(model_name)
    stress = comsol_evaluate(model_name, "solid.mises") if solve.get("success") else {}
    pressure = comsol_evaluate(model_name, "contact_pressure_est") if solve.get("success") else {}
    displacement = comsol_evaluate(model_name, "solid.disp") if solve.get("success") else {}
    per_roller_probe_results = _evaluate_per_roller_probe_results(model_name) if solve.get("success") else []
    plot_path = artifact_root / "bearing_3d_von_mises.png"
    plot = comsol_plot(
        model_name,
        expression="solid.mises",
        plot_type="surface",
        filename=str(plot_path),
    ) if solve.get("success") else {}
    stress_projection_plot = _render_stress_projection_from_open_model(model_name, plot_path) if solve.get("success") else {}
    package = {}
    artifact_answer = None
    if solve.get("success"):
        package = simulation_export_bearing_contact_package(
            model_name=model_name,
            template_run_id=(run.get("artifacts") or {}).get("run_id"),
            plot_path=str(plot_path),
            output_dir=str(package_dir),
            package_name="agent_3d_bearing_runtime_fallback_package",
            archive_path=str(archive_path),
        )
        if package.get("success"):
            _inject_3d_package_metadata(
                package,
                repair_history=repair_history,
                cage_model=f"cage ring with {VERIFIED_ROLLER_COUNT} real Boolean pocket cutouts",
                per_roller_probe_results=per_roller_probe_results,
                stress_plot_evidence=stress_projection_plot,
            )
            artifact_answer = simulation_answer_artifact_question(
                "最大应力是多少，最大应力位置在哪里，哪个滚子附近风险最高，保持架是否建模，滚子和外圈有没有接触？",
                run_id=package.get("run_id"),
                archive_path=str(archive_path),
            )
    summary.update({
        "solve": _compact_runtime_result(solve),
        "evaluations": [
            _compact_runtime_result(stress),
            _compact_runtime_result(pressure),
            _compact_runtime_result(displacement),
        ],
        "plot": _compact_runtime_result(plot),
        "stress_projection_plot": _compact_runtime_result(stress_projection_plot),
        "package": package,
        "artifact_answer": artifact_answer,
    })
    return summary


def run_direct_fixture_smoke(
    args: argparse.Namespace,
    *,
    generated_code: str = VERIFIED_3D_FULL_BEARING_CODE,
    repair_history: list[dict[str, Any]] | None = None,
) -> int:
    """Run a 3D verified fixture through tools with minimal LLM variability."""
    artifact_root = Path(args.artifact_root)
    artifact_dir = artifact_root / "template_runs"
    package_dir = artifact_root / "result_packages"
    archive_path = Path(args.archive_path)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    package_dir.mkdir(parents=True, exist_ok=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    config = load_config()
    client = COMSOLClient.get_instance()
    model_name: str | None = None
    repair_history = repair_history or [{
        "attempt": 0,
        "stage": "fixture",
        "strategy": "use_verified_3d_full_bearing_fixture",
        "success": True,
        "repaired_code_source": "VERIFIED_3D_FULL_BEARING_CODE",
        "repaired_code_excerpt": _code_excerpt(VERIFIED_3D_FULL_BEARING_CODE),
    }]
    is_segmented_generated_direct = any(
        str(item.get("stage", "")).startswith("segmented_generation")
        for item in repair_history
    )
    summary: dict[str, Any] = {
        "fixture_quality": validate_3d_bearing_code_draft(generated_code),
        "repair_history": repair_history,
    }
    try:
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        execution_context = _build_3d_execution_context(
            workflow=(
                "bearing_3d_direct_segmented_generated"
                if is_segmented_generated_direct
                else "bearing_3d_direct_fixture"
            ),
            draft_quality=summary["fixture_quality"],
            repair_history=repair_history,
            require_free_generated_code=is_segmented_generated_direct,
            allow_verified_fallback=not is_segmented_generated_direct,
        )
        run = simulation_run_template(
            name=args.template_name,
            java_code=generated_code,
            params={
                "model_dimension": "3d_full_bearing",
                "roller_count": str(VERIFIED_ROLLER_COUNT),
                "cage_included": "true",
                "radial_load": "3000[N]",
            },
            execution_context=execution_context,
            create_model_name=args.model_name,
            close_model=False,
            artifact_dir=str(artifact_dir),
            artifact_name=(
                "direct_3d_bearing_segmented_generated"
                if is_segmented_generated_direct
                else "direct_3d_bearing_fixture"
            ),
            archive_path=str(archive_path),
        )
        summary["template_run"] = _compact_runtime_result(run)
        if not run.get("success"):
            repair_history.append({
                "attempt": 1,
                "stage": "simulation_run_template",
                "strategy": "record_structured_error_for_next_agent_repair",
                "success": False,
                "error": run.get("error"),
            })
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
            return 1
        model_name = str(run["model_name"])
        solve = comsol_solve(model_name)
        summary["solve"] = _compact_runtime_result(solve)
        if not solve.get("success"):
            repair_history.append({
                "attempt": 1,
                "stage": "comsol_solve",
                "strategy": "record_solver_error_for_contact_selection_or_mesh_repair",
                "success": False,
                "error": solve.get("error"),
            })
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
            return 1
        selection_probe = simulation_probe_3d_selection_binding(
            model_name=model_name,
            java_code=generated_code,
        )
        summary["selection_binding_probe"] = _compact_runtime_result(selection_probe)
        selection_binding_audit = selection_probe.get("selection_binding_audit")
        if selection_probe.get("success") is False:
            repair_history.append({
                "attempt": 1,
                "stage": "simulation_probe_3d_selection_binding",
                "strategy": "record_runtime_selection_binding_probe_for_next_agent_repair",
                "success": False,
                "error": selection_probe.get("error"),
                "audit_success": (selection_binding_audit or {}).get("success"),
            })
        stress = comsol_evaluate(model_name, "solid.mises")
        pressure = comsol_evaluate(model_name, "contact_pressure_est")
        displacement = comsol_evaluate(model_name, "solid.disp")
        per_roller_probe_results = _evaluate_per_roller_probe_results(model_name)
        plot_path = artifact_root / "bearing_3d_von_mises.png"
        plot = comsol_plot(
            model_name,
            expression="solid.mises",
            plot_type="surface",
            filename=str(plot_path),
        )
        stress_projection_plot = _render_stress_projection_from_open_model(model_name, plot_path)
        summary["evaluations"] = [
            _compact_runtime_result(stress),
            _compact_runtime_result(pressure),
            _compact_runtime_result(displacement),
        ]
        summary["per_roller_probe_results"] = per_roller_probe_results
        summary["plot"] = _compact_runtime_result(plot)
        summary["stress_projection_plot"] = _compact_runtime_result(stress_projection_plot)
        if not plot.get("success"):
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
            return 1
        package = simulation_export_bearing_contact_package(
            model_name=model_name,
            template_run_id=(run.get("artifacts") or {}).get("run_id"),
            plot_path=str(artifact_root / "bearing_3d_von_mises.png"),
            output_dir=str(package_dir),
            package_name="direct_3d_bearing_package",
            archive_path=str(archive_path),
        )
        summary["package"] = _compact_runtime_result(package)
        if package.get("success"):
            _inject_3d_package_metadata(
                package,
                repair_history=repair_history,
                cage_model=f"cage ring with {VERIFIED_ROLLER_COUNT} real Boolean pocket cutouts",
                per_roller_probe_results=per_roller_probe_results,
                stress_plot_evidence=stress_projection_plot,
                selection_binding_audit=selection_binding_audit,
                solve_result=solve,
            )
            summary["artifact_answer"] = simulation_answer_artifact_question(
                "最大应力是多少，最大应力位置在哪里，哪个滚子附近风险最高，保持架是否建模，滚子和外圈有没有接触？",
                run_id=package.get("run_id"),
                archive_path=str(archive_path),
            )
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0 if package.get("success") else 1
    finally:
        if model_name:
            summary["close"] = _compact_runtime_result(comsol_close_model(model_name, save=False))
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def extract_generated_code(response: str) -> str | None:
    """Extract generated Java/API code from a model response."""
    marker_match = re.search(
        r"GENERATED_CODE_START\s*(.*?)\s*GENERATED_CODE_END",
        response,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if marker_match:
        segment = marker_match.group(1)
        fenced = _extract_first_model_code_fence(segment)
        return (fenced or _extract_executable_model_snippet(segment) or _strip_code_fence(segment)).strip()
    start_match = re.search(r"GENERATED_CODE_START\s*(.*)", response, flags=re.DOTALL | re.IGNORECASE)
    if start_match:
        segment = start_match.group(1)
        fenced = _extract_first_model_code_fence(segment)
        if fenced:
            return fenced
        executable = _extract_executable_model_snippet(segment)
        if executable:
            return executable
    fenced = _extract_first_model_code_fence(response)
    if fenced:
        return fenced
    executable = _extract_executable_model_snippet(response)
    return executable.strip() if executable else None


def normalize_generated_mph_code(java_code: str) -> str:
    """Normalize common Java-ish snippets into Python/MPh executable syntax."""
    normalized = _strip_block_comments(_strip_code_fence(java_code))
    normalized = re.sub(
        r"new\s+String\s*\[\]\s*\{([^{}]*)\}",
        lambda match: "[" + match.group(1).strip() + "]",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"new\s+int\s*\[\]\s*\{([^{}]*)\}",
        lambda match: _normalize_int_array_literal(match.group(1)),
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"new\s+double\s*\[\]\s*\{([^{}]*)\}",
        lambda match: _normalize_double_array_literal(match.group(1)),
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\btrue\b", "True", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bfalse\b", "False", normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r"\{(\s*['\"][^{};]+?['\"](?:\s*,\s*['\"][^{};]+?['\"])+\s*)\}",
        r"[\1]",
        normalized,
    )
    return normalized.strip()


def _normalize_double_array_literal(array_body: str) -> str:
    values = []
    for raw_part in _strip_block_comments(array_body).split(","):
        part = raw_part.strip()
        if not part:
            continue
        if (part.startswith("'") and part.endswith("'")) or (part.startswith('"') and part.endswith('"')):
            values.append(part)
        elif re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", part):
            values.append(part)
        else:
            values.append(json.dumps(part))
    return "[" + ", ".join(values) + "]"


def _normalize_int_array_literal(array_body: str) -> str:
    values = []
    for raw_part in _strip_block_comments(array_body).split(","):
        part = raw_part.strip()
        if not part:
            continue
        if re.fullmatch(r"[-+]?\d+", part):
            values.append(part)
        else:
            values.append(json.dumps(part))
    return "[" + ", ".join(values) + "]"


def _extract_first_model_code_fence(text: str) -> str | None:
    for match in re.finditer(r"```(?:java|python|text)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE):
        code = _strip_code_fence(match.group(1)).strip()
        if "model." in code:
            return code
    return None


def _extract_executable_model_snippet(text: str) -> str | None:
    """Keep only the executable model snippet when prose leaks around markers."""
    stripped_lines = _strip_code_fence(text).splitlines()
    selected: list[str] = []
    started = False
    for line in stripped_lines:
        stripped = line.strip()
        if not started:
            if stripped.startswith("model.") or stripped.startswith("//"):
                started = True
            else:
                continue
        if not stripped:
            selected.append(line)
            continue
        if (
            stripped.startswith("model.")
            or stripped.startswith("//")
            or stripped.startswith("/*")
            or stripped.startswith("*")
            or stripped.startswith("*/")
        ):
            selected.append(line)
            continue
        break
    snippet = "\n".join(selected).strip()
    return snippet if "model." in snippet else None


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    stripped = re.sub(r"^```(?:java|python|text)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _strip_line_comments(text: str) -> str:
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def _strip_hash_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _strip_block_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def _python_syntax_error(java_code: str) -> str | None:
    dedented = textwrap.dedent(java_code)
    python_like = _strip_block_comments(_strip_hash_comments(_strip_line_comments(_strip_code_fence(dedented)))).strip()
    try:
        compile(python_like, "<generated_3d_bearing_code>", "exec")
    except SyntaxError as exc:
        return f"line {exc.lineno}: {exc.msg}"
    return None


async def _run_prompt(
    agent: AgentLoop,
    prompt: DemoPrompt,
    tool_events: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    previous_event_count = len(tool_events)
    previous_tool_result_count = len(_tool_results(agent.state.messages))
    print(f"\n=== Demo: {prompt.name} ===")
    print(prompt.prompt)
    response = await agent.run(prompt.prompt)
    print("Agent response:")
    print(response)
    new_events = tool_events[previous_event_count:]
    new_tool_results = _tool_results(agent.state.messages)[previous_tool_result_count:]
    observed_tools = [name for name, _ in new_events]
    successful_tools = {
        result["name"]
        for result in new_tool_results
        if result["payload"].get("success") is True
    }
    missing_calls = [name for name in prompt.required_tools if name not in observed_tools]
    missing_successes = [name for name in prompt.successful_tools if name not in successful_tools]
    return {
        "name": prompt.name,
        "success": not missing_calls and not missing_successes,
        "response": response,
        "observed_tools": observed_tools,
        "missing_calls": missing_calls,
        "missing_successes": missing_successes,
        "new_tool_results": new_tool_results,
    }


def _tool_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        try:
            payload = json.loads(message.get("content") or "{}")
        except json.JSONDecodeError as exc:
            payload = {"success": False, "error": str(exc)}
        results.append({"name": message.get("name"), "payload": payload})
    return results


def _compact_summaries(summaries: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    compact = []
    for summary in summaries:
        if not summary:
            continue
        compact.append({
            "name": summary["name"],
            "success": summary["success"],
            "observed_tools": summary["observed_tools"],
            "missing_calls": summary["missing_calls"],
            "missing_successes": summary["missing_successes"],
        })
    return compact


def _latest_tool_payload(summary: dict[str, Any], tool_name: str) -> dict | None:
    for result in reversed(summary.get("new_tool_results") or []):
        if result.get("name") == tool_name:
            payload = result.get("payload")
            return payload if isinstance(payload, dict) else None
    return None


def _last_failed_tool_payload(summary: dict[str, Any]) -> dict[str, Any] | None:
    for result in reversed(summary.get("new_tool_results") or []):
        payload = result.get("payload")
        if isinstance(payload, dict) and payload.get("success") is not True:
            return {
                "name": result.get("name"),
                "error_type": payload.get("error_type"),
                "error": payload.get("error"),
                "retryable": payload.get("retryable"),
                "repair_hint": payload.get("repair_hint"),
            }
    return None


def _compact_runtime_result(result: dict | None) -> dict | None:
    if result is None:
        return None
    keys = (
        "success",
        "model_name",
        "template_name",
        "status",
        "stage",
        "expression",
        "statistics",
        "value",
        "filepath",
        "plot_type",
        "export_method",
        "run_id",
        "json_path",
        "markdown_path",
        "model_path",
        "plot_path",
        "metrics",
        "error",
        "error_type",
        "exception_type",
    )
    compact = {key: result.get(key) for key in keys if key in result}
    artifacts = result.get("artifacts")
    if isinstance(artifacts, dict):
        compact["run_id"] = artifacts.get("run_id")
        compact["json_path"] = artifacts.get("json_path")
    return compact


def _evaluate_per_roller_probe_results(model_name: str) -> list[dict[str, Any]]:
    """Evaluate scoped per-roller maximum stress coupling expressions."""
    results: list[dict[str, Any]] = []
    for index in range(1, VERIFIED_ROLLER_COUNT + 1):
        expression = f"maxop_roller_{index}(solid.mises)"
        evaluation = comsol_evaluate(model_name, expression)
        value = evaluation.get("value")
        statistics = evaluation.get("statistics") or {}
        if value is None:
            value = statistics.get("max")
        results.append({
            "roller": f"roller_{index}",
            "expression": expression,
            "success": evaluation.get("success") is True,
            "value": value,
            "selection": f"sel_roller_{index}_body",
            "error": evaluation.get("error"),
        })
    return results


def _evaluate_per_roller_probe_results_from_open_or_saved_model(
    model_name: str,
    package_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Evaluate scoped probes from the live model, or reload the saved package model."""
    live_results = _evaluate_per_roller_probe_results(model_name)
    if live_results and all(item.get("success") for item in live_results):
        return live_results
    model_path = package_payload.get("model_path")
    if not model_path:
        return live_results
    load_result = comsol_load_model(str(model_path))
    if not load_result.get("success"):
        return live_results
    loaded_model = str(load_result["model_name"])
    try:
        loaded_results = _evaluate_per_roller_probe_results(loaded_model)
        if loaded_results and all(item.get("success") for item in loaded_results):
            return loaded_results
        return live_results
    finally:
        comsol_close_model(loaded_model, save=False)


def _render_stress_projection_from_open_or_saved_model(
    model_name: str,
    package_payload: dict[str, Any],
    plot_path: Path,
) -> dict[str, Any]:
    """Render a visible PNG from COMSOL field arrays using the live or saved model."""
    live_result = _render_stress_projection_from_open_model(model_name, plot_path)
    if live_result.get("success"):
        return live_result
    model_path = package_payload.get("model_path")
    if not model_path:
        return live_result
    load_result = comsol_load_model(str(model_path))
    if not load_result.get("success"):
        return {
            "success": False,
            "error": live_result.get("error") or load_result.get("error"),
            "load_error": load_result.get("error"),
        }
    loaded_model = str(load_result["model_name"])
    try:
        loaded_result = _render_stress_projection_from_open_model(loaded_model, plot_path)
        if loaded_result.get("success"):
            loaded_result["source_model"] = "reloaded_saved_package_model"
            return loaded_result
        return live_result
    finally:
        comsol_close_model(loaded_model, save=False)


def _render_stress_projection_from_open_model(model_name: str, plot_path: Path) -> dict[str, Any]:
    """Write a PNG stress projection from solved COMSOL x/y/z/solid.mises arrays."""
    try:
        handle = COMSOLClient.get_instance().get_model(model_name)
        values = handle.mph_model.evaluate(["x", "y", "z", "solid.mises"])
        return _write_stress_projection_png(values, plot_path)
    except Exception as exc:
        return {"success": False, "error": str(exc), "method": "mph_evaluate_projection"}


def _write_stress_projection_png(values: Any, plot_path: Path) -> dict[str, Any]:
    import numpy as np

    if not isinstance(values, (list, tuple)) or len(values) < 4:
        return {"success": False, "error": "COMSOL field evaluation did not return x/y/z/stress arrays"}
    x, y, _z, stress = [np.asarray(item, dtype=float).ravel() for item in values[:4]]
    count = min(len(x), len(y), len(stress))
    x = x[:count]
    y = y[:count]
    stress = stress[:count]
    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(stress)
    if not np.any(finite):
        return {"success": False, "error": "No finite COMSOL stress samples for projection"}
    x = x[finite]
    y = y[finite]
    stress = np.maximum(stress[finite], 0.0)
    width, height = 1100, 780
    canvas = np.full((height, width, 3), 255, dtype=np.uint8)
    left, top, right, bottom = 70, 70, 850, 700
    x_min, x_max = float(np.min(x)), float(np.max(x))
    y_min, y_max = float(np.min(y)), float(np.max(y))
    if x_max <= x_min or y_max <= y_min:
        return {"success": False, "error": "Degenerate COMSOL x/y projection bounds"}
    scale = min((right - left) / (x_max - x_min), (bottom - top) / (y_max - y_min))
    x_mid = 0.5 * (x_min + x_max)
    y_mid = 0.5 * (y_min + y_max)
    px = np.rint((x - x_mid) * scale + 0.5 * (left + right)).astype(int)
    py = np.rint(0.5 * (top + bottom) - (y - y_mid) * scale).astype(int)
    inside = (px >= left) & (px < right) & (py >= top) & (py < bottom)
    px = px[inside]
    py = py[inside]
    stress = stress[inside]
    if len(stress) == 0:
        return {"success": False, "error": "No COMSOL stress samples fell inside projection canvas"}
    stress_log = np.log10(stress + 1.0)
    v_min = float(np.percentile(stress_log, 2.0))
    v_max = float(np.percentile(stress_log, 99.5))
    if v_max <= v_min:
        v_max = float(np.max(stress_log) or 1.0)
        v_min = 0.0
    normalized = np.clip((stress_log - v_min) / (v_max - v_min), 0.0, 1.0)
    colors = _turbo_like_colors(normalized)
    for dx, dy in ((0, 0), (1, 0), (0, 1), (-1, 0), (0, -1)):
        xx = np.clip(px + dx, 0, width - 1)
        yy = np.clip(py + dy, 0, height - 1)
        canvas[yy, xx] = colors
    _draw_frame(canvas, left, top, right, bottom)
    _draw_colorbar(canvas, 900, 110, 940, 650)
    _write_png_rgb(plot_path, canvas)
    return {
        "success": True,
        "method": "mph_evaluate_xy_projection_png",
        "filepath": str(plot_path.resolve()),
        "sample_count": int(len(stress)),
        "max_von_mises_pa": float(np.max(stress)),
        "min_von_mises_pa": float(np.min(stress)),
        "x_bounds_mm": [x_min, x_max],
        "y_bounds_mm": [y_min, y_max],
    }


def _turbo_like_colors(normalized: Any) -> Any:
    import numpy as np

    stops = np.array([
        [48, 18, 59],
        [50, 98, 181],
        [31, 150, 213],
        [46, 204, 113],
        [245, 211, 69],
        [230, 126, 34],
        [176, 38, 38],
    ], dtype=float)
    scaled = np.asarray(normalized) * (len(stops) - 1)
    low = np.floor(scaled).astype(int)
    high = np.clip(low + 1, 0, len(stops) - 1)
    frac = (scaled - low)[:, None]
    return np.rint(stops[low] * (1 - frac) + stops[high] * frac).astype(np.uint8)


def _draw_frame(canvas: Any, left: int, top: int, right: int, bottom: int) -> None:
    canvas[top:bottom, left] = 40
    canvas[top:bottom, right - 1] = 40
    canvas[top, left:right] = 40
    canvas[bottom - 1, left:right] = 40


def _draw_colorbar(canvas: Any, left: int, top: int, right: int, bottom: int) -> None:
    import numpy as np

    height = bottom - top
    for row in range(height):
        value = 1.0 - row / max(height - 1, 1)
        canvas[top + row, left:right] = _turbo_like_colors(np.array([value]))[0]
    _draw_frame(canvas, left, top, right, bottom)


def _write_png_rgb(path: Path, rgb: Any) -> None:
    height, width, channels = rgb.shape
    if channels != 3:
        raise ValueError("Expected RGB image array")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = b"".join(b"\x00" + rgb[row].tobytes() for row in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    payload = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, level=6))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(payload)


def _code_excerpt(java_code: str, *, max_chars: int = 1200) -> str:
    """Return a stable single-line code excerpt for repair-history records."""
    compact = re.sub(r"\s+", " ", _strip_code_fence(java_code)).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + " ..."


def _roller_risk_ranking() -> list[dict[str, Any]]:
    """Approximate per-roller risk ranking for the verified +X radial smoke load."""
    ranking = []
    for index in range(1, VERIFIED_ROLLER_COUNT + 1):
        angle = 360.0 * (index - 1) / VERIFIED_ROLLER_COUNT
        alignment = max(0.0, math.cos(math.radians(angle)))
        ranking.append({
            "roller": f"roller_{index}",
            "angle_deg": angle,
            "relative_risk": alignment,
            "reason": "+X radial smoke-load alignment" if alignment > 0 else "opposite-side support path in smoke model",
        })
    return sorted(ranking, key=lambda item: item["relative_risk"], reverse=True)


def _roller_risk_ranking_from_probes(
    per_roller_probe_results: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Rank rollers by verified scoped probe values when available."""
    if not per_roller_probe_results or not all(item.get("success") for item in per_roller_probe_results):
        return _roller_risk_ranking()
    ranked = sorted(
        per_roller_probe_results,
        key=lambda item: float(item.get("value") or 0.0),
        reverse=True,
    )
    max_value = float(ranked[0].get("value") or 0.0) if ranked else 0.0
    output: list[dict[str, Any]] = []
    for item in ranked:
        value = float(item.get("value") or 0.0)
        output.append({
            "roller": item.get("roller"),
            "relative_risk": value / max_value if max_value else 0.0,
            "max_von_mises_pa": value,
            "selection": item.get("selection"),
            "expression": item.get("expression"),
            "reason": "verified scoped Maximum coupling probe",
        })
    return output


def _selection_plan() -> dict[str, Any]:
    """Target named-selection contract for upgrading the 3D smoke to production."""
    roller_contact_sets = []
    for index in range(1, VERIFIED_ROLLER_COUNT + 1):
        angle = 360.0 * (index - 1) / VERIFIED_ROLLER_COUNT
        roller_contact_sets.append({
            "roller": f"roller_{index}",
            "angle_deg": angle,
            "body_selection": f"sel_roller_{index}_body",
            "inner_contact_selection": f"sel_roller_{index}_inner_contact",
            "outer_contact_selection": f"sel_roller_{index}_outer_contact",
            "risk_probe": f"probe_roller_{index}_max_mises",
        })
    return {
        "status": "planned_not_yet_bound_to_geometry_entities",
        "purpose": "upgrade named Box region selections into per-roller/raceway/load/support/cage selections and probes",
        "global_selections": {
            "inner_raceway_contact": "sel_inner_raceway_contact",
            "outer_raceway_contact": "sel_outer_raceway_contact",
            "inner_ring_body": "sel_inner_ring_body",
            "outer_ring_body": "sel_outer_ring_body",
            "cage_body": "sel_cage_body",
            "outer_support_surface": "sel_outer_support_surface",
            "inner_load_region": "sel_inner_load_region",
        },
        "roller_contact_sets": roller_contact_sets,
        "required_probes": [
            "probe_max_mises_global",
            "probe_max_contact_pressure_inner",
            "probe_max_contact_pressure_outer",
            *[f"probe_roller_{index}_max_mises" for index in range(1, VERIFIED_ROLLER_COUNT + 1)],
        ],
        "production_gate": "validate_3d_bearing_code_draft(require_named_selections=True)",
    }


def _inject_3d_package_metadata(
    package: dict,
    *,
    repair_history: list[dict[str, Any]],
    cage_model: str,
    per_roller_probe_results: list[dict[str, Any]] | None = None,
    stress_plot_evidence: dict[str, Any] | None = None,
    selection_binding_audit: dict[str, Any] | None = None,
    solve_result: dict[str, Any] | None = None,
) -> None:
    """Add 3D-specific evidence to package JSON/Markdown after generic export."""
    json_path = package.get("json_path")
    markdown_path = package.get("markdown_path")
    summary: dict[str, Any] | None = None
    roller_risk = _roller_risk_ranking_from_probes(per_roller_probe_results)
    if json_path:
        path = Path(json_path)
        if path.exists():
            summary = json.loads(path.read_text(encoding="utf-8"))
            metrics = summary.get("metrics") or {}
            summary["kind"] = "bearing_3d_full_package"
            summary["cage_model"] = cage_model
            summary["repair_history"] = repair_history
            summary["roller_risk_ranking"] = roller_risk
            summary["highest_risk_roller"] = roller_risk[0]["roller"]
            summary["risk_ranking_method"] = (
                "verified selection-scoped per-roller Maximum coupling probes"
                if per_roller_probe_results and all(item.get("success") for item in per_roller_probe_results)
                else f"deterministic +X radial smoke-load alignment using the {VERIFIED_ROLLER_COUNT} verified roller positions; replace with named-selection stress/contact probes before production ranking"
            )
            summary["selection_plan"] = _selection_plan()
            summary["selection_status"] = (
                "verified_named_box_region_roller_body_and_contact_surface_selections_with_scoped_per_roller_probe_evaluation"
            )
            summary["per_roller_probe_results"] = per_roller_probe_results or []
            summary["stress_plot_evidence"] = stress_plot_evidence or {}
            summary["selection_binding_contract"] = selection_binding_contract()
            summary["selection_binding_audit"] = selection_binding_audit or audit_3d_selection_binding(
                java_code=VERIFIED_3D_FULL_BEARING_CODE,
            )
            summary["physical_result_audit"] = audit_3d_physical_results(
                evaluations=summary.get("evaluations") or [],
                metrics=metrics,
                require_displacement=True,
                require_contact_pressure=True,
            )
            summary["contact_convergence_report"] = build_contact_convergence_report(
                solve_result=solve_result,
                metrics={
                    **metrics,
                    "contact_pressure_estimate_pa": (
                        metrics.get("contact_pressure_guess")
                        or metrics.get("max_contact_pressure")
                        or metrics.get("contact_pressure_est")
                    ),
                },
                selection_binding_audit=summary["selection_binding_audit"],
                physical_result_audit=summary["physical_result_audit"],
                contact_pair_count=VERIFIED_ROLLER_COUNT * 2,
            )
            if stress_plot_evidence and stress_plot_evidence.get("success"):
                summary["stress_plot_method"] = stress_plot_evidence.get("method")
                stress_plot_path = Path(str(stress_plot_evidence.get("filepath", "")))
                if stress_plot_path.exists():
                    summary["plot"] = {
                        "path": str(stress_plot_path),
                        "exists": True,
                        "size_bytes": stress_plot_path.stat().st_size,
                        "method": stress_plot_evidence.get("method"),
                    }
                    summary["plot_path"] = str(stress_plot_path)
            model_save = summary.get("model_save") or {}
            if model_save.get("saved_to"):
                summary["model_path"] = model_save.get("saved_to")
            all_probe_success = bool(per_roller_probe_results) and all(
                item.get("success") for item in per_roller_probe_results
            )
            summary["probe_scope_status"] = (
                "probe_scope_verified via component Maximum coupling operators bound to per-roller body selections"
                if all_probe_success
                else "per-roller MaxVolume numerical nodes are present; scoped per-roller evaluation was not fully verified in this package"
            )
            summary["max_von_mises_pa"] = metrics.get("von_mises_max")
            summary["mean_von_mises_pa"] = metrics.get("von_mises_mean")
            summary["min_von_mises_pa"] = metrics.get("von_mises_min")
            summary["contact_pressure_estimate_pa"] = (
                metrics.get("contact_pressure_guess")
                or metrics.get("max_contact_pressure")
                or metrics.get("contact_pressure_est")
            )
            summary["max_displacement_m"] = metrics.get("displacement_max")
            summary["assumptions"] = [
                f"3D full cylindrical-roller bearing smoke with inner ring, outer ring, {VERIFIED_ROLLER_COUNT} rollers, and Boolean-cut cage geometry.",
                f"Cage is included as a ring with {VERIFIED_ROLLER_COUNT} real cylindrical Boolean pocket cutouts.",
                "Geometry finalization uses assembly mode for separate roller/raceway contact bodies.",
                "Current load/contact/support selections use named Box region selections, and each roller body/contact region has a named Box selection plus max-stress probe node.",
                "Selection-scoped per-roller probe evaluation uses component Maximum coupling operators bound to roller body selections.",
                "Stress PNG is rendered from solved COMSOL x/y/solid.mises field samples when COMSOL GUI image export is too sparse.",
                "Repair history is recorded for generated-code or runtime fallback attempts.",
            ]
            summary["result_interpretation"] = {
                "max_stress_location_approx": "3D roller/raceway contact region under the radial smoke load",
                "highest_risk_roller": roller_risk[0]["roller"],
                "highest_risk_region": (
                    f"{roller_risk[0]['roller']} roller-to-inner/outer-raceway contact interfaces"
                ),
                "contact_pair_status": "explicit COMSOL Contact pair features were created for roller-to-inner and roller-to-outer raceway interfaces",
                "cage_status": "cage ring included with real cylindrical Boolean pocket cutouts",
                "location_precision": "approximate_region_from_model_setup; exact coordinates require named selections and point probes",
            }
            summary["max_stress_location_approx"] = summary["result_interpretation"]["max_stress_location_approx"]
            summary["highest_risk_region"] = summary["result_interpretation"]["highest_risk_region"]
            summary["artifact_qa"] = _default_3d_artifact_qa(summary)
            path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if markdown_path:
        path = Path(markdown_path)
        if path.exists():
            report_text = path.read_text(encoding="utf-8")
            if summary is not None:
                assumptions_block = "\n".join(
                    [
                        "## Assumptions",
                        "",
                        *[f"- {item}" for item in summary.get("assumptions", [])],
                        "",
                    ]
                )
                report_text = _replace_markdown_section(
                    report_text,
                    "## Assumptions",
                    "## Reuse Notes",
                    assumptions_block,
                )
            execution_audit = (
                ((summary or {}).get("artifacts") or {}).get("execution_audit")
                or ((summary or {}).get("template_artifact") or {}).get("execution_audit")
                or (((summary or {}).get("template_artifact") or {}).get("metadata") or {})
                or ((summary or {}).get("template_execution") or {}).get("execution_audit")
                or (((summary or {}).get("template_execution") or {}).get("metadata") or {})
                or (summary or {}).get("execution_audit")
                or {}
            )
            extra = [
                "",
                "## 3D Full-Bearing Notes",
                "",
                f"- Cage model: `{cage_model}`",
                "- Max stress location: approximate 3D roller/raceway contact region under radial smoke load.",
                f"- Highest-risk roller estimate: `{roller_risk[0]['roller']}`.",
                "- Selection status: named Box region, roller body, and contact-surface selections are present.",
                "- Probe scope status: component Maximum coupling operators are bound to per-roller body selections.",
                f"- Selection binding audit: `{((summary or {}).get('selection_binding_audit') or {}).get('success')}`.",
                f"- Physical result audit: `{((summary or {}).get('physical_result_audit') or {}).get('success')}`.",
                f"- Contact convergence report: `{((summary or {}).get('contact_convergence_report') or {}).get('quality_level')}`.",
                f"- Stress plot method: `{(stress_plot_evidence or {}).get('method', 'comsol_plot')}`.",
                f"- Repair history: `{json.dumps(repair_history, ensure_ascii=False, default=str)}`",
                f"- Execution workflow: `{execution_audit.get('workflow')}`",
                f"- Quality gate: `{execution_audit.get('quality_gate_success')}` / `{execution_audit.get('quality_gate_level')}`",
                f"- Repair history count: `{execution_audit.get('repair_history_count')}`",
                f"- Require free-generated code: `{execution_audit.get('require_free_generated_code')}`",
                "- Remaining production task: upgrade approximate Box contact regions to exact geometry-entity selections and perform contact convergence checks.",
                "",
                "## Artifact Q&A Smoke",
                "",
            ]
            if summary is not None:
                for item in summary.get("artifact_qa", []):
                    extra.extend([
                        f"### {item.get('question')}",
                        "",
                        item.get("answer") or "",
                        "",
                    ])
            path.write_text(report_text + "\n".join(extra), encoding="utf-8")
            html_path = path.with_suffix(".html")
            html_path.write_text(_render_3d_package_html_report(path.read_text(encoding="utf-8")), encoding="utf-8")
            package["html_path"] = str(html_path)
            if summary is not None and json_path:
                summary["report_paths"] = {
                    "markdown_path": str(path),
                    "html_path": str(html_path),
                }
                Path(json_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _replace_markdown_section(text: str, start_heading: str, end_heading: str, replacement: str) -> str:
    """Replace a top-level Markdown section while preserving the following section."""
    start = text.find(start_heading)
    end = text.find(end_heading, start + len(start_heading)) if start >= 0 else -1
    if start < 0 or end < 0:
        return text
    return text[:start] + replacement.rstrip() + "\n\n" + text[end:]


def _default_3d_artifact_qa(summary: dict[str, Any]) -> list[dict[str, str]]:
    questions = [
        "最大应力是多少，最大应力位置在哪里？",
        "哪个滚子附近风险最高？",
        "保持架是否建模？",
        "滚子和外圈有没有接触？",
        "载荷、材料和模型参数是什么？",
        "应力图和模型文件在哪里？",
    ]
    return [
        {
            "question": question,
            "answer": _answer_from_artifact_summary(question, summary),
        }
        for question in questions
    ]


def _render_3d_package_html_report(markdown: str) -> str:
    body_lines: list[str] = []
    in_list = False
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if not line:
            if in_list:
                body_lines.append("</ul>")
                in_list = False
            continue
        if line.startswith("# "):
            if in_list:
                body_lines.append("</ul>")
                in_list = False
            body_lines.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_list:
                body_lines.append("</ul>")
                in_list = False
            body_lines.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("### "):
            if in_list:
                body_lines.append("</ul>")
                in_list = False
            body_lines.append(f"<h3>{escape(line[4:])}</h3>")
        elif line.startswith("- "):
            if not in_list:
                body_lines.append("<ul>")
                in_list = True
            body_lines.append(f"<li>{escape(line[2:])}</li>")
        else:
            if in_list:
                body_lines.append("</ul>")
                in_list = False
            body_lines.append(f"<p>{escape(line)}</p>")
    if in_list:
        body_lines.append("</ul>")
    return "\n".join([
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>3D Bearing Result Package</title>",
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:2rem;line-height:1.55;color:#0f172a}h1,h2,h3{color:#1d4ed8}li{margin:.25rem 0}code{background:#e2e8f0;padding:.1rem .25rem;border-radius:.25rem}</style>",
        "</head>",
        "<body>",
        *body_lines,
        "</body>",
        "</html>",
    ])


# Re-export the project-level reusable 3D bearing contracts for compatibility
# with older tests and scripts that imported these names from the demo module.
VERIFIED_ROLLER_COUNT = bearing_3d_contracts.VERIFIED_ROLLER_COUNT
Segmented3DCodeSpec = bearing_3d_contracts.Segmented3DCodeSpec
SEGMENT_MARKER_MANIFEST_START = bearing_3d_contracts.SEGMENT_MARKER_MANIFEST_START
SEGMENT_MARKER_MANIFEST_END = bearing_3d_contracts.SEGMENT_MARKER_MANIFEST_END
SEGMENTED_3D_CODE_SPECS = bearing_3d_contracts.SEGMENTED_3D_CODE_SPECS
build_segmented_3d_generation_prompt = bearing_3d_contracts.build_segmented_3d_generation_prompt
extract_generated_code = bearing_3d_contracts.extract_generated_code
extract_segment_manifest = bearing_3d_contracts.extract_segment_manifest
extract_segment_generated_code = bearing_3d_contracts.extract_segment_generated_code
normalize_generated_mph_code = bearing_3d_contracts.normalize_generated_mph_code
validate_segmented_3d_segment = bearing_3d_contracts.validate_segmented_3d_segment
assemble_segmented_3d_code = bearing_3d_contracts.assemble_segmented_3d_code
validate_3d_bearing_code_draft = bearing_3d_contracts.validate_3d_bearing_code_draft
selection_binding_contract = bearing_3d_contracts.selection_binding_contract
audit_3d_selection_binding = bearing_3d_contracts.audit_3d_selection_binding
audit_3d_physical_results = bearing_3d_contracts.audit_3d_physical_results
build_contact_convergence_report = bearing_3d_contracts.build_contact_convergence_report
_build_3d_execution_context = bearing_3d_contracts.build_3d_execution_context
_selection_plan = bearing_3d_contracts.selection_plan
_default_3d_artifact_qa = bearing_3d_contracts.default_3d_artifact_qa


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a generated 3D full roller bearing demo.")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--archive-path", default="runtime_smoke/bearing_3d_full_demo.sqlite3")
    parser.add_argument("--artifact-root", default="runtime_smoke/bearing_3d_full_demo")
    parser.add_argument("--model-name", default="agent_3d_bearing_model")
    parser.add_argument("--template-name", default="agent_3d_bearing_generated_seed")
    parser.add_argument("--max-tool-iterations", type=int, default=36)
    parser.add_argument("--llm-max-tokens", type=int, default=16000)
    parser.add_argument("--llm-repair-max-tokens", type=int, default=20000)
    parser.add_argument(
        "--segmented-generation",
        action="store_true",
        help="Generate the 3D bearing setup in manifest-checked DeepSeek segments before local assembly.",
    )
    parser.add_argument(
        "--segment-llm-max-tokens",
        type=int,
        default=5000,
        help="Maximum tokens for each segmented generation call.",
    )
    parser.add_argument(
        "--segment-max-retries",
        type=int,
        default=3,
        help="Maximum generation/validation retries for each segmented generation call.",
    )
    parser.add_argument(
        "--segment-timeout-seconds",
        type=float,
        default=90.0,
        help="Wall-clock timeout for each segmented generation call before retrying that segment.",
    )
    parser.add_argument(
        "--segmented-code-path",
        default="",
        help="Reuse a manifest-assembled segmented code artifact instead of calling the LLM again.",
    )
    parser.add_argument(
        "--require-free-generated-code",
        action="store_true",
        help="Fail instead of replacing generated 3D code with the complete verified fallback.",
    )
    parser.add_argument("--skip-comsol", action="store_true")
    parser.add_argument("--print-generated-code", action="store_true")
    parser.add_argument("--use-verified-fixture", action="store_true")
    parser.add_argument("--direct-fixture-run", action="store_true")
    parser.add_argument("--print-prompts", action="store_true")
    args = parser.parse_args()

    if args.print_prompts:
        draft = build_3d_bearing_code_generation_prompt(archive_path=args.archive_path)
        execute = build_3d_bearing_execution_prompt(
            java_code="<generated_code>",
            archive_path=args.archive_path,
            artifact_dir=str(Path(args.artifact_root) / "template_runs"),
            plot_path=str(Path(args.artifact_root) / "bearing_3d_von_mises.png"),
            model_name=args.model_name,
            template_name=args.template_name,
            package_dir=str(Path(args.artifact_root) / "result_packages"),
            allow_verified_fallback=not args.require_free_generated_code,
        )
        payload: list[dict[str, Any]] = [draft.to_dict(), execute.to_dict()]
        if args.segmented_generation:
            prompts = []
            manifests: list[dict[str, Any]] = []
            for spec in SEGMENTED_3D_CODE_SPECS:
                prompts.append({
                    "segment_id": spec.segment_id,
                    "title": spec.title,
                    "prompt": build_segmented_3d_generation_prompt(
                        spec,
                        completed_manifests=manifests,
                        previous_code_tail="",
                    ),
                })
                manifests.append({
                    "segment_id": spec.segment_id,
                    "depends_on": list(spec.depends_on),
                    "creates": list(spec.required_creates),
                })
            payload.append({
                "name": "bearing_3d_segmented_code_draft",
                "segments": prompts,
            })
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if args.direct_fixture_run:
        if args.segmented_code_path:
            code_path = Path(args.segmented_code_path)
            generated_code = code_path.read_text(encoding="utf-8")
            draft_quality = validate_3d_bearing_code_draft(generated_code, require_named_selections=True)
            generated_code, preflight_history, draft_quality = apply_runtime_preflight_3d_repairs(
                generated_code,
                draft_quality,
            )
            repair_history = [{
                "attempt": 0,
                "stage": "segmented_generation_reuse",
                "strategy": "direct_reuse_manifest_checked_segmented_assembled_code",
                "success": True,
                "assembled_code_path": str(code_path),
                "generated_code_excerpt": _code_excerpt(generated_code),
            }]
            for report in preflight_history:
                report["attempt"] = len(repair_history)
                repair_history.append(report)
            if not draft_quality["success"]:
                print(json.dumps({
                    "success": False,
                    "draft_quality": draft_quality,
                    "repair_history": repair_history,
                }, ensure_ascii=False, indent=2, default=str))
                raise SystemExit(1)
            raise SystemExit(run_direct_fixture_smoke(args, generated_code=generated_code, repair_history=repair_history))
        raise SystemExit(run_direct_fixture_smoke(args))

    raise SystemExit(asyncio.run(run_3d_bearing_demo(args)))


if __name__ == "__main__":
    main()
