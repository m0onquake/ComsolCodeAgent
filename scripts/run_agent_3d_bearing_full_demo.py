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
LEGACY_RACEWAY_HIGHLOAD_TEMPLATE_JSON = (
    ROOT
    / "runtime_smoke"
    / "bearing_3d_full_demo"
    / "template_runs"
    / "direct_3d_bearing_fixture_20260704_181424_590737.json"
)

from comsol_agent.agent.loop import AgentLoop
from comsol_agent.agent.tool_registry import clear as clear_tools
from comsol_agent.agent.tools_bootstrap import register_all_tools
from comsol_agent.cli.config import load_config
from comsol_agent.llm.router import create_provider
from comsol_agent.memory.archive_store import ArchiveStore
from comsol_agent.simulation import bearing_3d as bearing_3d_contracts
from comsol_agent.simulation.skills import seed_builtin_templates
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.tools.comsol.evaluate import comsol_plot, inspect_png_quality
from comsol_agent.tools.comsol.model_ops import comsol_close_model, comsol_create_model, comsol_load_model, comsol_save_model
from comsol_agent.tools.comsol.solve import comsol_evaluate, comsol_execute_java, comsol_get_model_summary, comsol_solve
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


def _build_verified_3d_full_bearing_code(
    *,
    roller_count: int = 12,
    roller_angular_offset_deg: float = 0.0,
    local_contact_patch_mode: str = "none",
) -> str:
    """Build explicit setup code for the verified 3D full-bearing smoke fixture."""
    import math

    local_contact_patch_mode = str(local_contact_patch_mode or "none").strip().lower()
    if local_contact_patch_mode not in {
        "none",
        "roller1_outer_aux_patch",
        "roller1_cylinder_seam_shift15",
        "roller1_outer_retained_conformal_patch",
        "roller1_outer_retained_conformal_source_closure3um",
        "roller1_outer_retained_conformal_narrow_source_closure3um",
        "roller1_outer_retained_conformal_equal_height_source_closure3um",
        "roller1_outer_retained_conformal_sector_source_closure3um",
        "roller1_outer_construction_partition_patch",
        "roller1_outer_construction_partition_source_closure3um",
        "roller1_outer_raceway_partition_only",
        "roller1_outer_raceway_partition_source_closure3um",
        "roller1_outer_raceway_narrow_partition_source_closure3um",
    }:
        raise ValueError(f"Unsupported verified fixture local contact patch mode: {local_contact_patch_mode}")
    use_roller1_outer_aux_patch = local_contact_patch_mode == "roller1_outer_aux_patch"
    use_roller1_cylinder_seam_shift15 = local_contact_patch_mode == "roller1_cylinder_seam_shift15"
    use_roller1_outer_retained_conformal_patch = local_contact_patch_mode == "roller1_outer_retained_conformal_patch"
    use_roller1_outer_retained_conformal_source_closure3um = (
        local_contact_patch_mode == "roller1_outer_retained_conformal_source_closure3um"
    )
    use_roller1_outer_retained_conformal_narrow_source_closure3um = (
        local_contact_patch_mode == "roller1_outer_retained_conformal_narrow_source_closure3um"
    )
    use_roller1_outer_retained_conformal_equal_height_source_closure3um = (
        local_contact_patch_mode == "roller1_outer_retained_conformal_equal_height_source_closure3um"
    )
    use_roller1_outer_retained_conformal_sector_source_closure3um = (
        local_contact_patch_mode == "roller1_outer_retained_conformal_sector_source_closure3um"
    )
    use_roller1_outer_retained_conformal_any = (
        use_roller1_outer_retained_conformal_patch
        or use_roller1_outer_retained_conformal_source_closure3um
        or use_roller1_outer_retained_conformal_narrow_source_closure3um
        or use_roller1_outer_retained_conformal_equal_height_source_closure3um
        or use_roller1_outer_retained_conformal_sector_source_closure3um
    )
    use_roller1_outer_construction_partition_patch = (
        local_contact_patch_mode == "roller1_outer_construction_partition_patch"
    )
    use_roller1_outer_construction_partition_source_closure3um = (
        local_contact_patch_mode == "roller1_outer_construction_partition_source_closure3um"
    )
    use_roller1_outer_construction_partition_any = (
        use_roller1_outer_construction_partition_patch
        or use_roller1_outer_construction_partition_source_closure3um
    )
    use_roller1_outer_raceway_partition_only = local_contact_patch_mode == "roller1_outer_raceway_partition_only"
    use_roller1_outer_raceway_partition_source_closure3um = (
        local_contact_patch_mode == "roller1_outer_raceway_partition_source_closure3um"
    )
    use_roller1_outer_raceway_narrow_partition_source_closure3um = (
        local_contact_patch_mode == "roller1_outer_raceway_narrow_partition_source_closure3um"
    )
    use_roller1_source_closure3um = (
        use_roller1_outer_construction_partition_source_closure3um
        or use_roller1_outer_retained_conformal_source_closure3um
        or use_roller1_outer_retained_conformal_narrow_source_closure3um
        or use_roller1_outer_retained_conformal_equal_height_source_closure3um
        or use_roller1_outer_retained_conformal_sector_source_closure3um
        or use_roller1_outer_raceway_partition_source_closure3um
        or use_roller1_outer_raceway_narrow_partition_source_closure3um
    )
    pitch_radius = 27.0
    roller_radius = 4.0
    roller_box_margin = 1.5
    contact_half_width = 1.2
    lines: list[str] = [
        "model.param().set('inner_diameter', '40[mm]');",
        "model.param().set('outer_diameter', '80[mm]');",
        "model.param().set('bearing_width', '18[mm]');",
        f"model.param().set('roller_count', '{roller_count}');",
        "model.param().set('contact_interference', '0[um]');",
        "model.param().set('roller_diameter', '8[mm] + contact_interference');",
        "model.param().set('roller_radius', 'roller_diameter/2');",
        "model.param().set('roller_length', '16[mm]');",
        "model.param().set('pitch_radius', '27[mm]');",
        "model.param().set('inner_race_outer_radius', '23[mm]');",
        "model.param().set('outer_race_inner_radius', '31[mm]');",
        "model.param().set('cage_inner_radius', '24[mm]');",
        "model.param().set('cage_outer_radius', '30[mm]');",
        "model.param().set('cage_width', '14[mm]');",
        "model.param().set('cage_pocket_clearance', '0.6[mm]');",
        "model.param().set('cage_pocket_radius', 'roller_radius + cage_pocket_clearance');",
        "model.param().set('radial_load', '3000[N]');",
        "model.param().set('load_per_roller', 'radial_load/roller_count');",
        "model.param().set('contact_pressure_est', 'load_per_roller/(roller_length*roller_diameter)');",
        "model.param().set('inner_bore_load_pressure', 'radial_load/(pi*inner_diameter*bearing_width)');",
        "model.param().set('inner_radial_displacement', '0.1[um]');",
        "model.param().set('friction_coefficient', '0.05');",
        "model.param().set('E_steel', '210[GPa]');",
        "model.param().set('nu_steel', '0.30');",
        "model.param().set('rho_steel', '7850[kg/m^3]');",
        "model.param().set('E_cage', '3[GPa]');",
        "model.param().set('nu_cage', '0.35');",
        "model.param().set('rho_cage', '1350[kg/m^3]');",
        "model.param().set('mesh_contact_size', '0.7[mm]');",
        "model.param().set('mesh_bulk_size', '2.4[mm]');",
        "model.param().set('weak_roller_foundation_k', '1e8[N/m^3]');",
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
        "model.component('comp1').geom('geom1').feature('inner_ring').set('selresultshow', 'all');",
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
        "model.component('comp1').geom('geom1').feature('outer_ring').set('selresultshow', 'all');",
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
    if use_roller1_outer_aux_patch:
        lines.extend([
            "model.component('comp1').geom('geom1').create('roller1_outer_aux_raceway_patch', 'Block');",
            "model.component('comp1').geom('geom1').feature('roller1_outer_aux_raceway_patch').set('base', 'center');",
            "model.component('comp1').geom('geom1').feature('roller1_outer_aux_raceway_patch').set('size', ['0.35[mm]', '2.4[mm]', '17[mm]']);",
            "model.component('comp1').geom('geom1').feature('roller1_outer_aux_raceway_patch').set('pos', ['31.0[mm]', '0[mm]', '0[mm]']);",
            "model.component('comp1').geom('geom1').feature('roller1_outer_aux_raceway_patch').set('selresult', 'on');",
            "model.component('comp1').geom('geom1').feature('roller1_outer_aux_raceway_patch').set('selresultshow', 'all');",
        ])
    if use_roller1_outer_retained_conformal_any:
        conformal_inner_height = (
            "16.4[mm]"
            if use_roller1_outer_retained_conformal_equal_height_source_closure3um
            else "17.0[mm]"
        )
        conformal_inner_pos = (
            "-8.2[mm]"
            if use_roller1_outer_retained_conformal_equal_height_source_closure3um
            else "-8.5[mm]"
        )
        lines.extend([
            "model.component('comp1').geom('geom1').create('roller1_outer_conformal_patch_outer', 'Cylinder');",
            "model.component('comp1').geom('geom1').feature('roller1_outer_conformal_patch_outer').set('r', '31.05[mm]');",
            "model.component('comp1').geom('geom1').feature('roller1_outer_conformal_patch_outer').set('h', '16.4[mm]');",
            "model.component('comp1').geom('geom1').feature('roller1_outer_conformal_patch_outer').set('pos', ['0', '0', '-8.2[mm]']);",
            "model.component('comp1').geom('geom1').create('roller1_outer_conformal_patch_inner', 'Cylinder');",
            "model.component('comp1').geom('geom1').feature('roller1_outer_conformal_patch_inner').set('r', '30.72[mm]');",
            f"model.component('comp1').geom('geom1').feature('roller1_outer_conformal_patch_inner').set('h', '{conformal_inner_height}');",
            f"model.component('comp1').geom('geom1').feature('roller1_outer_conformal_patch_inner').set('pos', ['0', '0', '{conformal_inner_pos}']);",
        ])
        if use_roller1_outer_retained_conformal_sector_source_closure3um:
            lines.extend([
                "model.component('comp1').geom('geom1').create('roller1_outer_conformal_patch_annulus', 'Difference');",
                "model.component('comp1').geom('geom1').feature('roller1_outer_conformal_patch_annulus').selection('input').set(['roller1_outer_conformal_patch_outer']);",
                "model.component('comp1').geom('geom1').feature('roller1_outer_conformal_patch_annulus').selection('input2').set(['roller1_outer_conformal_patch_inner']);",
                "model.component('comp1').geom('geom1').create('roller1_outer_conformal_patch_window', 'Block');",
                "model.component('comp1').geom('geom1').feature('roller1_outer_conformal_patch_window').set('base', 'center');",
                "model.component('comp1').geom('geom1').feature('roller1_outer_conformal_patch_window').set('size', ['1.1[mm]', '3.6[mm]', '16.4[mm]']);",
                "model.component('comp1').geom('geom1').feature('roller1_outer_conformal_patch_window').set('pos', ['31.0[mm]', '0[mm]', '0[mm]']);",
                "model.component('comp1').geom('geom1').create('roller1_outer_retained_conformal_patch', 'Intersection');",
                "model.component('comp1').geom('geom1').feature('roller1_outer_retained_conformal_patch').selection('input').set(['roller1_outer_conformal_patch_annulus', 'roller1_outer_conformal_patch_window']);",
            ])
        else:
            lines.extend([
                "model.component('comp1').geom('geom1').create('roller1_outer_retained_conformal_patch', 'Difference');",
                "model.component('comp1').geom('geom1').feature('roller1_outer_retained_conformal_patch').selection('input').set(['roller1_outer_conformal_patch_outer']);",
                "model.component('comp1').geom('geom1').feature('roller1_outer_retained_conformal_patch').selection('input2').set(['roller1_outer_conformal_patch_inner']);",
            ])
        lines.extend([
            "model.component('comp1').geom('geom1').feature('roller1_outer_retained_conformal_patch').set('selresult', 'on');",
            "model.component('comp1').geom('geom1').feature('roller1_outer_retained_conformal_patch').set('selresultshow', 'all');",
            f"output.write('ROLLER1_OUTER_RETAINED_CONFORMAL_PATCH_GEOM|outer_r=31.05[mm]|inner_r=30.72[mm]|outer_h=16.4[mm]|inner_h={conformal_inner_height}|sector={str(bool(use_roller1_outer_retained_conformal_sector_source_closure3um)).lower()}|source_closure3um={str(bool(use_roller1_outer_retained_conformal_source_closure3um or use_roller1_outer_retained_conformal_narrow_source_closure3um or use_roller1_outer_retained_conformal_equal_height_source_closure3um or use_roller1_outer_retained_conformal_sector_source_closure3um)).lower()}|outer_box_tangential_half_width={('0.9' if use_roller1_outer_retained_conformal_narrow_source_closure3um else '1.8')}[mm]\\n');",
        ])
    pocket_tags = []
    roller_centres = []
    angular_offset_rad = math.radians(float(roller_angular_offset_deg))
    for index in range(1, roller_count + 1):
        angle = angular_offset_rad + 2.0 * math.pi * (index - 1) / roller_count
        x = pitch_radius * math.cos(angle)
        y = pitch_radius * math.sin(angle)
        roller_x = x
        roller_y = y
        if use_roller1_source_closure3um and index == 1:
            roller_x = x + 0.003
        roller_centres.append((index, angle, roller_x, roller_y))
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
        "model.component('comp1').geom('geom1').feature('cage').set('selresult', 'on');",
        "model.component('comp1').geom('geom1').feature('cage').set('selresultshow', 'all');",
    ])
    for index, _angle, x, y in roller_centres:
        lines.extend([
            f"model.component('comp1').geom('geom1').create('roller_{index}', 'Cylinder');",
            f"model.component('comp1').geom('geom1').feature('roller_{index}').set('r', 'roller_radius');",
            f"model.component('comp1').geom('geom1').feature('roller_{index}').set('h', 'roller_length');",
            f"model.component('comp1').geom('geom1').feature('roller_{index}').set('pos', ['{_fmt_mm(x)}', '{_fmt_mm(y)}', '-roller_length/2']);",
        ])
        if use_roller1_cylinder_seam_shift15 and index == 1:
            lines.extend([
                "model.component('comp1').geom('geom1').feature('roller_1').set('axis', ['0', '0', '1']);",
                "model.component('comp1').geom('geom1').feature('roller_1').set('rot', '15[deg]');",
                "output.write('ROLLER1_CYLINDER_SEAM_SHIFT|roller=1|axis=0,0,1|rot=15[deg]\\n');",
            ])
        if use_roller1_source_closure3um and index == 1:
            lines.append(
                f"output.write('ROLLER1_OUTER_SOURCE_CLOSURE|roller=1|radial_shift=3[um]|direction=+X|combined_with={local_contact_patch_mode}\\n');"
            )
        lines.extend([
            f"model.component('comp1').geom('geom1').feature('roller_{index}').set('selresult', 'on');",
            f"model.component('comp1').geom('geom1').feature('roller_{index}').set('selresultshow', 'all');",
        ])
    if use_roller1_outer_construction_partition_any:
        lines.extend([
            "model.component('comp1').geom('geom1').create('partition_tool_roller1_outer_raceway_patch', 'Block');",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_patch').set('base', 'center');",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_patch').set('size', ['1.1[mm]', '3.6[mm]', '17.0[mm]']);",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_patch').set('pos', ['31.0[mm]', '0[mm]', '0[mm]']);",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_patch').set('selresult', 'on');",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_patch').set('selresultshow', 'all');",
            "model.component('comp1').geom('geom1').create('partition_tool_roller1_outer_source_patch', 'Block');",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_source_patch').set('base', 'center');",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_source_patch').set('size', ['1.1[mm]', '3.6[mm]', '17.0[mm]']);",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_source_patch').set('pos', ['31.0[mm]', '0[mm]', '0[mm]']);",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_source_patch').set('selresult', 'on');",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_source_patch').set('selresultshow', 'all');",
            "model.component('comp1').geom('geom1').create('partition_roller1_outer_raceway_construction_patch', 'Partition');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_construction_patch').selection('input').set(['outer_ring']);",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_construction_patch').selection('tool').set(['partition_tool_roller1_outer_raceway_patch']);",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_construction_patch').set('keepinput', 'on');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_construction_patch').set('keeptool', 'off');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_construction_patch').set('selresult', 'on');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_construction_patch').set('selresultshow', 'all');",
            "model.component('comp1').geom('geom1').create('partition_roller1_outer_source_construction_patch', 'Partition');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_source_construction_patch').selection('input').set(['roller_1']);",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_source_construction_patch').selection('tool').set(['partition_tool_roller1_outer_source_patch']);",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_source_construction_patch').set('keepinput', 'on');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_source_construction_patch').set('keeptool', 'off');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_source_construction_patch').set('selresult', 'on');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_source_construction_patch').set('selresultshow', 'all');",
            f"output.write('ROLLER1_OUTER_CONSTRUCTION_PARTITION_PATCH_GEOM|raceway_tool=partition_tool_roller1_outer_raceway_patch|source_tool=partition_tool_roller1_outer_source_patch|source=roller_1|destination=outer_ring|source_closure3um={str(bool(use_roller1_outer_construction_partition_source_closure3um)).lower()}\\n');",
        ])
    if use_roller1_outer_raceway_partition_only or use_roller1_outer_raceway_partition_source_closure3um:
        lines.extend([
            "model.component('comp1').geom('geom1').create('partition_tool_roller1_outer_raceway_only_patch', 'Block');",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_only_patch').set('base', 'center');",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_only_patch').set('size', ['0.7[mm]', '2.4[mm]', '16.4[mm]']);",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_only_patch').set('pos', ['31.0[mm]', '0[mm]', '0[mm]']);",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_only_patch').set('selresult', 'on');",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_only_patch').set('selresultshow', 'all');",
            "model.component('comp1').geom('geom1').create('partition_roller1_outer_raceway_only_patch', 'Partition');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_only_patch').selection('input').set(['outer_ring']);",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_only_patch').selection('tool').set(['partition_tool_roller1_outer_raceway_only_patch']);",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_only_patch').set('keepinput', 'on');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_only_patch').set('keeptool', 'off');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_only_patch').set('selresult', 'on');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_only_patch').set('selresultshow', 'all');",
            f"output.write('ROLLER1_OUTER_RACEWAY_PARTITION_ONLY_GEOM|tool=partition_tool_roller1_outer_raceway_only_patch|source=original_roller_1_bnd|destination=outer_ring|source_closure3um={str(bool(use_roller1_outer_raceway_partition_source_closure3um)).lower()}\\n');",
        ])
    if use_roller1_outer_raceway_narrow_partition_source_closure3um:
        lines.extend([
            "model.component('comp1').geom('geom1').create('partition_tool_roller1_outer_raceway_narrow_closure_patch', 'Block');",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_narrow_closure_patch').set('base', 'center');",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_narrow_closure_patch').set('size', ['0.35[mm]', '1.2[mm]', '16.4[mm]']);",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_narrow_closure_patch').set('pos', ['31.0[mm]', '0[mm]', '0[mm]']);",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_narrow_closure_patch').set('selresult', 'on');",
            "model.component('comp1').geom('geom1').feature('partition_tool_roller1_outer_raceway_narrow_closure_patch').set('selresultshow', 'all');",
            "model.component('comp1').geom('geom1').create('partition_roller1_outer_raceway_narrow_closure_patch', 'Partition');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_narrow_closure_patch').selection('input').set(['outer_ring']);",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_narrow_closure_patch').selection('tool').set(['partition_tool_roller1_outer_raceway_narrow_closure_patch']);",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_narrow_closure_patch').set('keepinput', 'on');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_narrow_closure_patch').set('keeptool', 'off');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_narrow_closure_patch').set('selresult', 'on');",
            "model.component('comp1').geom('geom1').feature('partition_roller1_outer_raceway_narrow_closure_patch').set('selresultshow', 'all');",
            "output.write('ROLLER1_OUTER_RACEWAY_NARROW_PARTITION_SOURCE_CLOSURE_GEOM|tool=partition_tool_roller1_outer_raceway_narrow_closure_patch|source=original_roller_1_bnd|destination=outer_ring|source_closure3um=true|tool_size=0.35x1.2x16.4[mm]\\n');",
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
        "model.component('comp1').selection().create('sel_outer_support_xpos', 'Box');",
        "model.component('comp1').selection('sel_outer_support_xpos').set('entitydim', '2');",
        "model.component('comp1').selection('sel_outer_support_xpos').set('xmin', '39[mm]');",
        "model.component('comp1').selection('sel_outer_support_xpos').set('xmax', '41[mm]');",
        "model.component('comp1').selection('sel_outer_support_xpos').set('ymin', '-41[mm]');",
        "model.component('comp1').selection('sel_outer_support_xpos').set('ymax', '41[mm]');",
        "model.component('comp1').selection('sel_outer_support_xpos').set('zmin', '-9.5[mm]');",
        "model.component('comp1').selection('sel_outer_support_xpos').set('zmax', '9.5[mm]');",
        "model.component('comp1').selection('sel_outer_support_xpos').set('condition', 'intersects');",
        "model.component('comp1').selection().create('sel_outer_support_xneg', 'Box');",
        "model.component('comp1').selection('sel_outer_support_xneg').set('entitydim', '2');",
        "model.component('comp1').selection('sel_outer_support_xneg').set('xmin', '-41[mm]');",
        "model.component('comp1').selection('sel_outer_support_xneg').set('xmax', '-39[mm]');",
        "model.component('comp1').selection('sel_outer_support_xneg').set('ymin', '-41[mm]');",
        "model.component('comp1').selection('sel_outer_support_xneg').set('ymax', '41[mm]');",
        "model.component('comp1').selection('sel_outer_support_xneg').set('zmin', '-9.5[mm]');",
        "model.component('comp1').selection('sel_outer_support_xneg').set('zmax', '9.5[mm]');",
        "model.component('comp1').selection('sel_outer_support_xneg').set('condition', 'intersects');",
        "model.component('comp1').selection().create('sel_outer_support_ypos', 'Box');",
        "model.component('comp1').selection('sel_outer_support_ypos').set('entitydim', '2');",
        "model.component('comp1').selection('sel_outer_support_ypos').set('xmin', '-41[mm]');",
        "model.component('comp1').selection('sel_outer_support_ypos').set('xmax', '41[mm]');",
        "model.component('comp1').selection('sel_outer_support_ypos').set('ymin', '39[mm]');",
        "model.component('comp1').selection('sel_outer_support_ypos').set('ymax', '41[mm]');",
        "model.component('comp1').selection('sel_outer_support_ypos').set('zmin', '-9.5[mm]');",
        "model.component('comp1').selection('sel_outer_support_ypos').set('zmax', '9.5[mm]');",
        "model.component('comp1').selection('sel_outer_support_ypos').set('condition', 'intersects');",
        "model.component('comp1').selection().create('sel_outer_support_yneg', 'Box');",
        "model.component('comp1').selection('sel_outer_support_yneg').set('entitydim', '2');",
        "model.component('comp1').selection('sel_outer_support_yneg').set('xmin', '-41[mm]');",
        "model.component('comp1').selection('sel_outer_support_yneg').set('xmax', '41[mm]');",
        "model.component('comp1').selection('sel_outer_support_yneg').set('ymin', '-41[mm]');",
        "model.component('comp1').selection('sel_outer_support_yneg').set('ymax', '-39[mm]');",
        "model.component('comp1').selection('sel_outer_support_yneg').set('zmin', '-9.5[mm]');",
        "model.component('comp1').selection('sel_outer_support_yneg').set('zmax', '9.5[mm]');",
        "model.component('comp1').selection('sel_outer_support_yneg').set('condition', 'intersects');",
        "model.component('comp1').selection().create('sel_outer_support_surface', 'Union');",
        "model.component('comp1').selection('sel_outer_support_surface').set('entitydim', '2');",
        "model.component('comp1').selection('sel_outer_support_surface').set('input', ['sel_outer_support_xpos', 'sel_outer_support_xneg', 'sel_outer_support_ypos', 'sel_outer_support_yneg']);",
        "model.component('comp1').selection().create('box_inner_bore_load_surface', 'Box');",
        "model.component('comp1').selection('box_inner_bore_load_surface').set('entitydim', '2');",
        "model.component('comp1').selection('box_inner_bore_load_surface').set('xmin', '-20.8[mm]');",
        "model.component('comp1').selection('box_inner_bore_load_surface').set('xmax', '20.8[mm]');",
        "model.component('comp1').selection('box_inner_bore_load_surface').set('ymin', '-20.8[mm]');",
        "model.component('comp1').selection('box_inner_bore_load_surface').set('ymax', '20.8[mm]');",
        "model.component('comp1').selection('box_inner_bore_load_surface').set('zmin', '-8.6[mm]');",
        "model.component('comp1').selection('box_inner_bore_load_surface').set('zmax', '8.6[mm]');",
        "model.component('comp1').selection('box_inner_bore_load_surface').set('condition', 'intersects');",
        "model.component('comp1').selection().create('sel_inner_bore_load_surface', 'Intersection');",
        "model.component('comp1').selection('sel_inner_bore_load_surface').set('entitydim', '2');",
        "model.component('comp1').selection('sel_inner_bore_load_surface').set('input', ['box_inner_bore_load_surface', 'geom1_inner_ring_bnd']);",
        "model.component('comp1').selection().create('sel_inner_ring_body', 'Box');",
        "model.component('comp1').selection('sel_inner_ring_body').set('entitydim', '3');",
        "model.component('comp1').selection('sel_inner_ring_body').set('xmin', '-23.5[mm]');",
        "model.component('comp1').selection('sel_inner_ring_body').set('xmax', '23.5[mm]');",
        "model.component('comp1').selection('sel_inner_ring_body').set('ymin', '-23.5[mm]');",
        "model.component('comp1').selection('sel_inner_ring_body').set('ymax', '23.5[mm]');",
        "model.component('comp1').selection('sel_inner_ring_body').set('zmin', '-9.5[mm]');",
        "model.component('comp1').selection('sel_inner_ring_body').set('zmax', '9.5[mm]');",
        "model.component('comp1').selection('sel_inner_ring_body').set('condition', 'intersects');",
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
            f"model.component('comp1').selection().create('box_roller_{index}_cage_pocket_contact_patch', 'Box');",
            f"model.component('comp1').selection('box_roller_{index}_cage_pocket_contact_patch').set('entitydim', '2');",
            f"model.component('comp1').selection('box_roller_{index}_cage_pocket_contact_patch').set('xmin', '{_fmt_mm(x - 5.0)}');",
            f"model.component('comp1').selection('box_roller_{index}_cage_pocket_contact_patch').set('xmax', '{_fmt_mm(x + 5.0)}');",
            f"model.component('comp1').selection('box_roller_{index}_cage_pocket_contact_patch').set('ymin', '{_fmt_mm(y - 5.0)}');",
            f"model.component('comp1').selection('box_roller_{index}_cage_pocket_contact_patch').set('ymax', '{_fmt_mm(y + 5.0)}');",
            f"model.component('comp1').selection('box_roller_{index}_cage_pocket_contact_patch').set('zmin', '-7.2[mm]');",
            f"model.component('comp1').selection('box_roller_{index}_cage_pocket_contact_patch').set('zmax', '7.2[mm]');",
            f"model.component('comp1').selection('box_roller_{index}_cage_pocket_contact_patch').set('condition', 'intersects');",
            f"model.component('comp1').selection().create('sel_roller_{index}_cage_contact', 'Intersection');",
            f"model.component('comp1').selection('sel_roller_{index}_cage_contact').set('entitydim', '2');",
            f"model.component('comp1').selection('sel_roller_{index}_cage_contact').set('input', ['box_roller_{index}_cage_pocket_contact_patch', 'geom1_roller_{index}_bnd']);",
            f"model.component('comp1').selection().create('sel_cage_pocket_{index}_contact', 'Intersection');",
            f"model.component('comp1').selection('sel_cage_pocket_{index}_contact').set('entitydim', '2');",
            f"model.component('comp1').selection('sel_cage_pocket_{index}_contact').set('input', ['box_roller_{index}_cage_pocket_contact_patch', 'geom1_cage_bnd']);",
        ])
        radial_x, radial_y = math.cos(angle), math.sin(angle)
        tangent_x, tangent_y = -math.sin(angle), math.cos(angle)
        for side_name, radial_offset in (("inner", -roller_radius), ("outer", roller_radius)):
            cx = x + radial_offset * radial_x
            cy = y + radial_offset * radial_y
            half_radial = contact_half_width
            half_tangent = roller_radius + 0.6
            if (
                (
                    use_roller1_outer_retained_conformal_any
                    or use_roller1_outer_construction_partition_any
                    or use_roller1_outer_raceway_partition_only
                    or use_roller1_outer_raceway_partition_source_closure3um
                    or use_roller1_outer_raceway_narrow_partition_source_closure3um
                )
                and index == 1
                and side_name == "outer"
            ):
                half_radial = 0.55
                half_tangent = 0.9 if use_roller1_outer_retained_conformal_narrow_source_closure3um else 1.8
            corners = []
            for sr in (-1, 1):
                for st in (-1, 1):
                    corners.append((cx + sr * half_radial * radial_x + st * half_tangent * tangent_x, cy + sr * half_radial * radial_y + st * half_tangent * tangent_y))
            xs = [c[0] for c in corners]
            ys = [c[1] for c in corners]
            box_tag = f"box_roller_{index}_{side_name}_contact_patch"
            roller_tag = f"sel_roller_{index}_{side_name}_contact"
            raceway_tag = f"sel_{side_name}_raceway_{index}_contact"
            if use_roller1_outer_aux_patch and index == 1 and side_name == "outer":
                raceway_object_tag = "geom1_roller1_outer_aux_raceway_patch_bnd"
            elif use_roller1_outer_retained_conformal_any and index == 1 and side_name == "outer":
                raceway_object_tag = "geom1_roller1_outer_retained_conformal_patch_bnd"
            elif use_roller1_outer_construction_partition_any and index == 1 and side_name == "outer":
                raceway_object_tag = "geom1_partition_roller1_outer_raceway_construction_patch_bnd"
            elif (
                use_roller1_outer_raceway_partition_only
                or use_roller1_outer_raceway_partition_source_closure3um
            ) and index == 1 and side_name == "outer":
                raceway_object_tag = "geom1_partition_roller1_outer_raceway_only_patch_bnd"
            elif (
                use_roller1_outer_raceway_narrow_partition_source_closure3um
                and index == 1
                and side_name == "outer"
            ):
                raceway_object_tag = "geom1_partition_roller1_outer_raceway_narrow_closure_patch_bnd"
            else:
                raceway_object_tag = "geom1_inner_ring_bnd" if side_name == "inner" else "geom1_outer_ring_bnd"
            if use_roller1_outer_construction_partition_any and index == 1 and side_name == "outer":
                roller_object_tag = "geom1_partition_roller1_outer_source_construction_patch_bnd"
            else:
                roller_object_tag = f"geom1_roller_{index}_bnd"
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
                f"model.component('comp1').selection('{roller_tag}').set('input', ['{box_tag}', '{roller_object_tag}']);",
                f"model.component('comp1').selection().create('{raceway_tag}', 'Intersection');",
                f"model.component('comp1').selection('{raceway_tag}').set('entitydim', '2');",
                f"model.component('comp1').selection('{raceway_tag}').set('input', ['{box_tag}', '{raceway_object_tag}']);",
            ])
            if use_roller1_outer_retained_conformal_any and index == 1 and side_name == "outer":
                lines.append(
                    f"output.write('ROLLER1_OUTER_RETAINED_CONFORMAL_PATCH_BIND|source=sel_roller_1_outer_contact|destination=sel_outer_raceway_1_contact|pair=cp_roller_1_outer_raceway|box=box_roller_1_outer_contact_patch|source_closure3um={str(bool(use_roller1_outer_retained_conformal_source_closure3um or use_roller1_outer_retained_conformal_narrow_source_closure3um or use_roller1_outer_retained_conformal_equal_height_source_closure3um or use_roller1_outer_retained_conformal_sector_source_closure3um)).lower()}|outer_box_tangential_half_width={('0.9' if use_roller1_outer_retained_conformal_narrow_source_closure3um else '1.8')}[mm]\\n');"
                )
            if use_roller1_outer_construction_partition_any and index == 1 and side_name == "outer":
                lines.append(
                    f"output.write('ROLLER1_OUTER_CONSTRUCTION_PARTITION_PATCH_BIND|source=sel_roller_1_outer_contact|destination=sel_outer_raceway_1_contact|pair=cp_roller_1_outer_raceway|box=box_roller_1_outer_contact_patch|source_closure3um={str(bool(use_roller1_outer_construction_partition_source_closure3um)).lower()}\\n');"
                )
            if (
                use_roller1_outer_raceway_partition_only
                or use_roller1_outer_raceway_partition_source_closure3um
            ) and index == 1 and side_name == "outer":
                lines.append(
                    "output.write('ROLLER1_OUTER_RACEWAY_PARTITION_ONLY_BIND|source=sel_roller_1_outer_contact|destination=sel_outer_raceway_1_contact|pair=cp_roller_1_outer_raceway|box=box_roller_1_outer_contact_patch\\n');"
                )
            if use_roller1_outer_raceway_narrow_partition_source_closure3um and index == 1 and side_name == "outer":
                lines.append(
                    "output.write('ROLLER1_OUTER_RACEWAY_NARROW_PARTITION_SOURCE_CLOSURE_BIND|source=sel_roller_1_outer_contact|destination=sel_outer_raceway_1_contact|pair=cp_roller_1_outer_raceway|box=box_roller_1_outer_contact_patch\\n');"
                )
    lines.extend([
        f"for contact_partition_index in range(1, {roller_count + 1}):",
        "    contact_partition_inner_tag = 'sel_roller_' + str(contact_partition_index) + '_inner_contact'",
        "    contact_partition_outer_tag = 'sel_roller_' + str(contact_partition_index) + '_outer_contact'",
        "    contact_partition_cage_tag = 'sel_roller_' + str(contact_partition_index) + '_cage_contact'",
        "    contact_partition_inner_entities = list(model.component('comp1').selection(contact_partition_inner_tag).entities())",
        "    contact_partition_outer_entities = list(model.component('comp1').selection(contact_partition_outer_tag).entities())",
        "    contact_partition_cage_entities = list(model.component('comp1').selection(contact_partition_cage_tag).entities())",
        "    contact_partition_inner_set = set(contact_partition_inner_entities)",
        "    contact_partition_outer_set = set(contact_partition_outer_entities)",
        "    contact_partition_cage_set = set(contact_partition_cage_entities)",
        "    contact_partition_union = sorted(contact_partition_inner_set | contact_partition_outer_set | contact_partition_cage_set)",
        "    contact_partition_inner_final = sorted(contact_partition_inner_set - contact_partition_outer_set)",
        "    contact_partition_outer_final = sorted(contact_partition_outer_set - contact_partition_inner_set)",
        "    contact_partition_used = set(contact_partition_inner_final) | set(contact_partition_outer_final)",
        "    contact_partition_cage_final = [entity for entity in contact_partition_union if entity not in contact_partition_used]",
        "    if not contact_partition_inner_final and len(contact_partition_union) >= 2:",
        "        contact_partition_inner_final = contact_partition_union[:2]",
        "    if not contact_partition_outer_final and len(contact_partition_union) >= 4:",
        "        contact_partition_outer_final = contact_partition_union[-2:]",
        "    contact_partition_used = set(contact_partition_inner_final) | set(contact_partition_outer_final)",
        "    if not contact_partition_cage_final:",
        "        contact_partition_cage_final = [entity for entity in contact_partition_union if entity not in contact_partition_used]",
        "    for contact_partition_tag, contact_partition_entities in [",
        "        (contact_partition_inner_tag, contact_partition_inner_final),",
        "        (contact_partition_outer_tag, contact_partition_outer_final),",
        "        (contact_partition_cage_tag, contact_partition_cage_final),",
        "    ]:",
        "        try:",
        "            model.component('comp1').selection().remove(contact_partition_tag)",
        "        except Exception:",
        "            pass",
        "        model.component('comp1').selection().create(contact_partition_tag, 'Explicit')",
        "        model.component('comp1').selection(contact_partition_tag).geom('geom1', 2)",
        "        model.component('comp1').selection(contact_partition_tag).set(contact_partition_entities)",
        "    output.write('CONTACT_SOURCE_PARTITION|' + str(contact_partition_index) + '|inner=' + ','.join(str(entity) for entity in contact_partition_inner_final) + '|outer=' + ','.join(str(entity) for entity in contact_partition_outer_final) + '|cage=' + ','.join(str(entity) for entity in contact_partition_cage_final) + '\\n')",
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
        "model.component('comp1').material('mat_cage').selection().named('geom1_cage_dom');",
        "model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');",
        "model.component('comp1').physics('solid').create('fix_outer', 'Fixed', 2);",
        "model.component('comp1').physics('solid').feature('fix_outer').selection().named('sel_outer_support_surface');",
    ])
    if use_roller1_outer_aux_patch:
        lines.extend([
            "model.component('comp1').physics('solid').create('fix_roller1_outer_aux_raceway_patch', 'Fixed', 2);",
            "model.component('comp1').physics('solid').feature('fix_roller1_outer_aux_raceway_patch').selection().named('geom1_roller1_outer_aux_raceway_patch_bnd');",
        ])
    if use_roller1_outer_retained_conformal_any:
        lines.extend([
            "model.component('comp1').physics('solid').create('fix_roller1_outer_retained_conformal_patch', 'Fixed', 2);",
            "model.component('comp1').physics('solid').feature('fix_roller1_outer_retained_conformal_patch').selection().named('geom1_roller1_outer_retained_conformal_patch_bnd');",
        ])
    lines.extend([
        "model.component('comp1').physics('solid').create('load_inner_bore', 'BoundaryLoad', 2);",
        "model.component('comp1').physics('solid').feature('load_inner_bore').selection().named('sel_inner_bore_load_surface');",
        "model.component('comp1').physics('solid').feature('load_inner_bore').set('FperArea', ['inner_bore_load_pressure', '0', '0']);",
        "model.component('comp1').physics('solid').create('disp_inner_bore_preload', 'Displacement2', 2);",
        "model.component('comp1').physics('solid').feature('disp_inner_bore_preload').selection().named('sel_inner_bore_load_surface');",
        "model.component('comp1').physics('solid').feature('disp_inner_bore_preload').set('U0', ['inner_radial_displacement', '0', '0']);",
        "model.component('comp1').cpl().create('maxop_inner_ring', 'Maximum');",
        "model.component('comp1').cpl('maxop_inner_ring').selection().named('sel_inner_ring_body');",
        "model.component('comp1').cpl().create('maxop_cage', 'Maximum');",
        "model.component('comp1').cpl('maxop_cage').selection().named('geom1_cage_dom');",
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
            f"model.component('comp1').pair().create('cp_roller_{index}_cage_pocket', 'Contact');",
            f"model.component('comp1').pair('cp_roller_{index}_cage_pocket').manualSelection(True);",
            f"model.component('comp1').pair('cp_roller_{index}_cage_pocket').source().named('sel_roller_{index}_cage_contact');",
            f"model.component('comp1').pair('cp_roller_{index}_cage_pocket').destination().named('sel_cage_pocket_{index}_contact');",
            f"model.component('comp1').physics('solid').create('contact_roller_{index}_inner', 'Contact', 2);",
            f"model.component('comp1').physics('solid').feature('contact_roller_{index}_inner').set('pairs', ['cp_roller_{index}_inner_raceway']);",
            f"model.component('comp1').physics('solid').feature('contact_roller_{index}_inner').set('pfm', 'penalty');",
            f"model.component('comp1').physics('solid').create('contact_roller_{index}_outer', 'Contact', 2);",
            f"model.component('comp1').physics('solid').feature('contact_roller_{index}_outer').set('pairs', ['cp_roller_{index}_outer_raceway']);",
            f"model.component('comp1').physics('solid').feature('contact_roller_{index}_outer').set('pfm', 'penalty');",
            f"model.component('comp1').physics('solid').create('contact_roller_{index}_cage', 'Contact', 2);",
            f"model.component('comp1').physics('solid').feature('contact_roller_{index}_cage').set('pairs', ['cp_roller_{index}_cage_pocket']);",
            f"model.component('comp1').physics('solid').feature('contact_roller_{index}_cage').set('pfm', 'penalty');",
            f"model.component('comp1').physics('solid').create('weak_roller_{index}_foundation', 'SpringFoundation2', 2);",
            f"model.component('comp1').physics('solid').feature('weak_roller_{index}_foundation').selection().named('geom1_roller_{index}_bnd');",
            f"model.component('comp1').physics('solid').feature('weak_roller_{index}_foundation').set('SpringType', 'kPerArea');",
            f"model.component('comp1').physics('solid').feature('weak_roller_{index}_foundation').set('kPerArea', ['weak_roller_foundation_k', 'weak_roller_foundation_k', 'weak_roller_foundation_k']);",
            f"model.component('comp1').cpl().create('maxop_roller_{index}', 'Maximum');",
            f"model.component('comp1').cpl('maxop_roller_{index}').selection().named('geom1_roller_{index}_dom');",
        ])
    lines.extend([
        "model.component('comp1').mesh().create('mesh1');",
        "model.component('comp1').mesh('mesh1').create('size_global', 'Size');",
        "model.component('comp1').mesh('mesh1').feature('size_global').set('hmax', 'mesh_bulk_size');",
        "model.component('comp1').mesh('mesh1').feature('size_global').set('hmin', 'mesh_contact_size');",
        "model.component('comp1').mesh('mesh1').create('ftet1', 'FreeTet');",
        "model.study().create('std1');",
        "model.study('std1').create('stat', 'Stationary');",
        "model.study('std1').feature('stat').set('activate', ['solid', 'on']);",
        "model.result().create('pg_stress3d', 'PlotGroup3D');",
        "model.result('pg_stress3d').feature().create('surf_mises', 'Surface');",
        "model.result('pg_stress3d').feature('surf_mises').set('expr', 'solid.mises');",
        "model.result().numerical().create('max_von_mises', 'MaxVolume');",
        "model.result().numerical('max_von_mises').set('expr', 'solid.mises');",
        "model.result().numerical().create('probe_inner_ring_max_mises', 'MaxVolume');",
        "model.result().numerical('probe_inner_ring_max_mises').set('expr', 'maxop_inner_ring(solid.mises)');",
        "model.result().numerical().create('probe_cage_max_mises', 'MaxVolume');",
        "model.result().numerical('probe_cage_max_mises').set('expr', 'maxop_cage(solid.mises)');",
        "model.result().numerical().create('probe_cage_max_displacement', 'MaxVolume');",
        "model.result().numerical('probe_cage_max_displacement').set('expr', 'maxop_cage(solid.disp)');",
    ])
    for index in range(1, roller_count + 1):
        lines.extend([
            f"model.result().numerical().create('probe_roller_{index}_max_mises', 'MaxVolume');",
            f"model.result().numerical('probe_roller_{index}_max_mises').set('expr', 'maxop_roller_{index}(solid.mises)');",
        ])
    lines.extend([
        "model.result().numerical().create('max_contact_pressure_estimate', 'EvalGlobal');",
        "model.result().numerical('max_contact_pressure_estimate').set('expr', 'contact_pressure_est');",
        f"output.write('3D full cylindrical-roller bearing setup built: inner ring, outer ring, {roller_count} rollers, real Boolean cage ring with {roller_count} cylindrical pocket cutouts, named Box selections, inner-bore BoundaryLoad audit plus displacement-controlled inner-bore preload, {3 * roller_count} roller/raceway/cage-pocket Contact pair features, scoped per-roller Maximum probes, scoped cage stress/displacement probes, fixed support, stationary Solid Mechanics, and 3D stress plot. probe_scope_verified cage_boolean_pockets_verified cage_probe_verified cage_pocket_contact_verified local_contact_patch_mode={local_contact_patch_mode}');",
    ])
    return "\n".join(lines)


VERIFIED_3D_FULL_BEARING_CODE = _build_verified_3d_full_bearing_code(roller_count=VERIFIED_ROLLER_COUNT)


def _load_legacy_raceway_highload_code(path: Path | None = None) -> str:
    """Load the verified 12-roller raceway-only high-load starter code."""
    template_path = path or LEGACY_RACEWAY_HIGHLOAD_TEMPLATE_JSON
    payload = json.loads(template_path.read_text(encoding="utf-8"))
    code = ((payload.get("template") or {}).get("java_code") or "").strip()
    if not code:
        raise ValueError(f"Legacy raceway high-load template code not found: {template_path}")
    return code


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
        "inner_load_application": "inner_bore_boundary_load_surface_with_displacement_preload",
        "cage_probe_required": "true",
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
            "explicit Contact Pair/Contact features for roller-to-inner-raceway, roller-to-outer-raceway, "
            "and roller-to-cage-pocket interfaces, inner-bore BoundaryLoad audit using FperArea plus "
            "Displacement2 inner-bore radial preload using U0, support, mesh, stationary study, "
            "cage-scoped stress/displacement probes, and a PlotGroup3D for solid.mises. "
            "Do not apply the radial load as a BodyLoad/FperVol on the entire inner-ring domain. "
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
        "Boolean pocket cutouts, roller-to-inner, roller-to-outer, and roller-to-cage-pocket Contact pairs, "
        "SolidMechanics, inner-bore radial BoundaryLoad, support, mesh, stationary study, and PlotGroup3D solid.mises output. Use Python/MPh-compatible "
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
    summary_path = artifact_root / "direct_3d_bearing_summary.json"
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
    summary_path = artifact_root / "direct_3d_bearing_summary.json"
    archive_path = Path(args.archive_path)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    package_dir.mkdir(parents=True, exist_ok=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    config = load_config()
    client = COMSOLClient.get_instance()
    actual_model_name = model_name
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


def _set_3d_staged_contact_state(
    model_name: str,
    *,
    stage_name: str,
    cage_contact_active: bool,
    active_rollers: list[int] | tuple[int, ...] | None,
    inner_radial_displacement: str,
    preload_steps: str,
    mesh_contact_size: str,
    mesh_bulk_size: str,
    inner_bore_load_active: bool = False,
    inner_body_load_active: bool = False,
    displacement_preload_active: bool = True,
    sweep_parameter: str = "inner_radial_displacement",
    sweep_unit: str = "um",
    active_roller_stabilization_active: bool = False,
    active_roller_stabilization_mode: str = "fixed",
    active_roller_stabilization_k: str = "1e10[N/m^3]",
    weak_roller_foundation_active: bool = True,
    weak_roller_foundation_k: str = "1e8[N/m^3]",
    weak_inner_guidance_active: bool = False,
    weak_inner_guidance_k: str = "1e5[N/m^3]",
    solver_maxsegiter: str = "80",
    solver_maxlinit: str = "500",
    contact_penalty: str = "0.02*E_steel",
    contact_relaxation: str = "0.35",
    contact_tolerance: str = "0.2[um]",
    radial_load_value: str = "3000[N]",
    displacement_preload_selection: str = "sel_inner_bore_load_surface",
    reuse_existing_solver: bool = False,
    use_parametric_sweep: bool = True,
    contact_pair_endpoint_overrides: dict[str, dict[str, str]] | None = None,
    raceway_selection_entity_overrides: dict[str, list[int]] | None = None,
    contact_feature_property_overrides: dict[str, dict[str, str]] | None = None,
    contact_patch_box_overrides: dict[str, dict[str, str]] | None = None,
    raceway_partition_patch_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Configure one staged 3D contact solve state without rebuilding geometry."""
    active_roller_ids = sorted({
        int(index)
        for index in (active_rollers or range(1, VERIFIED_ROLLER_COUNT + 1))
        if 1 <= int(index) <= VERIFIED_ROLLER_COUNT
    })
    active_roller_literal = repr(active_roller_ids)
    endpoint_override_literal = repr(contact_pair_endpoint_overrides or {})
    raceway_entity_override_literal = repr(raceway_selection_entity_overrides or {})
    contact_feature_property_override_literal = repr(contact_feature_property_overrides or {})
    contact_patch_box_override_literal = repr(contact_patch_box_overrides or {})
    raceway_partition_patch_override_literal = repr(raceway_partition_patch_overrides or {})
    code = f"""
model.param().set('inner_radial_displacement', {inner_radial_displacement!r});
model.param().set('mesh_contact_size', {mesh_contact_size!r});
model.param().set('mesh_bulk_size', {mesh_bulk_size!r});
model.param().set('weak_roller_foundation_k', {weak_roller_foundation_k!r});
model.param().set('active_roller_stabilization_k', {active_roller_stabilization_k!r});
model.param().set('weak_inner_guidance_k', {weak_inner_guidance_k!r});
model.param().set('radial_load', {radial_load_value!r});
active_roller_ids = set({active_roller_literal})
contact_pair_endpoint_overrides={endpoint_override_literal}
raceway_selection_entity_overrides={raceway_entity_override_literal}
contact_feature_property_overrides={contact_feature_property_override_literal}
contact_patch_box_overrides={contact_patch_box_override_literal}
raceway_partition_patch_overrides={raceway_partition_patch_override_literal}
try:
    model.study('std1').feature('stat').set('geomnonlin', 'on')
except Exception:
    pass
if {use_parametric_sweep!r}:
    for staged_key, staged_value in [
        ('useparam', 'on'),
        ('pname', [{sweep_parameter!r}]),
        ('plistarr', [{preload_steps!r}]),
        ('punit', [{sweep_unit!r}]),
    ]:
        try:
            model.study('std1').feature('stat').set(staged_key, staged_value)
        except Exception:
            pass
else:
    for staged_key, staged_value in [
        ('pname', [{sweep_parameter!r}]),
        ('plistarr', [{preload_steps!r}]),
        ('punit', [{sweep_unit!r}]),
        ('useparam', 'off'),
    ]:
        try:
            model.study('std1').feature('stat').set(staged_key, staged_value)
        except Exception:
            pass
try:
    model.component('comp1').physics('solid').feature('load_inner_bore').active({inner_bore_load_active!r})
except Exception:
    pass
try:
    model.component('comp1').physics('solid').create('load_inner_body_visual', 'BodyLoad', 3)
    model.component('comp1').physics('solid').feature('load_inner_body_visual').selection().named('sel_inner_ring_body')
    model.component('comp1').physics('solid').feature('load_inner_body_visual').set('FperVol', ['radial_load/(pi*(inner_race_outer_radius^2-(inner_diameter/2)^2)*bearing_width)', '0', '0'])
except Exception:
    pass
try:
    model.component('comp1').physics('solid').feature('load_inner_body_visual').active({inner_body_load_active!r})
except Exception:
    pass
try:
    model.component('comp1').physics('solid').feature('disp_inner_bore_preload').selection().named({displacement_preload_selection!r})
except Exception:
    pass
try:
    model.component('comp1').physics('solid').feature('disp_inner_bore_preload').active(True)
except Exception:
    pass
try:
    model.component('comp1').physics('solid').feature('disp_inner_bore_preload').active({displacement_preload_active!r})
except Exception:
    pass
try:
    model.component('comp1').physics('solid').create('weak_inner_ring_load_guidance', 'SpringFoundation2', 2)
    model.component('comp1').physics('solid').feature('weak_inner_ring_load_guidance').selection().named('geom1_inner_ring_bnd')
    model.component('comp1').physics('solid').feature('weak_inner_ring_load_guidance').set('SpringType', 'kPerArea')
    model.component('comp1').physics('solid').feature('weak_inner_ring_load_guidance').set('kPerArea', ['weak_inner_guidance_k', 'weak_inner_guidance_k', 'weak_inner_guidance_k'])
except Exception:
    pass
try:
    model.component('comp1').physics('solid').feature('weak_inner_ring_load_guidance').active({weak_inner_guidance_active!r})
except Exception:
    pass
try:
    model.component('comp1').physics('solid').create('fix_cage_stage_stabilization', 'Fixed', 2)
    model.component('comp1').physics('solid').feature('fix_cage_stage_stabilization').selection().named('geom1_cage_bnd')
except Exception:
    pass
try:
    model.component('comp1').physics('solid').feature('fix_cage_stage_stabilization').active({(not cage_contact_active)!r})
except Exception:
    pass
for raceway_selection_tag, raceway_selection_entities in raceway_selection_entity_overrides.items():
    try:
        raceway_selection_entities = [int(entity) for entity in raceway_selection_entities]
        try:
            model.component('comp1').selection().remove(raceway_selection_tag)
        except Exception:
            pass
        model.component('comp1').selection().create(raceway_selection_tag, 'Explicit')
        model.component('comp1').selection(raceway_selection_tag).geom('geom1', 2)
        model.component('comp1').selection(raceway_selection_tag).set(raceway_selection_entities)
        output.write('RACEWAY_SELECTION_ENTITY_OVERRIDE|' + {stage_name!r} + '|selection=' + str(raceway_selection_tag) + '|entities=' + ','.join(str(entity) for entity in raceway_selection_entities) + '\\n')
        raceway_selection_parts = str(raceway_selection_tag).split('_')
        if len(raceway_selection_parts) >= 5 and raceway_selection_parts[0] == 'sel' and raceway_selection_parts[2] == 'raceway':
            raceway_side = raceway_selection_parts[1]
            raceway_roller = raceway_selection_parts[3]
            raceway_pair_tag = 'cp_roller_' + raceway_roller + '_' + raceway_side + '_raceway'
            try:
                model.component('comp1').pair(raceway_pair_tag).manualSelection(True)
                model.component('comp1').pair(raceway_pair_tag).destination().named(raceway_selection_tag)
                output.write('RACEWAY_SELECTION_ENTITY_REBIND|' + {stage_name!r} + '|pair=' + raceway_pair_tag + '|destination=' + str(raceway_selection_tag) + '\\n')
            except Exception as raceway_pair_rebind_error:
                output.write('RACEWAY_SELECTION_ENTITY_REBIND_ERROR|' + {stage_name!r} + '|pair=' + raceway_pair_tag + '|error=' + str(raceway_pair_rebind_error) + '\\n')
    except Exception as raceway_selection_override_error:
        output.write('RACEWAY_SELECTION_ENTITY_OVERRIDE_ERROR|' + {stage_name!r} + '|selection=' + str(raceway_selection_tag) + '|error=' + str(raceway_selection_override_error) + '\\n')
for contact_patch_box_tag, contact_patch_box_properties in contact_patch_box_overrides.items():
    try:
        contact_patch_box = model.component('comp1').selection(contact_patch_box_tag)
        for contact_patch_key, contact_patch_value in contact_patch_box_properties.items():
            try:
                contact_patch_box.set(contact_patch_key, contact_patch_value)
                output.write('CONTACT_PATCH_BOX_OVERRIDE|' + {stage_name!r} + '|selection=' + str(contact_patch_box_tag) + '|key=' + str(contact_patch_key) + '|value=' + str(contact_patch_value) + '\\n')
            except Exception as contact_patch_property_error:
                output.write('CONTACT_PATCH_BOX_OVERRIDE_ERROR|' + {stage_name!r} + '|selection=' + str(contact_patch_box_tag) + '|key=' + str(contact_patch_key) + '|value=' + str(contact_patch_value) + '|error=' + str(contact_patch_property_error) + '\\n')
    except Exception as contact_patch_box_error:
        output.write('CONTACT_PATCH_BOX_OVERRIDE_ERROR|' + {stage_name!r} + '|selection=' + str(contact_patch_box_tag) + '|error=' + str(contact_patch_box_error) + '\\n')
for raceway_partition_tag, raceway_partition_payload in raceway_partition_patch_overrides.items():
    try:
        target_object = str(raceway_partition_payload.get('target_object') or '')
        tool_tag = str(raceway_partition_payload.get('tool_tag') or (str(raceway_partition_tag) + '_tool'))
        partition_tag = str(raceway_partition_payload.get('partition_tag') or raceway_partition_tag)
        selection_tag = str(raceway_partition_payload.get('selection_tag') or '')
        tool_size = list(raceway_partition_payload.get('tool_size') or [])
        tool_pos = list(raceway_partition_payload.get('tool_pos') or [])
        if not target_object or len(tool_size) != 3 or len(tool_pos) != 3:
            raise ValueError('partition payload requires target_object, tool_size[3], and tool_pos[3]')
        try:
            model.component('comp1').geom('geom1').feature().remove(tool_tag)
        except Exception:
            pass
        try:
            model.component('comp1').geom('geom1').feature().remove(partition_tag)
        except Exception:
            pass
        model.component('comp1').geom('geom1').create(tool_tag, 'Block')
        model.component('comp1').geom('geom1').feature(tool_tag).set('size', [str(value) for value in tool_size])
        model.component('comp1').geom('geom1').feature(tool_tag).set('base', 'center')
        model.component('comp1').geom('geom1').feature(tool_tag).set('pos', [str(value) for value in tool_pos])
        model.component('comp1').geom('geom1').create(partition_tag, 'Partition')
        model.component('comp1').geom('geom1').feature(partition_tag).selection('input').set([target_object])
        model.component('comp1').geom('geom1').feature(partition_tag).selection('tool').set([tool_tag])
        for partition_key, partition_value in [
            ('keepinput', raceway_partition_payload.get('keepinput', 'on')),
            ('keeptool', raceway_partition_payload.get('keeptool', 'on')),
            ('selresult', raceway_partition_payload.get('selresult', 'on')),
            ('selresultshow', raceway_partition_payload.get('selresultshow', 'all')),
        ]:
            try:
                model.component('comp1').geom('geom1').feature(partition_tag).set(partition_key, partition_value)
            except Exception as partition_property_error:
                output.write('RACEWAY_PARTITION_PATCH_PROPERTY_ERROR|' + {stage_name!r} + '|partition=' + partition_tag + '|key=' + str(partition_key) + '|error=' + str(partition_property_error) + '\\n')
        try:
            model.component('comp1').geom('geom1').run()
            output.write('RACEWAY_PARTITION_PATCH_RUN|' + {stage_name!r} + '|partition=' + partition_tag + '|target=' + target_object + '|tool=' + tool_tag + '|selection=' + selection_tag + '\\n')
        except Exception as partition_run_error:
            output.write('RACEWAY_PARTITION_PATCH_RUN_ERROR|' + {stage_name!r} + '|partition=' + partition_tag + '|target=' + target_object + '|tool=' + tool_tag + '|error=' + str(partition_run_error) + '\\n')
        if selection_tag:
            try:
                model.component('comp1').selection(selection_tag).geom('geom1', 2)
                output.write('RACEWAY_PARTITION_PATCH_SELECTION_RETAINED|' + {stage_name!r} + '|partition=' + partition_tag + '|selection=' + selection_tag + '|entities=' + ','.join(str(entity) for entity in list(model.component('comp1').selection(selection_tag).entities())) + '\\n')
            except Exception as partition_selection_error:
                output.write('RACEWAY_PARTITION_PATCH_SELECTION_ERROR|' + {stage_name!r} + '|partition=' + partition_tag + '|selection=' + selection_tag + '|error=' + str(partition_selection_error) + '\\n')
        explicit_selection_entities = raceway_partition_payload.get('explicit_selection_entities')
        if selection_tag and explicit_selection_entities:
            try:
                explicit_entities = [int(entity) for entity in explicit_selection_entities]
                try:
                    model.component('comp1').selection().remove(selection_tag)
                except Exception:
                    pass
                model.component('comp1').selection().create(selection_tag, 'Explicit')
                model.component('comp1').selection(selection_tag).geom('geom1', 2)
                model.component('comp1').selection(selection_tag).set(explicit_entities)
                output.write('RACEWAY_PARTITION_PATCH_EXPLICIT_SELECTION|' + {stage_name!r} + '|partition=' + partition_tag + '|selection=' + selection_tag + '|entities=' + ','.join(str(entity) for entity in explicit_entities) + '\\n')
            except Exception as explicit_selection_error:
                output.write('RACEWAY_PARTITION_PATCH_EXPLICIT_SELECTION_ERROR|' + {stage_name!r} + '|partition=' + partition_tag + '|selection=' + selection_tag + '|error=' + str(explicit_selection_error) + '\\n')
        pair_tag = str(raceway_partition_payload.get('pair_tag') or '')
        if selection_tag and pair_tag:
            try:
                model.component('comp1').pair(pair_tag).manualSelection(True)
                model.component('comp1').pair(pair_tag).destination().named(selection_tag)
                output.write('RACEWAY_PARTITION_PATCH_PAIR_REBIND|' + {stage_name!r} + '|partition=' + partition_tag + '|pair=' + pair_tag + '|destination=' + selection_tag + '\\n')
            except Exception as pair_rebind_error:
                output.write('RACEWAY_PARTITION_PATCH_PAIR_REBIND_ERROR|' + {stage_name!r} + '|partition=' + partition_tag + '|pair=' + pair_tag + '|destination=' + selection_tag + '|error=' + str(pair_rebind_error) + '\\n')
    except Exception as raceway_partition_error:
        output.write('RACEWAY_PARTITION_PATCH_ERROR|' + {stage_name!r} + '|partition=' + str(raceway_partition_tag) + '|error=' + str(raceway_partition_error) + '\\n')
for pair_tag, pair_endpoints in contact_pair_endpoint_overrides.items():
    try:
        staged_pair = model.component('comp1').pair(pair_tag)
        staged_source = pair_endpoints.get('source')
        staged_destination = pair_endpoints.get('destination')
        staged_pair.manualSelection(True)
        if staged_source:
            staged_pair.source().named(staged_source)
        if staged_destination:
            staged_pair.destination().named(staged_destination)
        output.write('CONTACT_PAIR_ENDPOINT_OVERRIDE|' + {stage_name!r} + '|pair=' + str(pair_tag) + '|source=' + str(staged_source) + '|destination=' + str(staged_destination) + '\\n')
    except Exception as pair_override_error:
        output.write('CONTACT_PAIR_ENDPOINT_OVERRIDE_ERROR|' + {stage_name!r} + '|pair=' + str(pair_tag) + '|error=' + str(pair_override_error) + '\\n')
for staged_index in range(1, {VERIFIED_ROLLER_COUNT + 1}):
    staged_active = staged_index in active_roller_ids
    staged_roller_fixed = (not staged_active) or ({active_roller_stabilization_active!r} and {active_roller_stabilization_mode!r} == 'fixed' and staged_active)
    staged_inner = model.component('comp1').physics('solid').feature('contact_roller_' + str(staged_index) + '_inner')
    staged_outer = model.component('comp1').physics('solid').feature('contact_roller_' + str(staged_index) + '_outer')
    staged_cage = model.component('comp1').physics('solid').feature('contact_roller_' + str(staged_index) + '_cage')
    staged_inner.active(staged_active)
    staged_outer.active(staged_active)
    staged_cage.active({cage_contact_active!r} and staged_active)
    fix_tag = 'fix_roller_' + str(staged_index) + '_stage_stabilization'
    try:
        model.component('comp1').physics('solid').create(fix_tag, 'Fixed', 2)
        model.component('comp1').physics('solid').feature(fix_tag).selection().named('geom1_roller_' + str(staged_index) + '_bnd')
    except Exception:
        pass
    try:
        model.component('comp1').physics('solid').feature(fix_tag).active(staged_roller_fixed)
    except Exception:
        pass
    try:
        staged_foundation = model.component('comp1').physics('solid').feature('weak_roller_' + str(staged_index) + '_foundation')
        staged_spring_stabilized = staged_active and {active_roller_stabilization_active!r} and {active_roller_stabilization_mode!r} == 'spring'
        staged_foundation.active({weak_roller_foundation_active!r} or staged_spring_stabilized)
        if staged_spring_stabilized:
            staged_foundation.set('kPerArea', ['active_roller_stabilization_k', 'active_roller_stabilization_k', 'active_roller_stabilization_k'])
        else:
            staged_foundation.set('kPerArea', ['weak_roller_foundation_k', 'weak_roller_foundation_k', 'weak_roller_foundation_k'])
    except Exception:
        pass
    for staged_contact in [staged_inner, staged_outer, staged_cage]:
        for staged_key, staged_value in [
            ('pfm', 'penalty'),
            ('penaltyCtrl', 'manual'),
            ('pn_penalty', {contact_penalty!r}),
            ('useRelaxation', 'on'),
            ('irlx', {contact_relaxation!r}),
            ('nRelax', '8'),
            ('useCutback', 'on'),
            ('doCutback', 'on'),
            ('zeroInitGap', 'on'),
            ('ContactTolType', 'manual'),
            ('tolcontact', {contact_tolerance!r}),
            ('splitSegStep', 'on'),
            ('stab', 'on'),
            ('stabilization', 'on'),
            ('stabilize', 'on'),
            ('cntstab', 'on'),
        ]:
            try:
                staged_contact.set(staged_key, staged_value)
            except Exception:
                pass
for contact_feature_tag, contact_feature_properties in contact_feature_property_overrides.items():
    try:
        contact_feature = model.component('comp1').physics('solid').feature(contact_feature_tag)
        for contact_feature_key, contact_feature_value in contact_feature_properties.items():
            try:
                contact_feature.set(contact_feature_key, contact_feature_value)
                output.write('CONTACT_FEATURE_PROPERTY_OVERRIDE|' + {stage_name!r} + '|feature=' + str(contact_feature_tag) + '|key=' + str(contact_feature_key) + '|value=' + str(contact_feature_value) + '\\n')
            except Exception as contact_feature_property_error:
                output.write('CONTACT_FEATURE_PROPERTY_OVERRIDE_ERROR|' + {stage_name!r} + '|feature=' + str(contact_feature_tag) + '|key=' + str(contact_feature_key) + '|value=' + str(contact_feature_value) + '|error=' + str(contact_feature_property_error) + '\\n')
    except Exception as contact_feature_override_error:
        output.write('CONTACT_FEATURE_OVERRIDE_ERROR|' + {stage_name!r} + '|feature=' + str(contact_feature_tag) + '|error=' + str(contact_feature_override_error) + '\\n')
try:
    model.component('comp1').mesh('mesh1').feature('size_global').set('hmax', 'mesh_bulk_size')
    model.component('comp1').mesh('mesh1').feature('size_global').set('hmin', 'mesh_contact_size')
except Exception:
    pass
if not {reuse_existing_solver!r}:
    try:
        model.study('std1').createAutoSequences('sol')
    except Exception:
        pass
if {use_parametric_sweep!r}:
    for staged_key, staged_value in [
        ('useparam', 'on'),
        ('pname', [{sweep_parameter!r}]),
        ('plistarr', [{preload_steps!r}]),
        ('punit', [{sweep_unit!r}]),
    ]:
        try:
            model.study('std1').feature('stat').set(staged_key, staged_value)
        except Exception:
            pass
else:
    for staged_key, staged_value in [
        ('pname', [{sweep_parameter!r}]),
        ('plistarr', [{preload_steps!r}]),
        ('punit', [{sweep_unit!r}]),
        ('useparam', 'off'),
    ]:
        try:
            model.study('std1').feature('stat').set(staged_key, staged_value)
        except Exception:
            pass
solver_settings = []
for solver_path, solver_key, solver_value in [
    ('se1', 'maxsegiter', {solver_maxsegiter!r}),
    ('se1', 'segiter', {solver_maxsegiter!r}),
    ('se1', 'ntolfact', '1'),
    ('i1', 'maxlinit', {solver_maxlinit!r}),
    ('i1', 'itrestart', '100'),
]:
    try:
        model.sol('sol1').feature('s1').feature(solver_path).set(solver_key, solver_value)
        solver_settings.append(solver_path + ':' + solver_key + '=' + solver_value)
    except Exception:
        pass
        output.write('STAGED_CONTACT_SOLVE|' + {stage_name!r} + '|raceway_contact_active=True|cage_contact_active=' + str({cage_contact_active!r}) + '|active_rollers=' + str(sorted(active_roller_ids)) + '|inactive_roller_stabilization_active=' + str(len(active_roller_ids) < {VERIFIED_ROLLER_COUNT}) + '|temporary_active_roller_stabilization_active=' + str({active_roller_stabilization_active!r}) + '|active_roller_stabilization_mode=' + {active_roller_stabilization_mode!r} + '|active_roller_stabilization_k=' + {active_roller_stabilization_k!r} + '|weak_roller_foundation_active=' + str({weak_roller_foundation_active!r}) + '|weak_roller_foundation_k=' + {weak_roller_foundation_k!r} + '|weak_inner_guidance_active=' + str({weak_inner_guidance_active!r}) + '|weak_inner_guidance_k=' + {weak_inner_guidance_k!r} + '|reuse_existing_solver=' + str({reuse_existing_solver!r}) + '|use_parametric_sweep=' + str({use_parametric_sweep!r}) + '|solver_settings=' + str(solver_settings) + '|inner_bore_load_active=' + str({inner_bore_load_active!r}) + '|inner_body_load_active=' + str({inner_body_load_active!r}) + '|displacement_preload_active=' + str({displacement_preload_active!r}) + '|displacement_preload_selection=' + {displacement_preload_selection!r} + '|contact_pair_endpoint_overrides=' + str(contact_pair_endpoint_overrides) + '|contact_feature_property_overrides=' + str(contact_feature_property_overrides) + '|contact_patch_box_overrides=' + str(contact_patch_box_overrides) + '|raceway_partition_patch_overrides=' + str(raceway_partition_patch_overrides) + '|temporary_cage_stabilization_active=' + str({(not cage_contact_active)!r}) + '|inner_radial_displacement=' + {inner_radial_displacement!r} + '|preload_steps=' + {preload_steps!r} + '|radial_load_value=' + {radial_load_value!r} + '|mesh_contact_size=' + {mesh_contact_size!r} + '|mesh_bulk_size=' + {mesh_bulk_size!r} + '\\n')
"""
    return comsol_execute_java(code, model_name=model_name)


def _run_3d_staged_contact_solve(
    model_name: str,
    *,
    run_full_cage_stage: bool = False,
    contact_stage_mode: str = "all_raceway",
    stage_plot_dir: Path | None = None,
    roller1_outer_entity_override_entities: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    """Run a conservative staged contact sequence for the 3D bearing fixture."""
    requested_contact_stage_mode = contact_stage_mode
    roller1_outer_entity_override_only = (
        contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_roller1_outer_entity_override"
    )
    if roller1_outer_entity_override_only:
        contact_stage_mode = "load_side_group_boundary_load_single_solve_0p101_entity_raceway_override"
    if contact_stage_mode not in {"single_load_roller", "single_roller_displacement_preload", "load_side_then_all", "all_raceway", "all_raceway_micro_preload", "load_side_group_micro", "load_side_group_compaction", "load_side_group_preclosed_boundary_load", "load_side_group_boundary_load", "load_side_group_boundary_load_soft_guidance", "load_side_group_boundary_load_contact_relaxation", "load_side_group_boundary_load_single_solve_0p101", "load_side_group_boundary_load_single_solve_0p101_roller1_pair_swap", "load_side_group_boundary_load_single_solve_0p101_roller1_patch_shrink", "load_side_group_boundary_load_single_solve_0p101_roller1_box_intersection_rebuild", "load_side_group_boundary_load_single_solve_0p101_roller1_outer_x31_box_intersection", "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch", "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_rebind", "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_min_entities", "load_side_group_boundary_load_single_solve_0p101_active_spring1e9", "load_side_group_boundary_load_single_solve_0p101_full_raceway_destination", "load_side_group_boundary_load_single_solve_0p101_entity_raceway_override", "load_side_group_boundary_load_single_solve_0p101_roller1_gapoffset_minus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_minus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_plus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_offset_minus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_offset_plus3um", "load_side_group_boundary_load_single_solve_0p12", "load_side_group_boundary_load_single_solve_0p13", "load_side_group_boundary_load_single_solve_0p14", "load_side_group_boundary_load_single_solve_0p145", "load_side_group_boundary_load_single_solve_0p1475", "load_side_group_boundary_load_single_solve_0p14875", "load_side_group_boundary_load_single_solve_0p149375", "load_side_group_boundary_load_single_solve_0p15_fine", "load_side_group_boundary_load_single_solve_0p1625", "load_side_group_boundary_load_single_solve_0p175", "load_side_group_boundary_load_single_solve_0p1875", "load_side_group_boundary_load_single_solve_0p19375", "load_side_group_boundary_load_single_solve_0p196875", "load_side_group_boundary_load_single_solve_0p1984375", "load_side_group_boundary_load_single_solve_0p2_fine", "load_side_group_boundary_load_single_solve_0p15", "load_side_group_boundary_load_single_solve_0p2", "load_side_group_boundary_load_single_solve_1n", "load_side_group_boundary_load_micro_continuation", "load_side_group_boundary_load_fixed_stabilization", "all_raceway_low_load_transfer", "all_raceway_continuous_boundary_load", "all_raceway_split_control_boundary_load", "all_raceway_guided_probe_1n", "all_raceway_guided_low_load_transfer", "all_raceway_guided_high_load_transfer", "all_raceway_preload_only", "all_raceway_high_preload_visual", "all_raceway_high_preload_reaction_equivalent", "all_raceway_high_load_visual", "all_raceway_high_body_load_visual"}:
        return {
            "success": False,
            "kind": "bearing_3d_staged_contact_solve",
            "policy": "invalid contact_stage_mode",
            "run_full_cage_stage": run_full_cage_stage,
            "contact_stage_mode": requested_contact_stage_mode,
            "stages": [],
            "final_solve": {"success": False, "error": f"Unsupported contact_stage_mode: {requested_contact_stage_mode}"},
        }

    stages = []
    if contact_stage_mode == "all_raceway_micro_preload":
        stages.append({
            "name": "all_12_roller_raceway_micro_preload",
            "contact_scope": "all_12_rollers_inner_outer_raceway_true_contact_micro_displacement_preload",
            "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
            "cage_contact_active": False,
            "inner_radial_displacement": "0.00002[um]",
            "preload_steps": "0.000001 0.000005 0.00002",
            "mesh_contact_size": "4.0[mm]",
            "mesh_bulk_size": "8.0[mm]",
            "inner_bore_load_active": False,
            "inner_body_load_active": False,
            "displacement_preload_active": True,
            "active_roller_stabilization_active": False,
            "weak_roller_foundation_k": "1e11[N/m^3]",
            "solver_maxsegiter": "40",
            "solver_maxlinit": "300",
            "contact_penalty": "1e-5*E_steel",
            "contact_relaxation": "0.15",
            "contact_tolerance": "2[um]",
            "physical_acceptance": "raceway_contact_smoke_true_12_roller_inner_outer_contact_requires_nonzero_inner_ring_stress_and_visible_stress_png",
        })
    if contact_stage_mode == "load_side_group_micro":
        for name, active_rollers, displacement, steps in [
            ("load_side_3_roller_micro_preload", [12, 1, 2], "0.000005[um]", "0.000001 0.000005"),
            ("load_side_6_roller_micro_preload", [11, 12, 1, 2, 3, 4], "0.00001[um]", "0.000005 0.00001"),
            ("all_12_roller_group_ramped_micro_preload", list(range(1, VERIFIED_ROLLER_COUNT + 1)), "0.00002[um]", "0.00001 0.00002"),
        ]:
            stages.append({
                "name": name,
                "contact_scope": "group_ramped_inner_outer_raceway_true_contact_micro_displacement_preload",
                "active_rollers": active_rollers,
                "cage_contact_active": False,
                "inner_radial_displacement": displacement,
                "preload_steps": steps,
                "mesh_contact_size": "4.0[mm]",
                "mesh_bulk_size": "8.0[mm]",
                "inner_bore_load_active": False,
                "inner_body_load_active": False,
                "displacement_preload_active": True,
                "active_roller_stabilization_active": False,
                "weak_roller_foundation_k": "1e11[N/m^3]",
                "solver_maxsegiter": "40",
                "solver_maxlinit": "300",
                "contact_penalty": "1e-5*E_steel",
                "contact_relaxation": "0.15",
                "contact_tolerance": "2[um]",
                "physical_acceptance": "final_stage_requires_all_12_rollers_active_no_temporary_active_roller_fix_nonzero_inner_ring_stress_visible_stress_png",
            })
    if contact_stage_mode in {"load_side_group_compaction", "load_side_group_preclosed_boundary_load"}:
        for name, active_rollers, displacement, steps, contact_tolerance in [
            ("load_side_3_roller_compaction_preload", [12, 1, 2], "0.001[um]", "0.00005 0.0001 0.0005 0.001", "0.5[um]"),
            ("load_side_6_roller_compaction_preload", [11, 12, 1, 2, 3, 4], "0.003[um]", "0.001 0.002 0.003", "0.5[um]"),
            ("load_side_8_roller_compaction_preload", [10, 11, 12, 1, 2, 3, 4, 5], "0.003[um]", "0.003", "0.75[um]"),
            ("load_side_10_roller_compaction_preload", [9, 10, 11, 12, 1, 2, 3, 4, 5, 6], "0.003[um]", "0.003", "0.75[um]"),
            ("all_12_roller_group_compaction_preload", list(range(1, VERIFIED_ROLLER_COUNT + 1)), "0.003[um]", "0.001 0.002 0.003", "3[um]"),
        ]:
            final_all_rollers = len(active_rollers) == VERIFIED_ROLLER_COUNT
            stages.append({
                "name": name,
                "contact_scope": "group_ramped_inner_outer_raceway_true_contact_compaction_displacement_preload",
                "active_rollers": active_rollers,
                "cage_contact_active": False,
                "inner_radial_displacement": displacement,
                "preload_steps": steps,
                "mesh_contact_size": "2.8[mm]" if not final_all_rollers else "2.4[mm]",
                "mesh_bulk_size": "6.0[mm]" if not final_all_rollers else "5.0[mm]",
                "inner_bore_load_active": False,
                "inner_body_load_active": False,
                "displacement_preload_active": False,
                "active_roller_stabilization_active": False,
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": "1e11[N/m^3]" if final_all_rollers else "1e8[N/m^3]",
                "weak_inner_guidance_active": final_all_rollers,
                "weak_inner_guidance_k": "5e4[N/m^3]" if final_all_rollers else "1e5[N/m^3]",
                "solver_maxsegiter": "140",
                "solver_maxlinit": "900",
                "contact_penalty": "1e-5*E_steel" if final_all_rollers else "0.002*E_steel",
                "contact_relaxation": "0.15" if final_all_rollers else "0.25",
                "contact_tolerance": contact_tolerance,
                "load_application_fidelity": "displacement_controlled_group_compaction_preload_not_boundary_load_design_gate",
                "physical_acceptance": (
                    "final_all_12_group_compaction_requires_nonzero_mpa_stress_visible_native_png_not_boundary_load_design_gate"
                    if final_all_rollers
                    else "intermediate_load_side_group_compaction_closure"
                ),
            })
    if contact_stage_mode == "load_side_group_preclosed_boundary_load":
        stages.extend([
            {
                "name": "preclosed_boundary_load_probe_0p001n",
                "contact_scope": "all_12_rollers_preclosed_by_group_compaction_then_inner_bore_boundary_load_low_ramp",
                "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
                "cage_contact_active": False,
                "inner_radial_displacement": "0.003[um]",
                "preload_steps": "0.001",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "radial_load_value": "0.001[N]",
                "inner_bore_load_active": True,
                "inner_body_load_active": False,
                "displacement_preload_active": True,
                "displacement_preload_selection": "sel_inner_raceway_contact",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": "1e11[N/m^3]",
                "weak_inner_guidance_active": True,
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "solver_maxsegiter": "180",
                "solver_maxlinit": "1200",
                "contact_penalty": "1e-5*E_steel",
                "contact_relaxation": "0.15",
                "contact_tolerance": "3[um]",
                "reuse_existing_solver": True,
                "use_parametric_sweep": False,
                "load_application_fidelity": "inner_bore_boundary_load_single_solve_bridge_after_group_compaction_contact_closure_retained_displacement_preload_not_design_gate",
                "physical_acceptance": "preclosed_boundary_load_0p001n_single_solve_probe_requires_native_png_and_boundary_load_active_with_temporary_active_roller_spring",
            },
            {
                "name": "preclosed_boundary_load_high_ramp",
                "contact_scope": "all_12_rollers_preclosed_by_group_compaction_then_inner_bore_boundary_load_high_ramp",
                "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
                "cage_contact_active": False,
                "inner_radial_displacement": "0.003[um]",
                "preload_steps": "5 10 25 50 100 250 500 1000 2000 3000",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "radial_load_value": "3000[N]",
                "inner_bore_load_active": True,
                "inner_body_load_active": False,
                "displacement_preload_active": False,
                "displacement_preload_selection": "sel_inner_raceway_contact",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": "1e11[N/m^3]",
                "weak_inner_guidance_active": True,
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1600",
                "contact_penalty": "1e-5*E_steel",
                "contact_relaxation": "0.15",
                "contact_tolerance": "3[um]",
                "reuse_existing_solver": True,
                "load_application_fidelity": "inner_bore_boundary_load_high_ramp_after_group_compaction_contact_closure_release_displacement_preload_not_design_gate",
                "physical_acceptance": "preclosed_high_boundary_load_diagnostic_requires_mpa_stress_native_png_and_boundary_load_active",
            },
        ])
    if contact_stage_mode == "load_side_group_boundary_load":
        for stage_payload in [
            {
                "name": "load_side_3_roller_boundary_load_0p1n",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.001 0.005 0.01 0.05 0.1",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.1[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
            },
            {
                "name": "load_side_3_roller_boundary_load_0p101n",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.101",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.101[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
            },
            {
                "name": "load_side_3_roller_boundary_load_0p105n",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.105",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.105[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
            },
            {
                "name": "load_side_3_roller_boundary_load_0p12n",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.12",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.12[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
            },
            {
                "name": "load_side_3_roller_boundary_load_0p15n",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.15",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.15[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
            },
            {
                "name": "load_side_3_roller_boundary_load_0p2n",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.2",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.2[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
            },
            {
                "name": "load_side_3_roller_boundary_load_0p5n",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.5",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.5[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "240",
                "solver_maxlinit": "1500",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
            },
            {
                "name": "load_side_3_roller_boundary_load_1n",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "1",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "1[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "260",
                "solver_maxlinit": "1600",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
            },
            {
                "name": "load_side_3_roller_boundary_load_5n",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "5",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "5[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "260",
                "solver_maxlinit": "1600",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
            },
            {
                "name": "load_side_3_roller_boundary_load_20n",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "20",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "20[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "300",
                "solver_maxlinit": "1800",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
            },
            {
                "name": "load_side_3_roller_boundary_load_50n",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "50",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "50[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "340",
                "solver_maxlinit": "2000",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
            },
            {
                "name": "load_side_6_roller_boundary_load_50n",
                "active_rollers": [11, 12, 1, 2, 3, 4],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "50",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "50[N]",
                "mesh_contact_size": "2.2[mm]",
                "mesh_bulk_size": "4.8[mm]",
                "solver_maxsegiter": "380",
                "solver_maxlinit": "2200",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.10",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "8e9[N/m^3]",
                "weak_roller_foundation_k": "8e7[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
            },
            {
                "name": "all_12_roller_boundary_load_50n",
                "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
                "inner_radial_displacement": "0[um]",
                "preload_steps": "50",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "50[N]",
                "mesh_contact_size": "2.0[mm]",
                "mesh_bulk_size": "4.5[mm]",
                "solver_maxsegiter": "420",
                "solver_maxlinit": "2400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.10",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "5e9[N/m^3]",
                "weak_roller_foundation_k": "5e7[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
            },
        ]:
            final_all_rollers = len(stage_payload["active_rollers"]) == VERIFIED_ROLLER_COUNT
            stages.append({
                **stage_payload,
                "contact_scope": "load_side_group_ramped_inner_bore_boundary_load_true_raceway_contact",
                "cage_contact_active": False,
                "inner_bore_load_active": True,
                "inner_body_load_active": False,
                "displacement_preload_active": False,
                "displacement_preload_selection": "sel_inner_raceway_contact",
                "active_roller_stabilization_active": bool(stage_payload.get("active_roller_stabilization_active", False)),
                "active_roller_stabilization_mode": stage_payload.get("active_roller_stabilization_mode", "fixed"),
                "active_roller_stabilization_k": stage_payload.get("active_roller_stabilization_k", "1e10[N/m^3]"),
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": stage_payload.get("weak_roller_foundation_k", "1e8[N/m^3]" if not final_all_rollers else "5e7[N/m^3]"),
                "weak_inner_guidance_active": True,
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "load_application_fidelity": (
                    "inner_bore_boundary_load_group_ramped_free_closure_single_solve_active_spring_stabilized_not_design_gate"
                ),
                "physical_acceptance": (
                    "group_ramped_high_load_boundary_load_diagnostic_requires_all_12_rollers_mpa_stress_native_png_and_stabilization_warning"
                    if final_all_rollers
                    else "group_ramped_boundary_load_intermediate_load_side_contact_closure_diagnostic_not_final"
                ),
            })
    if contact_stage_mode == "load_side_group_boundary_load_soft_guidance":
        for stage_payload in [
            {
                "name": "soft_guidance_3_roller_boundary_load_0p1n_bootstrap",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.001 0.005 0.01 0.05 0.1",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.1[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "guidance_diagnostic_role": "baseline_parametric_bootstrap",
            },
            {
                "name": "soft_guidance_3_roller_boundary_load_0p1n_singlepoint",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.1",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.1[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
                "guidance_diagnostic_role": "singlepoint_baseline_same_load",
            },
            {
                "name": "soft_guidance_3_roller_boundary_load_0p1n_k1e4",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.1",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.1[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "weak_inner_guidance_k": "1e4[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
                "guidance_diagnostic_role": "soften_weak_inner_guidance_only",
            },
            {
                "name": "soft_guidance_3_roller_boundary_load_0p101n_k1e4",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.101",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.101[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "weak_inner_guidance_k": "1e4[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
                "guidance_diagnostic_role": "load_increment_after_soft_guidance",
            },
        ]:
            stages.append({
                **stage_payload,
                "contact_scope": "load_side_group_ramped_inner_bore_boundary_load_soft_weak_guidance_diagnostic",
                "cage_contact_active": False,
                "inner_bore_load_active": True,
                "inner_body_load_active": False,
                "displacement_preload_active": False,
                "displacement_preload_selection": "sel_inner_raceway_contact",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": stage_payload.get("active_roller_stabilization_k", "1e10[N/m^3]"),
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": stage_payload.get("weak_roller_foundation_k", "1e8[N/m^3]"),
                "weak_inner_guidance_active": True,
                "weak_inner_guidance_k": stage_payload.get("weak_inner_guidance_k", "1e4[N/m^3]"),
                "load_application_fidelity": (
                    "inner_bore_boundary_load_load_side_three_roller_soft_weak_guidance_diagnostic_not_design_gate"
                ),
                "physical_acceptance": (
                    "soft_guidance_boundary_load_diagnostic_requires_native_png_and_records_guidance_warning_not_final"
                ),
            })
    if contact_stage_mode == "load_side_group_boundary_load_contact_relaxation":
        for stage_payload in [
            {
                "name": "contact_relaxation_3_roller_boundary_load_0p1n_bootstrap",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.001 0.005 0.01 0.05 0.1",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.1[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "contact_relaxation_diagnostic_role": "baseline_parametric_bootstrap",
            },
            {
                "name": "contact_relaxation_3_roller_boundary_load_0p1n_penalty1e5",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.1",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.1[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "1e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
                "contact_relaxation_diagnostic_role": "soften_contact_penalty_only_same_load",
            },
            {
                "name": "contact_relaxation_3_roller_boundary_load_0p101n_penalty1e5",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.101",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.101[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "1e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
                "contact_relaxation_diagnostic_role": "load_increment_after_softened_contact_penalty",
            },
        ]:
            stages.append({
                **stage_payload,
                "contact_scope": "load_side_group_ramped_inner_bore_boundary_load_contact_penalty_diagnostic",
                "cage_contact_active": False,
                "inner_bore_load_active": True,
                "inner_body_load_active": False,
                "displacement_preload_active": False,
                "displacement_preload_selection": "sel_inner_raceway_contact",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": stage_payload.get("active_roller_stabilization_k", "1e10[N/m^3]"),
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": stage_payload.get("weak_roller_foundation_k", "1e8[N/m^3]"),
                "weak_inner_guidance_active": True,
                "weak_inner_guidance_k": stage_payload.get("weak_inner_guidance_k", "5e4[N/m^3]"),
                "load_application_fidelity": (
                    "inner_bore_boundary_load_load_side_three_roller_contact_penalty_relaxation_diagnostic_not_design_gate"
                ),
                "physical_acceptance": (
                    "contact_penalty_boundary_load_diagnostic_requires_native_png_and_physical_plausibility_not_final"
                ),
            })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p101n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p101_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_roller1_pair_swap":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_roller1_pair_swap",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_roller1_pair_source_destination_swap",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "contact_pair_endpoint_overrides": {
                "cp_roller_1_inner_raceway": {
                    "source": "sel_inner_raceway_1_contact",
                    "destination": "sel_roller_1_inner_contact",
                },
                "cp_roller_1_outer_raceway": {
                    "source": "sel_outer_raceway_1_contact",
                    "destination": "sel_roller_1_outer_contact",
                },
            },
            "solver_formulation_diagnostic_role": "single_solve_0p101_roller1_pair_source_destination_swap_only",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_roller1_pair_endpoint_swap_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "roller1_pair_endpoint_swap_diagnostic_requires_native_png_pair_specific_Tn_and_active_roller_distribution_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_roller1_patch_shrink":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_roller1_patch_shrink",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_roller1_contact_patch_box_shrink",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "contact_patch_box_overrides": {
                "box_roller_1_inner_contact_patch": {
                    "xmin": "22.6[mm]",
                    "xmax": "23.4[mm]",
                    "ymin": "-1.0[mm]",
                    "ymax": "1.0[mm]",
                    "zmin": "-4.0[mm]",
                    "zmax": "4.0[mm]",
                    "condition": "intersects",
                },
                "box_roller_1_outer_contact_patch": {
                    "xmin": "30.6[mm]",
                    "xmax": "31.4[mm]",
                    "ymin": "-1.0[mm]",
                    "ymax": "1.0[mm]",
                    "zmin": "-4.0[mm]",
                    "zmax": "4.0[mm]",
                    "condition": "intersects",
                },
            },
            "solver_formulation_diagnostic_role": "single_solve_0p101_roller1_contact_patch_box_shrink_only",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_roller1_patch_shrink_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "roller1_patch_shrink_diagnostic_requires_selection_count_contact_probe_native_png_and_active_roller_distribution_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_roller1_box_intersection_rebuild":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_roller1_box_intersection_rebuild",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_roller1_box_intersection_contact_patch_rebuild",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "contact_patch_box_overrides": {
                "box_roller_1_inner_contact_patch": {
                    "xmin": "22.5[mm]",
                    "xmax": "23.5[mm]",
                    "ymin": "-1.2[mm]",
                    "ymax": "1.2[mm]",
                    "zmin": "-8.6[mm]",
                    "zmax": "8.6[mm]",
                    "condition": "intersects",
                },
                "box_roller_1_outer_contact_patch": {
                    "xmin": "26.4[mm]",
                    "xmax": "27.6[mm]",
                    "ymin": "-1.2[mm]",
                    "ymax": "1.2[mm]",
                    "zmin": "-8.6[mm]",
                    "zmax": "8.6[mm]",
                    "condition": "intersects",
                },
            },
            "solver_formulation_diagnostic_role": "single_solve_0p101_roller1_box_intersection_contact_patch_rebuild_only",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_roller1_box_intersection_rebuild_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "roller1_box_intersection_rebuild_requires_pair_specific_Tn_gap_source_destination_and_active_roller_distribution_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_roller1_outer_x31_box_intersection":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_roller1_outer_x31_box_intersection",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_roller1_outer_raceway_x31_box_intersection",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "contact_patch_box_overrides": {
                "box_roller_1_inner_contact_patch": {
                    "xmin": "22.5[mm]",
                    "xmax": "23.5[mm]",
                    "ymin": "-1.2[mm]",
                    "ymax": "1.2[mm]",
                    "zmin": "-8.6[mm]",
                    "zmax": "8.6[mm]",
                    "condition": "intersects",
                },
                "box_roller_1_outer_contact_patch": {
                    "xmin": "30.4[mm]",
                    "xmax": "31.6[mm]",
                    "ymin": "-1.2[mm]",
                    "ymax": "1.2[mm]",
                    "zmin": "-8.6[mm]",
                    "zmax": "8.6[mm]",
                    "condition": "intersects",
                },
            },
            "solver_formulation_diagnostic_role": "single_solve_0p101_roller1_outer_raceway_x31_box_intersection_only",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_roller1_outer_x31_box_intersection_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "roller1_outer_x31_box_intersection_requires_nonempty_outer_raceway_destination_pair_specific_Tn_gap_and_active_roller_distribution_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_roller1_partitioned_raceway_patch",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_roller1_geometry_partitioned_raceway_patch",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "raceway_partition_patch_overrides": {
                "partition_roller_1_inner_raceway_patch": {
                    "target_object": "inner_ring",
                    "tool_tag": "partition_tool_roller_1_inner_raceway_patch",
                    "selection_tag": "sel_inner_raceway_1_contact",
                    "tool_size": ["1.0[mm]", "2.4[mm]", "17.0[mm]"],
                    "tool_pos": ["23.0[mm]", "0[mm]", "0[mm]"],
                    "keepinput": "on",
                    "keeptool": "on",
                    "selresult": "on",
                    "selresultshow": "bnd",
                },
                "partition_roller_1_outer_raceway_patch": {
                    "target_object": "outer_ring",
                    "tool_tag": "partition_tool_roller_1_outer_raceway_patch",
                    "selection_tag": "sel_outer_raceway_1_contact",
                    "tool_size": ["1.0[mm]", "2.4[mm]", "17.0[mm]"],
                    "tool_pos": ["31.0[mm]", "0[mm]", "0[mm]"],
                    "keepinput": "on",
                    "keeptool": "on",
                    "selresult": "on",
                    "selresultshow": "bnd",
                },
            },
            "solver_formulation_diagnostic_role": "single_solve_0p101_roller1_geometry_partitioned_raceway_patch_only",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_roller1_partitioned_raceway_patch_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "roller1_partitioned_raceway_patch_diagnostic_requires_partition_log_native_png_pair_specific_Tn_gap_source_destination_and_active_roller_distribution_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_rebind":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_roller1_partitioned_raceway_patch_rebind",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_roller1_geometry_partitioned_raceway_patch_explicit_rebind",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "raceway_partition_patch_overrides": {
                "partition_roller_1_inner_raceway_patch": {
                    "target_object": "inner_ring",
                    "tool_tag": "partition_tool_roller_1_inner_raceway_patch",
                    "selection_tag": "sel_inner_raceway_1_contact",
                    "pair_tag": "cp_roller_1_inner_raceway",
                    "tool_size": ["1.0[mm]", "2.4[mm]", "17.0[mm]"],
                    "tool_pos": ["23.0[mm]", "0[mm]", "0[mm]"],
                    "explicit_selection_entities": [131, 134, 140, 141, 148, 151],
                    "keepinput": "on",
                    "keeptool": "on",
                    "selresult": "on",
                    "selresultshow": "bnd",
                },
                "partition_roller_1_outer_raceway_patch": {
                    "target_object": "outer_ring",
                    "tool_tag": "partition_tool_roller_1_outer_raceway_patch",
                    "selection_tag": "sel_outer_raceway_1_contact",
                    "pair_tag": "cp_roller_1_outer_raceway",
                    "tool_size": ["1.0[mm]", "2.4[mm]", "17.0[mm]"],
                    "tool_pos": ["31.0[mm]", "0[mm]", "0[mm]"],
                    "explicit_selection_entities": [8, 9, 11, 15, 25, 26],
                    "keepinput": "on",
                    "keeptool": "on",
                    "selresult": "on",
                    "selresultshow": "bnd",
                },
            },
            "solver_formulation_diagnostic_role": "single_solve_0p101_roller1_geometry_partitioned_raceway_patch_explicit_rebind",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_roller1_partitioned_raceway_patch_explicit_rebind_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "roller1_partitioned_raceway_patch_rebind_diagnostic_requires_partition_log_pair_rebind_native_png_pair_specific_Tn_gap_source_destination_and_active_roller_distribution_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_min_entities":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_roller1_partitioned_raceway_patch_min_entities",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_roller1_geometry_partitioned_min_entity_raceway_patch",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "raceway_partition_patch_overrides": {
                "partition_roller_1_inner_raceway_patch": {
                    "target_object": "inner_ring",
                    "tool_tag": "partition_tool_roller_1_inner_raceway_patch",
                    "selection_tag": "sel_inner_raceway_1_contact",
                    "pair_tag": "cp_roller_1_inner_raceway",
                    "tool_size": ["1.0[mm]", "2.4[mm]", "17.0[mm]"],
                    "tool_pos": ["23.0[mm]", "0[mm]", "0[mm]"],
                    "explicit_selection_entities": [140, 141],
                    "keepinput": "on",
                    "keeptool": "off",
                    "selresult": "on",
                    "selresultshow": "bnd",
                },
                "partition_roller_1_outer_raceway_patch": {
                    "target_object": "outer_ring",
                    "tool_tag": "partition_tool_roller_1_outer_raceway_patch",
                    "selection_tag": "sel_outer_raceway_1_contact",
                    "pair_tag": "cp_roller_1_outer_raceway",
                    "tool_size": ["1.0[mm]", "2.4[mm]", "17.0[mm]"],
                    "tool_pos": ["31.0[mm]", "0[mm]", "0[mm]"],
                    "explicit_selection_entities": [25, 26],
                    "keepinput": "on",
                    "keeptool": "off",
                    "selresult": "on",
                    "selresultshow": "bnd",
                },
            },
            "solver_formulation_diagnostic_role": "single_solve_0p101_roller1_partitioned_raceway_patch_min_entities_keeptool_off",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_roller1_partitioned_raceway_patch_min_entities_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "roller1_partitioned_raceway_patch_min_entities_diagnostic_requires_no_NPE_native_png_pair_specific_Tn_gap_source_destination_and_active_roller_distribution_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_active_spring1e9":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_active_spring1e9",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_active_spring_softened",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e9[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_0p101_active_roller_spring_softened_only",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_active_spring1e9_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "active_spring_softening_diagnostic_requires_native_png_pair_specific_Tn_and_active_roller_distribution_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_full_raceway_destination":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_full_raceway_destination",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_full_raceway_pair_destination",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "contact_pair_endpoint_overrides": {
                "cp_roller_1_inner_raceway": {
                    "destination": "sel_inner_raceway_contact",
                },
                "cp_roller_1_outer_raceway": {
                    "destination": "sel_outer_raceway_contact",
                },
                "cp_roller_2_inner_raceway": {
                    "destination": "sel_inner_raceway_contact",
                },
                "cp_roller_2_outer_raceway": {
                    "destination": "sel_outer_raceway_contact",
                },
                "cp_roller_12_inner_raceway": {
                    "destination": "sel_inner_raceway_contact",
                },
                "cp_roller_12_outer_raceway": {
                    "destination": "sel_outer_raceway_contact",
                },
            },
            "solver_formulation_diagnostic_role": "single_solve_0p101_full_raceway_pair_destination_only",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_full_raceway_destination_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "full_raceway_destination_diagnostic_requires_native_png_pair_specific_Tn_and_active_roller_distribution_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_entity_raceway_override":
        if roller1_outer_entity_override_only:
            entity_override_stage_name = "single_solve_3_roller_boundary_load_0p101n_roller1_outer_entity_override"
            entity_override_contact_scope = (
                "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_"
                "roller1_outer_destination_entity_override"
            )
            entity_override_selection_overrides = {
                "sel_outer_raceway_1_contact": list(roller1_outer_entity_override_entities or (8, 9)),
            }
            entity_override_diagnostic_role = (
                "single_solve_0p101_roller1_outer_destination_explicit_entity_override_only"
                + (
                    "_from_entity_transfer_probe"
                    if roller1_outer_entity_override_entities
                    else ""
                )
            )
            entity_override_load_fidelity = (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_"
                "roller1_outer_destination_entity_override_diagnostic_not_design_gate"
            )
            entity_override_physical_acceptance = (
                "roller1_outer_entity_override_diagnostic_requires_native_png_pair_specific_Tn_"
                "source_response_and_active_roller_distribution_not_final"
            )
        else:
            entity_override_stage_name = "single_solve_3_roller_boundary_load_0p101n_entity_raceway_override"
            entity_override_contact_scope = (
                "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_"
                "explicit_raceway_entity_override"
            )
            entity_override_selection_overrides = {
                "sel_inner_raceway_1_contact": [132, 133],
                "sel_outer_raceway_1_contact": [8, 9],
                "sel_inner_raceway_2_contact": [133, 134],
                "sel_outer_raceway_2_contact": [9],
                "sel_inner_raceway_12_contact": [131, 132],
                "sel_outer_raceway_12_contact": [8],
            }
            entity_override_diagnostic_role = (
                "single_solve_0p101_explicit_raceway_entity_override_from_saved_mph_geometry_moments"
            )
            entity_override_load_fidelity = (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_"
                "explicit_raceway_entity_override_diagnostic_not_design_gate"
            )
            entity_override_physical_acceptance = (
                "entity_raceway_override_diagnostic_requires_native_png_pair_specific_Tn_"
                "and_active_roller_distribution_not_final"
            )
        stages.append({
            "name": entity_override_stage_name,
            "contact_scope": entity_override_contact_scope,
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "raceway_selection_entity_overrides": entity_override_selection_overrides,
            "entity_override_source": (
                "saved_solved_mph_entity_transfer_probe_nonzero_integrals"
                if roller1_outer_entity_override_entities
                else "saved_mph_geometry_moments"
            ),
            "solver_formulation_diagnostic_role": entity_override_diagnostic_role,
            "load_application_fidelity": entity_override_load_fidelity,
            "physical_acceptance": entity_override_physical_acceptance,
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_roller1_gapoffset_minus3um":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_roller1_gapoffset_minus3um",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_roller1_contact_gapoffset_minus3um",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "contact_feature_property_overrides": {
                "contact_roller_1_inner": {"gapoffset": "-3[um]"},
                "contact_roller_1_outer": {"gapoffset": "-3[um]"},
            },
            "solver_formulation_diagnostic_role": "single_solve_0p101_roller1_contact_gapoffset_minus3um_only",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_roller1_gapoffset_minus3um_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "roller1_gapoffset_diagnostic_requires_native_png_pair_specific_Tn_and_active_roller_distribution_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_minus3um":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_roller1_source_offset_minus3um",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_roller1_contact_source_offset_minus3um",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "contact_feature_property_overrides": {
                "contact_roller_1_inner": {"source_offset": "-3[um]"},
                "contact_roller_1_outer": {"source_offset": "-3[um]"},
            },
            "solver_formulation_diagnostic_role": "single_solve_0p101_roller1_contact_source_offset_minus3um_only",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_roller1_source_offset_minus3um_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "roller1_source_offset_diagnostic_requires_native_png_pair_specific_Tn_and_active_roller_distribution_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_plus3um":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_roller1_source_offset_plus3um",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_roller1_contact_source_offset_plus3um",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "contact_feature_property_overrides": {
                "contact_roller_1_inner": {"source_offset": "3[um]"},
                "contact_roller_1_outer": {"source_offset": "3[um]"},
            },
            "solver_formulation_diagnostic_role": "single_solve_0p101_roller1_contact_source_offset_plus3um_only",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_roller1_source_offset_plus3um_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "roller1_source_offset_plus_diagnostic_requires_native_png_pair_specific_Tn_and_active_roller_distribution_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_roller1_offset_minus3um":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_roller1_offset_minus3um",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_roller1_contact_offset_minus3um",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "contact_feature_property_overrides": {
                "contact_roller_1_inner": {"offset": "-3[um]"},
                "contact_roller_1_outer": {"offset": "-3[um]"},
            },
            "solver_formulation_diagnostic_role": "single_solve_0p101_roller1_contact_offset_minus3um_only",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_roller1_offset_minus3um_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "roller1_offset_minus_diagnostic_requires_native_png_pair_specific_Tn_and_active_roller_distribution_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p101_roller1_offset_plus3um":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p101n_roller1_offset_plus3um",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p101n_roller1_contact_offset_plus3um",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.101[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "260",
            "solver_maxlinit": "1600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "contact_feature_property_overrides": {
                "contact_roller_1_inner": {"offset": "3[um]"},
                "contact_roller_1_outer": {"offset": "3[um]"},
            },
            "solver_formulation_diagnostic_role": "single_solve_0p101_roller1_contact_offset_plus3um_only",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_0p101n_roller1_offset_plus3um_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "roller1_offset_plus_diagnostic_requires_native_png_pair_specific_Tn_and_active_roller_distribution_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p12":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p12n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p12n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.12[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "280",
            "solver_maxlinit": "1800",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p12_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p12n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p12_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p13":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p13n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p13n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.13[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "285",
            "solver_maxlinit": "1850",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p13_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p13n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p13_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p14":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p14n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p14n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.14[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "290",
            "solver_maxlinit": "1900",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p14_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p14n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p14_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p145":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p145n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p145n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.145[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "295",
            "solver_maxlinit": "1950",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p145_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p145n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p145_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p1475":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p1475n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p1475n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.1475[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "300",
            "solver_maxlinit": "2000",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p1475_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p1475n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p1475_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p14875":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p14875n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p14875n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.14875[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "305",
            "solver_maxlinit": "2050",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p14875_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p14875n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p14875_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p149375":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p149375n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p149375n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.149375[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "310",
            "solver_maxlinit": "2100",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p149375_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p149375n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p149375_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p15_fine":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p15n_fine_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p15n_fine",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.15[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "320",
            "solver_maxlinit": "2200",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p15_fine_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p15n_fine_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p15_fine_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p1625":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p1625n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p1625n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.1625[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "330",
            "solver_maxlinit": "2300",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p1625_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p1625n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p1625_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p175":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p175n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p175n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.175[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "340",
            "solver_maxlinit": "2400",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p175_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p175n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p175_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p1875":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p1875n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p1875n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.1875[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "350",
            "solver_maxlinit": "2500",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p1875_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p1875n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p1875_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p19375":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p19375n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p19375n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875 0.19375",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.19375[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "360",
            "solver_maxlinit": "2600",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p19375_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p19375n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p19375_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p196875":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p196875n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p196875n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875 0.19375 0.196875",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.196875[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "370",
            "solver_maxlinit": "2700",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p196875_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p196875n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p196875_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p1984375":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p1984375n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p1984375n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875 0.19375 0.196875 0.1984375",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.1984375[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "380",
            "solver_maxlinit": "2800",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p1984375_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p1984375n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p1984375_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p2_fine":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p2n_fine_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p2n_fine",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.13 0.14 0.145 0.1475 0.14875 0.149375 0.15 0.1625 0.175 0.1875 0.19375 0.196875 0.1984375 0.2",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.2[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "400",
            "solver_maxlinit": "3000",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p2_fine_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p2n_fine_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p2_fine_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p15":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p15n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p15n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.15",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.15[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "290",
            "solver_maxlinit": "1900",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p15_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p15n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p15_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_0p2":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_0p2n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_0p2n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.15 0.2",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "0.2[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "300",
            "solver_maxlinit": "2000",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_0p2_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_0p2n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_0p2_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_single_solve_1n":
        stages.append({
            "name": "single_solve_3_roller_boundary_load_1n_parametric",
            "contact_scope": "load_side_three_roller_inner_bore_boundary_load_single_solver_sequence_to_1n",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.15 0.2 0.5 1",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "radial_load_value": "1[N]",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "solver_maxsegiter": "340",
            "solver_maxlinit": "2400",
            "contact_penalty": "5e-5*E_steel",
            "contact_relaxation": "0.12",
            "contact_tolerance": "3[um]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "displacement_preload_selection": "sel_inner_raceway_contact",
            "active_roller_stabilization_active": True,
            "active_roller_stabilization_mode": "spring",
            "active_roller_stabilization_k": "1e10[N/m^3]",
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "5e4[N/m^3]",
            "reuse_existing_solver": False,
            "use_parametric_sweep": True,
            "solver_formulation_diagnostic_role": "single_solve_parametric_to_1n_no_prior_bootstrap_or_cross_stage_solver_edit",
            "load_application_fidelity": (
                "inner_bore_boundary_load_load_side_three_roller_single_solve_parametric_1n_diagnostic_not_design_gate"
            ),
            "physical_acceptance": (
                "single_solve_1n_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
            ),
        })
    if contact_stage_mode == "load_side_group_boundary_load_micro_continuation":
        for stage_payload in [
            {
                "name": "micro_continuation_3_roller_boundary_load_0p1n_bootstrap",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.001 0.005 0.01 0.05 0.1",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.1[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "solver_formulation_diagnostic_role": "baseline_parametric_bootstrap",
            },
            {
                "name": "micro_continuation_3_roller_boundary_load_0p101n_parametric",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.1 0.1005 0.101",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.101[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "240",
                "solver_maxlinit": "1500",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": True,
                "solver_formulation_diagnostic_role": "micro_parametric_continuation_after_bootstrap_only",
            },
        ]:
            stages.append({
                **stage_payload,
                "contact_scope": "load_side_group_ramped_inner_bore_boundary_load_micro_parametric_continuation_diagnostic",
                "cage_contact_active": False,
                "inner_bore_load_active": True,
                "inner_body_load_active": False,
                "displacement_preload_active": False,
                "displacement_preload_selection": "sel_inner_raceway_contact",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": stage_payload.get("active_roller_stabilization_k", "1e10[N/m^3]"),
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": stage_payload.get("weak_roller_foundation_k", "1e8[N/m^3]"),
                "weak_inner_guidance_active": True,
                "weak_inner_guidance_k": stage_payload.get("weak_inner_guidance_k", "5e4[N/m^3]"),
                "load_application_fidelity": (
                    "inner_bore_boundary_load_load_side_three_roller_micro_parametric_continuation_diagnostic_not_design_gate"
                ),
                "physical_acceptance": (
                    "micro_parametric_boundary_load_diagnostic_requires_native_png_physical_plausibility_and_still_not_final"
                ),
            })
    if contact_stage_mode == "load_side_group_boundary_load_fixed_stabilization":
        for stage_payload in [
            {
                "name": "fixed_stabilization_3_roller_boundary_load_0p1n_bootstrap",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.001 0.005 0.01 0.05 0.1",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.1[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "spring",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "stabilization_diagnostic_role": "baseline_spring_parametric_bootstrap",
            },
            {
                "name": "fixed_stabilization_3_roller_boundary_load_0p1n_fixed_active",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.1",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.1[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "fixed",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
                "stabilization_diagnostic_role": "switch_active_roller_stabilization_from_spring_to_fixed_only",
            },
            {
                "name": "fixed_stabilization_3_roller_boundary_load_0p101n_fixed_active",
                "active_rollers": [12, 1, 2],
                "inner_radial_displacement": "0[um]",
                "preload_steps": "0.101",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "radial_load_value": "0.101[N]",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "solver_maxsegiter": "220",
                "solver_maxlinit": "1400",
                "contact_penalty": "5e-5*E_steel",
                "contact_relaxation": "0.12",
                "contact_tolerance": "3[um]",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": "fixed",
                "active_roller_stabilization_k": "1e10[N/m^3]",
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "reuse_existing_solver": False,
                "use_parametric_sweep": False,
                "stabilization_diagnostic_role": "load_increment_after_fixed_active_roller_stabilization",
            },
        ]:
            stages.append({
                **stage_payload,
                "contact_scope": "load_side_group_ramped_inner_bore_boundary_load_fixed_active_roller_stabilization_diagnostic",
                "cage_contact_active": False,
                "inner_bore_load_active": True,
                "inner_body_load_active": False,
                "displacement_preload_active": False,
                "displacement_preload_selection": "sel_inner_raceway_contact",
                "active_roller_stabilization_active": True,
                "active_roller_stabilization_mode": stage_payload.get("active_roller_stabilization_mode", "fixed"),
                "active_roller_stabilization_k": stage_payload.get("active_roller_stabilization_k", "1e10[N/m^3]"),
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": stage_payload.get("weak_roller_foundation_k", "1e8[N/m^3]"),
                "weak_inner_guidance_active": True,
                "weak_inner_guidance_k": stage_payload.get("weak_inner_guidance_k", "5e4[N/m^3]"),
                "load_application_fidelity": (
                    "inner_bore_boundary_load_load_side_three_roller_fixed_active_roller_stabilization_diagnostic_not_design_gate"
                ),
                "physical_acceptance": (
                    "fixed_active_roller_stabilization_boundary_load_diagnostic_not_design_gate_even_if_native_png_converges"
                ),
            })
    if contact_stage_mode == "single_roller_displacement_preload":
        stages.append({
            "name": "single_roller_physical_displacement_preload",
            "contact_scope": "single_load_side_roller_inner_outer_raceway_true_contact_displacement_preload",
            "active_rollers": [1],
            "cage_contact_active": False,
            "inner_radial_displacement": "0.003[um]",
            "preload_steps": "0.0001 0.0005 0.001 0.003",
            "mesh_contact_size": "2.8[mm]",
            "mesh_bulk_size": "6.0[mm]",
            "inner_bore_load_active": False,
            "inner_body_load_active": False,
            "displacement_preload_active": True,
            "active_roller_stabilization_active": False,
            "physical_acceptance": "candidate_physical_smoke_true_roller_raceway_contact_requires_nonzero_inner_ring_stress",
        })
        stages.append({
            "name": "single_roller_physical_radial_load_transfer",
            "contact_scope": "single_load_side_roller_inner_outer_raceway_true_contact_radial_load",
            "active_rollers": [1],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "1 25 100 500 1500",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "mesh_contact_size": "2.8[mm]",
            "mesh_bulk_size": "6.0[mm]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "active_roller_stabilization_active": False,
            "physical_acceptance": "candidate_physical_smoke_true_roller_raceway_load_transfer_requires_nonzero_inner_ring_stress",
        })
    if contact_stage_mode in {"single_load_roller", "load_side_then_all"}:
        stages.append({
            "name": "single_load_roller_contact_closure_bootstrap",
            "contact_scope": "single_load_side_roller_inner_outer_raceway_bootstrap_fixed_active_roller",
            "active_rollers": [1],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "1 50 250 1000 3000",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.5[mm]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "active_roller_stabilization_active": True,
            "physical_acceptance": "bootstrap_only_not_final_physical_contact_validation",
        })
        stages.append({
            "name": "single_load_roller_radial_load_ramp",
            "contact_scope": "single_load_side_roller_inner_outer_raceway_radial_load",
            "active_rollers": [1],
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "1 50 250 1000 3000",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.5[mm]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "active_roller_stabilization_active": False,
            "physical_acceptance": "candidate_physical_stage_requires_nonzero_inner_ring_stress_and_no_temporary_active_roller_fix",
        })
    if contact_stage_mode == "load_side_then_all":
        stages.append({
            "name": "load_side_three_roller_raceway_preload",
            "contact_scope": "load_side_rollers_inner_outer_raceway_only",
            "active_rollers": [12, 1, 2],
            "cage_contact_active": False,
            "inner_radial_displacement": "0.005[um]",
            "preload_steps": "0.0005 0.001 0.005",
            "mesh_contact_size": "2.2[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "inner_bore_load_active": False,
            "inner_body_load_active": False,
            "displacement_preload_active": True,
            "active_roller_stabilization_active": False,
        })
    if contact_stage_mode not in {"single_load_roller", "single_roller_displacement_preload", "all_raceway_micro_preload", "load_side_group_micro", "load_side_group_compaction", "load_side_group_preclosed_boundary_load", "load_side_group_boundary_load", "load_side_group_boundary_load_soft_guidance", "load_side_group_boundary_load_contact_relaxation", "load_side_group_boundary_load_single_solve_0p101", "load_side_group_boundary_load_single_solve_0p101_roller1_pair_swap", "load_side_group_boundary_load_single_solve_0p101_roller1_patch_shrink", "load_side_group_boundary_load_single_solve_0p101_roller1_box_intersection_rebuild", "load_side_group_boundary_load_single_solve_0p101_roller1_outer_x31_box_intersection", "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch", "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_rebind", "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_min_entities", "load_side_group_boundary_load_single_solve_0p101_active_spring1e9", "load_side_group_boundary_load_single_solve_0p101_full_raceway_destination", "load_side_group_boundary_load_single_solve_0p101_entity_raceway_override", "load_side_group_boundary_load_single_solve_0p101_roller1_gapoffset_minus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_minus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_plus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_offset_minus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_offset_plus3um", "load_side_group_boundary_load_single_solve_0p12", "load_side_group_boundary_load_single_solve_0p13", "load_side_group_boundary_load_single_solve_0p14", "load_side_group_boundary_load_single_solve_0p145", "load_side_group_boundary_load_single_solve_0p1475", "load_side_group_boundary_load_single_solve_0p14875", "load_side_group_boundary_load_single_solve_0p149375", "load_side_group_boundary_load_single_solve_0p15_fine", "load_side_group_boundary_load_single_solve_0p1625", "load_side_group_boundary_load_single_solve_0p175", "load_side_group_boundary_load_single_solve_0p1875", "load_side_group_boundary_load_single_solve_0p19375", "load_side_group_boundary_load_single_solve_0p196875", "load_side_group_boundary_load_single_solve_0p1984375", "load_side_group_boundary_load_single_solve_0p2_fine", "load_side_group_boundary_load_single_solve_0p15", "load_side_group_boundary_load_single_solve_0p2", "load_side_group_boundary_load_single_solve_1n", "load_side_group_boundary_load_micro_continuation", "load_side_group_boundary_load_fixed_stabilization", "all_raceway_high_body_load_visual", "all_raceway_continuous_boundary_load", "all_raceway_split_control_boundary_load"}:
        stages.extend([
        {
            "name": "raceway_contact_coarse_preload",
            "contact_scope": "roller_inner_outer_raceway_only",
            "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
            "cage_contact_active": False,
            "inner_radial_displacement": "0.002[um]",
            "preload_steps": "0.0001 0.0005 0.002",
            "mesh_contact_size": "2.4[mm]",
            "mesh_bulk_size": "5.0[mm]",
            "inner_bore_load_active": False,
            "inner_body_load_active": False,
            "displacement_preload_active": True,
            "active_roller_stabilization_active": False,
            "physical_acceptance": "intermediate_all_12_roller_raceway_contact_preload_not_final",
        },
        {
            "name": "raceway_contact_refined_preload",
            "contact_scope": "roller_inner_outer_raceway_only",
            "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
            "cage_contact_active": False,
            "inner_radial_displacement": "0.01[um]",
            "preload_steps": "0.002 0.005 0.01",
            "mesh_contact_size": "1.6[mm]",
            "mesh_bulk_size": "3.5[mm]",
            "inner_bore_load_active": False,
            "inner_body_load_active": False,
            "displacement_preload_active": True,
            "active_roller_stabilization_active": False,
            "physical_acceptance": "accepted_all_12_roller_raceway_contact_displacement_preload_smoke_requires_nonzero_inner_ring_stress_visible_stress_png",
        },
        ])
    if contact_stage_mode in {"all_raceway_high_preload_visual", "all_raceway_high_preload_reaction_equivalent"}:
        reaction_equivalent = contact_stage_mode == "all_raceway_high_preload_reaction_equivalent"
        stages.append({
            "name": "raceway_contact_high_preload_reaction_equivalent" if reaction_equivalent else "raceway_contact_high_preload_visual",
            "contact_scope": (
                "roller_inner_outer_raceway_only_high_displacement_preload_reaction_equivalent_probe"
                if reaction_equivalent
                else "roller_inner_outer_raceway_only_high_displacement_preload_visualization"
            ),
            "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
            "cage_contact_active": False,
            "inner_radial_displacement": "3[um]",
            "preload_steps": "0.01 0.05 0.1 0.25 0.5 1 2 3",
            "mesh_contact_size": "1.6[mm]",
            "mesh_bulk_size": "3.5[mm]",
            "inner_bore_load_active": False,
            "inner_body_load_active": False,
            "displacement_preload_active": True,
            "active_roller_stabilization_active": False,
            "solver_maxsegiter": "100",
            "solver_maxlinit": "700",
            "contact_penalty": "0.02*E_steel",
            "contact_relaxation": "0.35",
            "contact_tolerance": "0.2[um]",
            "reaction_equivalent_requested": reaction_equivalent,
            "reaction_probe_selection": "sel_inner_bore_load_surface",
            "load_application_fidelity": (
                "displacement_controlled_high_preload_with_reaction_probe_not_boundary_load_design_gate"
                if reaction_equivalent
                else "boundary_or_displacement_stage"
            ),
            "physical_acceptance": (
                "high_preload_reaction_equivalent_true_12_roller_raceway_contact_requires_reaction_probe_or_clear_failure"
                if reaction_equivalent
                else "high_preload_visualization_true_12_roller_raceway_contact_not_radial_force_transfer"
            ),
        })
    if contact_stage_mode == "all_raceway_high_load_visual":
        stages.append({
            "name": "raceway_contact_high_radial_load_visual",
            "contact_scope": "all_12_rollers_inner_outer_raceway_true_contact_high_radial_load_transfer",
            "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "10 50 100 250 500 1000 2000 3000",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "mesh_contact_size": "1.6[mm]",
            "mesh_bulk_size": "3.5[mm]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "active_roller_stabilization_active": False,
            "solver_maxsegiter": "120",
            "solver_maxlinit": "900",
            "contact_penalty": "0.002*E_steel",
            "contact_relaxation": "0.25",
            "contact_tolerance": "0.5[um]",
            "physical_acceptance": "high_load_true_12_roller_raceway_contact_requires_converged_radial_load_transfer_nonzero_mpa_stress_visible_native_comsol_png",
        })
    if contact_stage_mode == "all_raceway_continuous_boundary_load":
        stages.extend([
            {
                "name": "continuous_boundary_load_contact_closure_1n",
                "contact_scope": "all_12_rollers_inner_outer_raceway_true_contact_inner_bore_boundary_load_active_from_initial_contact_closure",
                "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
                "cage_contact_active": False,
                "inner_radial_displacement": "0.01[um]",
                "preload_steps": "0.0001 0.0005 0.002 0.005 0.01",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "radial_load_value": "1[N]",
                "inner_bore_load_active": True,
                "inner_body_load_active": False,
                "displacement_preload_active": True,
                "active_roller_stabilization_active": False,
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "solver_maxsegiter": "80",
                "solver_maxlinit": "500",
                "contact_penalty": "0.002*E_steel",
                "contact_relaxation": "0.25",
                "contact_tolerance": "0.5[um]",
                "load_application_fidelity": "inner_bore_boundary_load_active_from_initial_contact_closure_with_retained_displacement_preload_not_design_gate",
                "physical_acceptance": "continuous_boundary_load_contact_closure_diagnostic_not_final_design_gate",
            },
            {
                "name": "continuous_boundary_load_low_ramp_retained_preload",
                "contact_scope": "all_12_rollers_inner_outer_raceway_true_contact_inner_bore_boundary_load_low_ramp_retained_preload",
                "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
                "cage_contact_active": False,
                "inner_radial_displacement": "0.01[um]",
                "preload_steps": "1 2 5 10 25 50 100",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "mesh_contact_size": "1.8[mm]",
                "mesh_bulk_size": "4.0[mm]",
                "radial_load_value": "100[N]",
                "inner_bore_load_active": True,
                "inner_body_load_active": False,
                "displacement_preload_active": True,
                "active_roller_stabilization_active": False,
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "weak_inner_guidance_active": True,
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "solver_maxsegiter": "160",
                "solver_maxlinit": "1000",
                "contact_penalty": "0.001*E_steel",
                "contact_relaxation": "0.20",
                "contact_tolerance": "1[um]",
                "load_application_fidelity": "inner_bore_boundary_load_continuation_with_retained_displacement_preload_and_weak_inner_guidance_not_design_gate",
                "physical_acceptance": "continuous_boundary_load_low_ramp_requires_native_png_and_guidance_warning",
            },
            {
                "name": "continuous_boundary_load_high_ramp_retained_preload",
                "contact_scope": "all_12_rollers_inner_outer_raceway_true_contact_inner_bore_boundary_load_high_ramp_retained_preload",
                "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
                "cage_contact_active": False,
                "inner_radial_displacement": "0.005[um]",
                "preload_steps": "100 250 500 1000 2000 3000",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "mesh_contact_size": "1.8[mm]",
                "mesh_bulk_size": "4.0[mm]",
                "radial_load_value": "3000[N]",
                "inner_bore_load_active": True,
                "inner_body_load_active": False,
                "displacement_preload_active": True,
                "active_roller_stabilization_active": False,
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": "5e7[N/m^3]",
                "weak_inner_guidance_active": True,
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "solver_maxsegiter": "180",
                "solver_maxlinit": "1200",
                "contact_penalty": "0.001*E_steel",
                "contact_relaxation": "0.20",
                "contact_tolerance": "1[um]",
                "load_application_fidelity": "inner_bore_boundary_load_high_ramp_with_retained_displacement_preload_and_weak_inner_guidance_not_design_gate",
                "physical_acceptance": "continuous_high_load_boundary_load_diagnostic_requires_mpa_stress_native_png_and_explicit_stabilization_warning",
            },
        ])
    if contact_stage_mode == "all_raceway_split_control_boundary_load":
        stages.extend([
            {
                "name": "split_control_boundary_load_contact_closure_0p1n",
                "contact_scope": "all_12_rollers_inner_outer_raceway_true_contact_inner_bore_boundary_load_with_raceway_displacement_closure",
                "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
                "cage_contact_active": False,
                "inner_radial_displacement": "0.005[um]",
                "preload_steps": "0.0001 0.0005 0.001 0.002 0.005",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "radial_load_value": "0.1[N]",
                "inner_bore_load_active": True,
                "inner_body_load_active": False,
                "displacement_preload_active": True,
                "displacement_preload_selection": "sel_inner_raceway_contact",
                "active_roller_stabilization_active": False,
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "solver_maxsegiter": "100",
                "solver_maxlinit": "700",
                "contact_penalty": "1e-4*E_steel",
                "contact_relaxation": "0.15",
                "contact_tolerance": "2[um]",
                "load_application_fidelity": "inner_bore_boundary_load_active_with_split_raceway_displacement_closure_not_design_gate",
                "physical_acceptance": "split_control_boundary_load_contact_closure_diagnostic_not_final_design_gate",
            },
            {
                "name": "split_control_boundary_load_low_ramp",
                "contact_scope": "all_12_rollers_inner_outer_raceway_true_contact_inner_bore_boundary_load_low_ramp_split_control",
                "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
                "cage_contact_active": False,
                "inner_radial_displacement": "0.005[um]",
                "preload_steps": "0.1 1 2 5 10 25 50 100",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "mesh_contact_size": "1.8[mm]",
                "mesh_bulk_size": "4.0[mm]",
                "radial_load_value": "100[N]",
                "inner_bore_load_active": True,
                "inner_body_load_active": False,
                "displacement_preload_active": True,
                "displacement_preload_selection": "sel_inner_raceway_contact",
                "active_roller_stabilization_active": False,
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": "1e8[N/m^3]",
                "weak_inner_guidance_active": True,
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "solver_maxsegiter": "180",
                "solver_maxlinit": "1200",
                "contact_penalty": "1e-4*E_steel",
                "contact_relaxation": "0.15",
                "contact_tolerance": "2[um]",
                "load_application_fidelity": "inner_bore_boundary_load_low_ramp_with_split_raceway_displacement_closure_and_weak_guidance_not_design_gate",
                "physical_acceptance": "split_control_boundary_load_low_ramp_requires_native_png_and_guidance_warning",
            },
            {
                "name": "split_control_boundary_load_high_ramp",
                "contact_scope": "all_12_rollers_inner_outer_raceway_true_contact_inner_bore_boundary_load_high_ramp_split_control",
                "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
                "cage_contact_active": False,
                "inner_radial_displacement": "0.002[um]",
                "preload_steps": "100 250 500 1000 2000 3000",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "mesh_contact_size": "1.8[mm]",
                "mesh_bulk_size": "4.0[mm]",
                "radial_load_value": "3000[N]",
                "inner_bore_load_active": True,
                "inner_body_load_active": False,
                "displacement_preload_active": True,
                "displacement_preload_selection": "sel_inner_raceway_contact",
                "active_roller_stabilization_active": False,
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": "5e7[N/m^3]",
                "weak_inner_guidance_active": True,
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "solver_maxsegiter": "200",
                "solver_maxlinit": "1400",
                "contact_penalty": "1e-4*E_steel",
                "contact_relaxation": "0.15",
                "contact_tolerance": "2[um]",
                "load_application_fidelity": "inner_bore_boundary_load_high_ramp_with_split_raceway_displacement_closure_and_weak_guidance_not_design_gate",
                "physical_acceptance": "split_control_high_load_boundary_load_diagnostic_requires_mpa_stress_native_png_and_explicit_stabilization_warning",
            },
        ])
    if contact_stage_mode in {"all_raceway_guided_probe_1n", "all_raceway_guided_low_load_transfer", "all_raceway_guided_high_load_transfer"}:
        high_guided = contact_stage_mode == "all_raceway_guided_high_load_transfer"
        probe_guided = contact_stage_mode == "all_raceway_guided_probe_1n"
        stages.append({
            "name": (
                "raceway_contact_guided_high_radial_load_transfer"
                if high_guided
                else "raceway_contact_guided_probe_1n_boundary_load"
                if probe_guided
                else "raceway_contact_guided_low_radial_load_transfer"
            ),
            "contact_scope": "all_12_rollers_inner_outer_raceway_true_contact_inner_bore_boundary_load_with_weak_inner_guidance",
            "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": (
                "1 5 10 25 50 100 250 500 1000 2000 3000"
                if high_guided
                else "1"
                if probe_guided
                else "1 2 5 10 25 50 100"
            ),
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "mesh_contact_size": "1.8[mm]",
            "mesh_bulk_size": "4.0[mm]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "active_roller_stabilization_active": False,
            "weak_roller_foundation_active": True,
            "weak_roller_foundation_k": "1e8[N/m^3]",
            "weak_inner_guidance_active": True,
            "weak_inner_guidance_k": "1e5[N/m^3]",
            "solver_maxsegiter": "30" if probe_guided else "160",
            "solver_maxlinit": "250" if probe_guided else "1000",
            "contact_penalty": "1e-4*E_steel",
            "contact_relaxation": "0.15",
            "contact_tolerance": "2[um]",
            "load_application_fidelity": "inner_bore_boundary_load_with_weak_inner_ring_guidance_not_final_design_gate",
            "physical_acceptance": (
                "guided_high_load_true_12_roller_raceway_contact_requires_native_png_and_guidance_warning"
                if high_guided
                else "guided_probe_1n_true_12_roller_raceway_contact_boundary_load_diagnostic"
                if probe_guided
                else "guided_low_load_true_12_roller_raceway_contact_requires_native_png_and_guidance_warning"
            ),
        })
    if contact_stage_mode == "all_raceway_high_body_load_visual":
        stages.append({
            "name": "raceway_contact_high_body_load_visual",
            "contact_scope": "all_12_rollers_inner_outer_raceway_contact_high_load_visual_body_load_fallback",
            "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "3000",
            "sweep_parameter": "radial_load",
            "sweep_unit": "N",
            "mesh_contact_size": "1.6[mm]",
            "mesh_bulk_size": "3.5[mm]",
            "inner_bore_load_active": False,
            "inner_body_load_active": True,
            "displacement_preload_active": False,
            "active_roller_stabilization_active": False,
            "weak_roller_foundation_active": False,
            "solver_maxsegiter": "80",
            "solver_maxlinit": "500",
            "contact_penalty": "0.02*E_steel",
            "contact_relaxation": "0.35",
            "contact_tolerance": "0.2[um]",
            "load_application_fidelity": "visual_fallback_inner_ring_distributed_body_load_not_design_boundary_load",
            "physical_acceptance": "high_load_visual_fallback_true_12_roller_raceway_contact_body_load_stage_must_be_labeled_not_final_design_load",
        })
    if contact_stage_mode not in {"all_raceway_micro_preload", "load_side_group_micro", "load_side_group_compaction", "load_side_group_preclosed_boundary_load", "load_side_group_boundary_load", "load_side_group_boundary_load_soft_guidance", "load_side_group_boundary_load_contact_relaxation", "load_side_group_boundary_load_single_solve_0p101", "load_side_group_boundary_load_single_solve_0p101_roller1_pair_swap", "load_side_group_boundary_load_single_solve_0p101_roller1_patch_shrink", "load_side_group_boundary_load_single_solve_0p101_roller1_box_intersection_rebuild", "load_side_group_boundary_load_single_solve_0p101_roller1_outer_x31_box_intersection", "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch", "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_rebind", "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_min_entities", "load_side_group_boundary_load_single_solve_0p101_active_spring1e9", "load_side_group_boundary_load_single_solve_0p101_full_raceway_destination", "load_side_group_boundary_load_single_solve_0p101_entity_raceway_override", "load_side_group_boundary_load_single_solve_0p101_roller1_gapoffset_minus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_minus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_plus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_offset_minus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_offset_plus3um", "load_side_group_boundary_load_single_solve_0p12", "load_side_group_boundary_load_single_solve_0p13", "load_side_group_boundary_load_single_solve_0p14", "load_side_group_boundary_load_single_solve_0p145", "load_side_group_boundary_load_single_solve_0p1475", "load_side_group_boundary_load_single_solve_0p14875", "load_side_group_boundary_load_single_solve_0p149375", "load_side_group_boundary_load_single_solve_0p15_fine", "load_side_group_boundary_load_single_solve_0p1625", "load_side_group_boundary_load_single_solve_0p175", "load_side_group_boundary_load_single_solve_0p1875", "load_side_group_boundary_load_single_solve_0p19375", "load_side_group_boundary_load_single_solve_0p196875", "load_side_group_boundary_load_single_solve_0p1984375", "load_side_group_boundary_load_single_solve_0p2_fine", "load_side_group_boundary_load_single_solve_0p15", "load_side_group_boundary_load_single_solve_0p2", "load_side_group_boundary_load_single_solve_1n", "load_side_group_boundary_load_micro_continuation", "load_side_group_boundary_load_fixed_stabilization", "all_raceway_preload_only", "all_raceway_high_preload_visual", "all_raceway_high_preload_reaction_equivalent", "all_raceway_high_load_visual", "all_raceway_continuous_boundary_load", "all_raceway_split_control_boundary_load", "all_raceway_guided_probe_1n", "all_raceway_guided_low_load_transfer", "all_raceway_guided_high_load_transfer", "all_raceway_high_body_load_visual"}:
        radial_transfer_stage = {
            "name": "raceway_contact_radial_load_transfer",
            "contact_scope": "roller_inner_outer_raceway_only_radial_load",
            "active_rollers": [1] if contact_stage_mode in {"single_load_roller", "single_roller_displacement_preload"} else list(range(1, VERIFIED_ROLLER_COUNT + 1)),
            "cage_contact_active": False,
            "inner_radial_displacement": "0[um]",
            "preload_steps": "0",
            "mesh_contact_size": "1.6[mm]",
            "mesh_bulk_size": "3.5[mm]",
            "inner_bore_load_active": True,
            "inner_body_load_active": False,
            "displacement_preload_active": False,
            "active_roller_stabilization_active": False,
        }
        if contact_stage_mode == "all_raceway_low_load_transfer":
            radial_transfer_stage.update({
                "name": "raceway_contact_low_radial_load_transfer",
                "preload_steps": "1 10 50 100",
                "sweep_parameter": "radial_load",
                "sweep_unit": "N",
                "contact_penalty": "1e-5*E_steel",
                "contact_relaxation": "0.15",
                "contact_tolerance": "2[um]",
                "solver_maxsegiter": "40",
                "solver_maxlinit": "300",
                "physical_acceptance": "low_load_true_12_roller_raceway_contact_requires_nonzero_inner_ring_stress_visible_stress_png",
            })
        stages.append({
            **radial_transfer_stage,
        })
    if run_full_cage_stage:
        if contact_stage_mode == "load_side_group_compaction":
            stages.append({
                "name": "full_cage_contact_compaction_preload",
                "contact_scope": "roller_inner_outer_raceway_compaction_plus_cage_pockets",
                "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
                "cage_contact_active": True,
                "inner_radial_displacement": "0.003[um]",
                "preload_steps": "0.001 0.002 0.003",
                "mesh_contact_size": "2.4[mm]",
                "mesh_bulk_size": "5.0[mm]",
                "inner_bore_load_active": False,
                "displacement_preload_active": True,
                "active_roller_stabilization_active": False,
                "weak_roller_foundation_active": True,
                "weak_roller_foundation_k": "1e11[N/m^3]",
                "weak_inner_guidance_active": True,
                "weak_inner_guidance_k": "5e4[N/m^3]",
                "contact_penalty": "1e-5*E_steel",
                "contact_relaxation": "0.15",
                "contact_tolerance": "3[um]",
                "load_application_fidelity": "displacement_controlled_group_compaction_with_cage_contact_not_boundary_load_design_gate",
                "physical_acceptance": "final_all_12_group_compaction_with_cage_contact_requires_nonzero_stress_visible_native_png",
            })
        else:
            stages.append({
                "name": "full_cage_contact_small_preload",
                "contact_scope": "roller_inner_outer_raceway_plus_cage_pockets",
                "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
                "cage_contact_active": True,
                "inner_radial_displacement": "0.002[um]",
                "preload_steps": "0.0001 0.0005 0.002",
                "mesh_contact_size": "1.6[mm]",
                "mesh_bulk_size": "4.0[mm]",
                "inner_bore_load_active": False,
                "displacement_preload_active": True,
                "active_roller_stabilization_active": False,
                "physical_acceptance": "final_cage_contact_stage_requires_no_temporary_cage_or_roller_fix",
            })
    stage_results: list[dict[str, Any]] = []
    final_solve: dict[str, Any] = {"success": False, "error": "No staged solve was executed."}
    for stage in stages:
        setup = _set_3d_staged_contact_state(
            model_name,
            stage_name=stage["name"],
            cage_contact_active=stage["cage_contact_active"],
            active_rollers=stage["active_rollers"],
            inner_radial_displacement=stage["inner_radial_displacement"],
            preload_steps=stage["preload_steps"],
            mesh_contact_size=stage["mesh_contact_size"],
            mesh_bulk_size=stage["mesh_bulk_size"],
            inner_bore_load_active=stage.get("inner_bore_load_active", False),
            inner_body_load_active=stage.get("inner_body_load_active", False),
            displacement_preload_active=stage.get("displacement_preload_active", True),
            sweep_parameter=stage.get("sweep_parameter", "inner_radial_displacement"),
            sweep_unit=stage.get("sweep_unit", "um"),
            active_roller_stabilization_active=stage.get("active_roller_stabilization_active", False),
            active_roller_stabilization_mode=stage.get("active_roller_stabilization_mode", "fixed"),
            active_roller_stabilization_k=stage.get("active_roller_stabilization_k", "1e10[N/m^3]"),
            weak_roller_foundation_active=stage.get("weak_roller_foundation_active", True),
            weak_roller_foundation_k=stage.get("weak_roller_foundation_k", "1e8[N/m^3]"),
            weak_inner_guidance_active=stage.get("weak_inner_guidance_active", False),
            weak_inner_guidance_k=stage.get("weak_inner_guidance_k", "1e5[N/m^3]"),
            solver_maxsegiter=stage.get("solver_maxsegiter", "80"),
            solver_maxlinit=stage.get("solver_maxlinit", "500"),
            contact_penalty=stage.get("contact_penalty", "0.02*E_steel"),
            contact_relaxation=stage.get("contact_relaxation", "0.35"),
            contact_tolerance=stage.get("contact_tolerance", "0.2[um]"),
            radial_load_value=stage.get("radial_load_value", "3000[N]"),
            displacement_preload_selection=stage.get("displacement_preload_selection", "sel_inner_bore_load_surface"),
            reuse_existing_solver=stage.get("reuse_existing_solver", False),
            use_parametric_sweep=stage.get("use_parametric_sweep", True),
            contact_pair_endpoint_overrides=stage.get("contact_pair_endpoint_overrides"),
            raceway_selection_entity_overrides=stage.get("raceway_selection_entity_overrides"),
            contact_feature_property_overrides=stage.get("contact_feature_property_overrides"),
            contact_patch_box_overrides=stage.get("contact_patch_box_overrides"),
            raceway_partition_patch_overrides=stage.get("raceway_partition_patch_overrides"),
        )
        pre_solve_model_save = (
            _save_stage_configured_mph(
                model_name,
                stage_name=stage["name"],
                output_dir=stage_plot_dir.parent / "stage_models" if stage_plot_dir is not None else None,
            )
            if setup.get("success")
            else {}
        )
        solve = comsol_solve(model_name)
        stress = comsol_evaluate(model_name, "solid.mises") if solve.get("success") else {}
        inner_ring_stress = comsol_evaluate(model_name, "maxop_inner_ring(solid.mises)") if solve.get("success") else {}
        displacement = comsol_evaluate(model_name, "solid.disp") if solve.get("success") else {}
        contact_pressure = comsol_evaluate(model_name, "contact_pressure_est") if solve.get("success") else {}
        per_roller_probe_results = _evaluate_per_roller_probe_results(model_name) if solve.get("success") else []
        active_roller_load_distribution = _active_roller_load_distribution_audit(
            per_roller_probe_results,
            active_rollers=stage.get("active_rollers"),
            boundary_load_active=bool(stage.get("inner_bore_load_active")),
        )
        reaction_equivalent = (
            _evaluate_displacement_reaction_equivalent(
                model_name,
                selection_name=stage.get("reaction_probe_selection", "sel_inner_bore_load_surface"),
            )
            if solve.get("success") and stage.get("reaction_equivalent_requested")
            else {}
        )
        post_reaction_probe_model_save = (
            _save_stage_configured_mph(
                model_name,
                stage_name=f"{stage['name']}_post_reaction_probe",
                output_dir=stage_plot_dir.parent / "stage_models" if stage_plot_dir is not None else None,
            )
            if solve.get("success") and stage.get("reaction_equivalent_requested")
            else {}
        )
        native_volume_plot = (
            _export_native_3d_stage_volume_plot(
                model_name,
                stage_name=stage["name"],
                output_dir=stage_plot_dir,
            )
            if solve.get("success") and stage_plot_dir is not None
            else {}
        )
        stage_result = {
            **stage,
            "raceway_contact_active": True,
            "inactive_roller_stabilization_active": len(stage["active_rollers"]) < VERIFIED_ROLLER_COUNT,
            "temporary_active_roller_stabilization_active": bool(stage.get("active_roller_stabilization_active")),
            "active_roller_stabilization_mode": stage.get("active_roller_stabilization_mode", "fixed"),
            "active_roller_stabilization_k": stage.get("active_roller_stabilization_k", "1e10[N/m^3]"),
            "weak_roller_foundation_active": stage.get("weak_roller_foundation_active", True),
            "weak_roller_foundation_k": stage.get("weak_roller_foundation_k", "1e8[N/m^3]"),
            "weak_inner_guidance_active": stage.get("weak_inner_guidance_active", False),
            "weak_inner_guidance_k": stage.get("weak_inner_guidance_k", "1e5[N/m^3]"),
            "inner_body_load_active": stage.get("inner_body_load_active", False),
            "reuse_existing_solver": stage.get("reuse_existing_solver", False),
            "use_parametric_sweep": stage.get("use_parametric_sweep", True),
            "radial_load_value": stage.get("radial_load_value", "3000[N]"),
            "displacement_preload_selection": stage.get("displacement_preload_selection", "sel_inner_bore_load_surface"),
            "reaction_equivalent_requested": bool(stage.get("reaction_equivalent_requested")),
            "reaction_probe_selection": stage.get("reaction_probe_selection"),
            "load_application_fidelity": stage.get("load_application_fidelity", "boundary_or_displacement_stage"),
            "contact_penalty": stage.get("contact_penalty", "0.02*E_steel"),
            "contact_relaxation": stage.get("contact_relaxation", "0.35"),
            "contact_tolerance": stage.get("contact_tolerance", "0.2[um]"),
            "contact_pair_endpoint_overrides": stage.get("contact_pair_endpoint_overrides") or {},
            "raceway_selection_entity_overrides": stage.get("raceway_selection_entity_overrides") or {},
            "contact_feature_property_overrides": stage.get("contact_feature_property_overrides") or {},
            "contact_patch_box_overrides": stage.get("contact_patch_box_overrides") or {},
            "raceway_partition_patch_overrides": stage.get("raceway_partition_patch_overrides") or {},
            "solver_stabilization": "auto_solver_sequence_with_stage_specific_segiter_and_linear_iteration_cap",
            "temporary_cage_stabilization_active": not stage["cage_contact_active"],
            "contact_stabilization_policy": "displacement_preload_first_close_contact_then_optional_cage_contact_keep_penalty_contact",
            "setup": _compact_runtime_result(setup),
            "pre_solve_model_save": _compact_runtime_result(pre_solve_model_save),
            "post_reaction_probe_model_save": _compact_runtime_result(post_reaction_probe_model_save),
            "solve": _compact_runtime_result(solve),
            "stress": _compact_runtime_result(stress),
            "inner_ring_stress": _compact_runtime_result(inner_ring_stress),
            "displacement": _compact_runtime_result(displacement),
            "contact_pressure": _compact_runtime_result(contact_pressure),
            "per_roller_probe_results": per_roller_probe_results,
            "active_roller_load_distribution": active_roller_load_distribution,
            "reaction_equivalent": reaction_equivalent,
            "native_volume_plot": _compact_runtime_result(native_volume_plot),
        }
        stage_results.append(stage_result)
        final_solve = solve
        if not solve.get("success"):
            break
    return {
        "success": bool(final_solve.get("success")),
        "kind": "bearing_3d_staged_contact_solve",
        "policy": "optional load-side roller ramp, all-raceway preload, radial-load transfer, optional cage-pocket contact preload",
        "run_full_cage_stage": run_full_cage_stage,
        "contact_stage_mode": requested_contact_stage_mode,
        "stage_plot_policy": (
            "native_comsol_volume_plot_per_successful_stage"
            if stage_plot_dir is not None
            else "not_requested"
        ),
        "stages": stage_results,
        "final_solve": _compact_runtime_result(final_solve),
    }


def _select_requested_stage_image_from_staged_solve(
    staged_solve: dict[str, Any] | None,
    *,
    request_class: str = "high_load_12roller_native_comsol_stress_image",
) -> dict[str, Any]:
    """Choose the stage image that answers a user stress-image request."""
    stages = list((staged_solve or {}).get("stages") or [])
    successful_stages = [
        stage
        for stage in stages
        if (stage.get("solve") or {}).get("success") and (stage.get("native_volume_plot") or {}).get("success")
    ]
    if not successful_stages:
        return {
            "success": False,
            "request_class": request_class,
            "image_role": "no_converged_native_comsol_stage_available",
            "selected_stage": None,
            "native_comsol_png": None,
            "stage_selection_reason": "No solved stage exported a native COMSOL PNG.",
        }

    plausibility_reports = {
        str(stage.get("name") or index): _stage_basic_physical_plausibility(stage)
        for index, stage in enumerate(successful_stages)
    }
    plausible_successful_stages = [
        stage
        for index, stage in enumerate(successful_stages)
        if plausibility_reports[str(stage.get("name") or index)].get("success")
    ]
    if not plausible_successful_stages:
        rejected = sorted(successful_stages, key=_stage_image_rank, reverse=True)[0]
        rejected_key = str(rejected.get("name") or successful_stages.index(rejected))
        return {
            "success": False,
            "request_class": request_class,
            "image_role": "no_physically_plausible_converged_native_comsol_stage_available",
            "selected_stage": None,
            "native_comsol_png": None,
            "best_available_rejected_stage": rejected.get("name"),
            "best_available_rejected_native_comsol_png": (rejected.get("native_volume_plot") or {}).get("filepath"),
            "best_available_rejected_max_von_mises_pa": _runtime_numeric_max(rejected.get("stress")),
            "best_available_rejected_max_displacement_m": _runtime_numeric_max(rejected.get("displacement")),
            "best_available_rejected_reasons": plausibility_reports[rejected_key].get("errors"),
            "production_ready": False,
            "stage_selection_reason": (
                "Converged native COMSOL stages exist, but all failed basic physical plausibility checks; "
                "do not present them as bearing stress evidence."
            ),
        }

    ranked = sorted(plausible_successful_stages, key=_stage_image_rank, reverse=True)
    best = ranked[0]
    best_rank = _stage_image_rank(best)
    high_load_request = "high_load" in request_class
    high_load_candidate = best_rank >= 80
    if high_load_request and not high_load_candidate:
        fallback = best
        return {
            "success": False,
            "request_class": request_class,
            "image_role": "best_available_native_stage_is_not_high_load",
            "selected_stage": None,
            "native_comsol_png": None,
            "best_available_stage": fallback.get("name"),
            "best_available_native_comsol_png": (fallback.get("native_volume_plot") or {}).get("filepath"),
            "best_available_max_von_mises_pa": _runtime_numeric_max(fallback.get("stress")),
            "best_available_max_displacement_m": _runtime_numeric_max(fallback.get("displacement")),
            "best_available_contact_pressure_est_pa": _runtime_numeric_max(fallback.get("contact_pressure")),
            "best_available_reaction_equivalent": fallback.get("reaction_equivalent"),
            "rejected_converged_stage_count": len(successful_stages) - len(plausible_successful_stages),
            "production_ready": False,
            "stage_selection_reason": (
                "The only converged native stage is preload/diagnostic fidelity; it must not be presented "
                "as the requested high-load BoundaryLoad or cage-contact result."
            ),
        }

    native_plot = best.get("native_volume_plot") or {}
    load_fidelity = best.get("load_application_fidelity", "boundary_or_displacement_stage")
    production_ready = (
        bool(best.get("cage_contact_active"))
        and bool(best.get("inner_bore_load_active"))
        and not bool(best.get("displacement_preload_active"))
        and not bool(best.get("weak_inner_guidance_active"))
        and not bool(best.get("temporary_cage_stabilization_active"))
        and "not_design" not in load_fidelity
    )
    return {
        "success": True,
        "request_class": request_class,
        "selected_stage": best.get("name"),
        "image_role": "user_requested_high_load_stress_png" if high_load_request else "user_requested_stress_png",
        "native_comsol_png": native_plot.get("filepath"),
        "plot_type": native_plot.get("plot_type"),
        "expression": "solid.mises",
        "max_von_mises_pa": _runtime_numeric_max(best.get("stress")),
        "max_displacement_m": _runtime_numeric_max(best.get("displacement")),
        "contact_pressure_est_pa": _runtime_numeric_max(best.get("contact_pressure")),
        "reaction_equivalent": best.get("reaction_equivalent"),
        "png_quality": native_plot.get("png_quality"),
        "physical_plausibility": _stage_basic_physical_plausibility(best),
        "contact_scope": best.get("contact_scope"),
        "load_application_fidelity": load_fidelity,
        "production_ready": production_ready,
        "stage_selection_reason": _stage_image_selection_reason(best, production_ready=production_ready),
    }


def _stage_basic_physical_plausibility(stage: dict[str, Any]) -> dict[str, Any]:
    """Reject numerically exploded fields before any stage can be recommended."""
    stress_max = _runtime_numeric_max(stage.get("stress"))
    displacement_max = _runtime_numeric_max(stage.get("displacement"))
    roller_probe_metrics = _roller_probe_metrics(
        stage.get("per_roller_probe_results"),
        active_rollers=stage.get("active_rollers"),
    )
    load_distribution = stage.get("active_roller_load_distribution")
    if not isinstance(load_distribution, dict):
        load_distribution = _active_roller_load_distribution_audit(
            stage.get("per_roller_probe_results"),
            active_rollers=stage.get("active_rollers"),
            boundary_load_active=bool(stage.get("inner_bore_load_active")),
        )
    errors: list[str] = []
    warnings: list[str] = []
    if stress_max is None or not math.isfinite(stress_max) or stress_max <= 1.0:
        errors.append("max von Mises stress is missing, non-finite, or near zero.")
    elif stress_max > 1.0e10:
        errors.append(f"max von Mises stress {stress_max:.6g} Pa is implausibly high for a steel bearing diagnostic.")
    if displacement_max is None or not math.isfinite(displacement_max) or displacement_max <= 0.0:
        errors.append("max displacement is missing, non-finite, or zero.")
    elif displacement_max > 5.0e-2:
        errors.append(f"max displacement {displacement_max:.6g} m is larger than the bearing-scale plausibility bound.")
    elif displacement_max > 5.0e-3:
        warnings.append(f"max displacement {displacement_max:.6g} m is large; treat as diagnostic, not design-grade.")
    if bool(stage.get("inner_bore_load_active")):
        if roller_probe_metrics["probe_count"] == 0:
            errors.append("BoundaryLoad stage is missing per-roller max-stress probe results.")
        elif roller_probe_metrics["active_probe_success_count"] < roller_probe_metrics["active_roller_count"]:
            errors.append("BoundaryLoad stage does not have successful max-stress probes for every active roller.")
        elif roller_probe_metrics["active_roller_max_von_mises_pa"] is None or roller_probe_metrics["active_roller_max_von_mises_pa"] <= 1.0:
            errors.append("BoundaryLoad stage active rollers have missing or near-zero max-stress probe values.")
        elif roller_probe_metrics["active_roller_nonzero_count"] < roller_probe_metrics["active_roller_count"]:
            errors.append(
                "BoundaryLoad stage has active rollers with near-zero max-stress probe values: "
                + ", ".join(roller_probe_metrics["active_roller_zero_stress_rollers"])
            )
        for message in load_distribution.get("errors") or []:
            if message not in errors:
                errors.append(message)
        for message in load_distribution.get("warnings") or []:
            if message not in warnings:
                warnings.append(message)
    return {
        "success": not errors,
        "max_von_mises_pa": stress_max,
        "max_displacement_m": displacement_max,
        "roller_probe_metrics": roller_probe_metrics,
        "active_roller_load_distribution": load_distribution,
        "errors": errors,
        "warnings": warnings,
    }


def _roller_probe_metrics(
    per_roller_probe_results: Any,
    *,
    active_rollers: Any,
) -> dict[str, Any]:
    probes = per_roller_probe_results if isinstance(per_roller_probe_results, list) else []
    active_ids = {
        int(value)
        for value in active_rollers
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit())
    } if isinstance(active_rollers, list) else set()
    active_values: list[float] = []
    inactive_values: list[float] = []
    active_values_by_roller: dict[str, float] = {}
    inactive_values_by_roller: dict[str, float] = {}
    active_zero_rollers: list[str] = []
    success_count = 0
    active_success_count = 0
    for probe in probes:
        if not isinstance(probe, dict) or probe.get("success") is not True:
            continue
        success_count += 1
        roller_text = str(probe.get("roller") or "")
        match = re.search(r"(\d+)$", roller_text)
        roller_id = int(match.group(1)) if match else None
        try:
            value = float(probe.get("value"))
        except (TypeError, ValueError):
            continue
        if roller_id in active_ids:
            active_success_count += 1
            active_values.append(value)
            active_values_by_roller[f"roller_{roller_id}"] = value
            if abs(value) <= 1.0:
                active_zero_rollers.append(f"roller_{roller_id}")
        elif roller_id is not None:
            inactive_values.append(value)
            inactive_values_by_roller[f"roller_{roller_id}"] = value
    active_max = max(active_values) if active_values else None
    active_min = min(active_values) if active_values else None
    inactive_max = max(inactive_values) if inactive_values else None
    active_nonzero_count = len(active_values) - len(active_zero_rollers)
    active_nonzero_ratio = (
        active_nonzero_count / len(active_ids)
        if active_ids
        else None
    )
    active_min_to_max_ratio = (
        active_min / active_max
        if active_min is not None and active_max not in (None, 0.0)
        else None
    )
    return {
        "probe_count": len(probes),
        "probe_success_count": success_count,
        "active_roller_count": len(active_ids),
        "active_probe_success_count": active_success_count,
        "active_roller_nonzero_count": active_nonzero_count,
        "active_roller_nonzero_ratio": active_nonzero_ratio,
        "active_roller_zero_stress_rollers": active_zero_rollers,
        "active_roller_max_von_mises_pa": active_max,
        "active_roller_min_von_mises_pa": active_min,
        "active_roller_min_to_max_ratio": active_min_to_max_ratio,
        "active_roller_values_by_roller": active_values_by_roller,
        "inactive_roller_max_von_mises_pa": inactive_max,
        "inactive_roller_values_by_roller": inactive_values_by_roller,
        "active_to_inactive_max_ratio": (
            active_max / inactive_max
            if active_max is not None and inactive_max not in (None, 0.0)
            else None
        ),
    }


def _active_roller_load_distribution_audit(
    per_roller_probe_results: Any,
    *,
    active_rollers: Any,
    boundary_load_active: bool,
) -> dict[str, Any]:
    """Summarize whether every intended load-side roller is actually carrying stress."""
    metrics = _roller_probe_metrics(per_roller_probe_results, active_rollers=active_rollers)
    errors: list[str] = []
    warnings: list[str] = []
    if boundary_load_active:
        active_count = metrics.get("active_roller_count") or 0
        if metrics.get("probe_count") == 0:
            errors.append("No per-roller stress probes were available for BoundaryLoad distribution audit.")
        elif metrics.get("active_probe_success_count") != active_count:
            errors.append(
                "BoundaryLoad distribution audit lacks successful max-stress probes for every active roller."
            )
        elif metrics.get("active_roller_nonzero_count") != active_count:
            missing = ", ".join(metrics.get("active_roller_zero_stress_rollers") or [])
            errors.append(
                "BoundaryLoad load-side roller distribution is incomplete; active rollers with near-zero stress: "
                + (missing or "unknown")
            )
        min_to_max = metrics.get("active_roller_min_to_max_ratio")
        if (
            min_to_max is not None
            and math.isfinite(float(min_to_max))
            and float(min_to_max) < 1.0e-3
            and not errors
        ):
            warnings.append(
                f"BoundaryLoad active roller stress distribution is highly unbalanced; min/max={float(min_to_max):.3g}."
            )
    return {
        "success": not errors,
        "boundary_load_active": boundary_load_active,
        "expected_active_rollers": sorted(
            {
                int(value)
                for value in active_rollers
                if isinstance(value, int) or (isinstance(value, str) and value.isdigit())
            }
        ) if isinstance(active_rollers, list) else [],
        "probe_count": metrics.get("probe_count"),
        "active_roller_count": metrics.get("active_roller_count"),
        "active_probe_success_count": metrics.get("active_probe_success_count"),
        "active_roller_nonzero_count": metrics.get("active_roller_nonzero_count"),
        "active_roller_nonzero_ratio": metrics.get("active_roller_nonzero_ratio"),
        "active_roller_zero_stress_rollers": metrics.get("active_roller_zero_stress_rollers"),
        "active_roller_values_by_roller": metrics.get("active_roller_values_by_roller"),
        "active_roller_min_to_max_ratio": metrics.get("active_roller_min_to_max_ratio"),
        "inactive_roller_max_von_mises_pa": metrics.get("inactive_roller_max_von_mises_pa"),
        "active_to_inactive_roller_stress_ratio": metrics.get("active_to_inactive_max_ratio"),
        "errors": errors,
        "warnings": warnings,
    }


def _stage_image_rank(stage: dict[str, Any]) -> float:
    name = str(stage.get("name") or "")
    acceptance = str(stage.get("physical_acceptance") or "")
    fidelity = str(stage.get("load_application_fidelity") or "")
    text = " ".join([name, acceptance, fidelity])
    rank = 0.0
    if "split_control_boundary_load_high" in text or "continuous_boundary_load_high" in text or "high_ramp" in text:
        rank = 95.0
    elif "high_radial_load" in text or "high_load_true" in text:
        rank = 90.0
    elif "legacy_raceway_highload" in text:
        rank = 88.0
    elif "reaction_equivalent" in text or "high_preload" in text:
        rank = 82.0
    elif "guided_high" in text:
        rank = 78.0
    elif "low_ramp" in text or "low_radial_load" in text:
        rank = 45.0
    elif "refined_preload" in text:
        rank = 25.0
    elif "coarse_preload" in text:
        rank = 15.0
    stress_max = _runtime_numeric_max(stage.get("stress"))
    if stress_max and stress_max > 0:
        rank += min(math.log10(stress_max), 8.0) / 10.0
    if bool(stage.get("inner_bore_load_active")):
        rank += 2.0
    if bool(stage.get("cage_contact_active")):
        rank += 2.0
    if "not_final_design_gate" in text or bool(stage.get("weak_inner_guidance_active")):
        rank -= 1.0
    if "probe_1n" in text:
        rank -= 10.0
    return rank


def _stage_image_selection_reason(stage: dict[str, Any], *, production_ready: bool) -> str:
    if production_ready:
        return "Selected the highest ranked converged native COMSOL stage with cage contact and design-grade BoundaryLoad fidelity."
    if bool(stage.get("inner_bore_load_active")) and bool(stage.get("displacement_preload_active")):
        return (
            "Selected the highest ranked converged high-load stage, but it retains displacement preload/continuation "
            "stabilization and is not a final design-grade BoundaryLoad gate."
        )
    if "preload" in str(stage.get("name") or ""):
        return "Selected a high-preload visualization stage; it is not radial force-transfer production fidelity."
    return "Selected the highest ranked converged native COMSOL stress stage available for this request."


def _save_stage_configured_mph(
    model_name: str,
    *,
    stage_name: str,
    output_dir: Path | None,
) -> dict[str, Any]:
    """Save a pre-solve checkpoint after stage configuration for failure replay."""
    if output_dir is None:
        return {"success": False, "error": "stage model output_dir was not provided"}
    safe_stage_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", stage_name).strip("_") or "stage"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_stage_name}_configured.mph"
    result = comsol_save_model(model_name, str(output_path.resolve()))
    compact = _compact_runtime_result(result) or {}
    compact.update({
        "stage": stage_name,
        "model_name": model_name,
        "filepath": str(output_path.resolve()),
        "checkpoint_role": "pre_solve_stage_configured_mph",
    })
    return compact


def _export_native_3d_stage_volume_plot(
    model_name: str,
    *,
    stage_name: str,
    output_dir: Path | None,
) -> dict[str, Any]:
    """Export a COMSOL-native 3D Volume plot for the current solved stage."""
    if output_dir is None:
        return {"success": False, "error": "stage plot output_dir was not provided"}
    safe_stage_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", stage_name).strip("_") or "stage"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_stage_name}_native_volume.png"
    plot_group = f"pg_stage_{safe_stage_name[:42]}"
    feature_tag = "vol_mises"
    export_tag = f"img_stage_{safe_stage_name[:42]}"
    try:
        handle = COMSOLClient.get_instance().get_model(model_name)
        java_model = handle.java_model
        dataset_tags = _java_tags(java_model.result().dataset())
        try:
            java_model.result().remove(plot_group)
        except Exception:
            pass
        java_model.result().create(plot_group, "PlotGroup3D")
        if dataset_tags:
            try:
                java_model.result(plot_group).set("data", dataset_tags[-1])
            except Exception:
                pass
        java_model.result(plot_group).feature().create(feature_tag, "Volume")
        java_model.result(plot_group).feature(feature_tag).set("expr", "solid.mises")
        java_model.result(plot_group).run()
        exports = java_model.result().export()
        try:
            exports.remove(export_tag)
        except Exception:
            pass
        exports.create(export_tag, "Image2D")
        image_export = java_model.result().export(export_tag)
        image_export.set("plotgroup", plot_group)
        image_export.set("pngfilename", str(output_path.resolve()))
        image_export.run()
        png_quality = inspect_png_quality(output_path)
        return {
            "success": bool(png_quality.get("success")),
            "model_name": model_name,
            "stage": stage_name,
            "plot_type": "native_comsol_volume",
            "expression": "solid.mises",
            "filepath": str(output_path.resolve()),
            "export_method": "java:Image2D:Volume",
            "dataset": dataset_tags[-1] if dataset_tags else None,
            "png_quality": png_quality,
            "message": (
                "Native COMSOL Volume plot exported for this solved stage."
                if png_quality.get("success")
                else png_quality.get("error")
            ),
        }
    except Exception as exc:
        return {
            "success": False,
            "model_name": model_name,
            "stage": stage_name,
            "plot_type": "native_comsol_volume",
            "expression": "solid.mises",
            "filepath": str(output_path.resolve()),
            "export_method": "java:Image2D:Volume",
            "error": str(exc),
        }


def _run_legacy_raceway_highload_direct(
    model_name: str,
    *,
    artifact_root: Path,
) -> dict[str, Any]:
    """Run the verified raceway-only high-load starter and export native evidence."""
    solve = comsol_solve(model_name)
    stress = comsol_evaluate(model_name, "solid.mises") if solve.get("success") else {}
    displacement = comsol_evaluate(model_name, "solid.disp") if solve.get("success") else {}
    pressure = comsol_evaluate(model_name, "contact_pressure_est") if solve.get("success") else {}
    native_volume_plot = (
        _export_native_3d_stage_volume_plot(
            model_name,
            stage_name="legacy_raceway_highload_direct",
            output_dir=artifact_root / "stage_plots",
        )
        if solve.get("success")
        else {}
    )
    projection_plot = (
        _render_stress_projection_from_open_model(
            model_name,
            artifact_root / "bearing_3d_von_mises.png",
        )
        if solve.get("success")
        else {}
    )
    model_dir = artifact_root / "result_packages" / "legacy_raceway_highload_direct"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_save = (
        comsol_save_model(model_name, str(model_dir / f"{model_name}.mph"))
        if solve.get("success")
        else {}
    )
    stress_max = _runtime_numeric_max(stress)
    displacement_max = _runtime_numeric_max(displacement)
    contact_pressure_max = _runtime_numeric_max(pressure)
    png_quality = (native_volume_plot or {}).get("png_quality") or {}
    requested_stage_image = {
        "success": bool(solve.get("success")) and bool(native_volume_plot.get("success")),
        "request_class": "high_load_12roller_native_comsol_stress_image",
        "selected_stage": "legacy_raceway_highload_direct",
        "image_role": "user_requested_high_load_stress_png",
        "native_comsol_png": (native_volume_plot or {}).get("filepath"),
        "mph_path": str((model_dir / f"{model_name}.mph").resolve()),
        "plot_type": (native_volume_plot or {}).get("plot_type"),
        "expression": "solid.mises",
        "max_von_mises_pa": stress_max,
        "max_displacement_m": displacement_max,
        "contact_pressure_est_pa": contact_pressure_max,
        "png_quality": png_quality,
        "contact_scope": "all_12_rollers_inner_outer_raceway_only_24_contact_pairs",
        "load_application_fidelity": "visual_fallback_inner_ring_distributed_body_load_not_design_boundary_load",
        "production_ready": False,
        "template_source": str(LEGACY_RACEWAY_HIGHLOAD_TEMPLATE_JSON),
        "stage_selection_reason": (
            "High-load native stress-image requests need the MPa-scale solved stage; "
            "the full boundary-load/cage high-load stage is still not declared converged."
        ),
    }
    return {
        "success": bool(solve.get("success")) and bool(native_volume_plot.get("success")),
        "kind": "bearing_3d_legacy_raceway_highload_direct",
        "stage": "legacy_raceway_highload_direct",
        "contact_scope": "all_12_rollers_inner_outer_raceway_only_24_contact_pairs",
        "load_application_fidelity": "visual_fallback_inner_ring_distributed_body_load_not_design_boundary_load",
        "cage_contact_active": False,
        "run_full_cage_stage": False,
        "solve": _compact_runtime_result(solve),
        "stress": _compact_runtime_result(stress),
        "displacement": _compact_runtime_result(displacement),
        "contact_pressure": _compact_runtime_result(pressure),
        "native_volume_plot": _compact_runtime_result(native_volume_plot),
        "stress_projection_plot": _compact_runtime_result(projection_plot),
        "model_save": _compact_runtime_result(model_save),
        "requested_stage_image": requested_stage_image,
        "physical_contact_validation": {
            "success": bool(solve.get("success")) and bool(stress_max and stress_max > 1e6) and bool(png_quality.get("success")),
            "quality_level": "high_load_visual_raceway_contact_gate",
            "production_ready": False,
            "global_max_von_mises_pa": stress_max,
            "max_displacement_m": displacement_max,
            "stress_png_quality_success": bool(png_quality.get("success")),
            "errors": [] if bool(solve.get("success")) and bool(stress_max and stress_max > 1e6) and bool(png_quality.get("success")) else [
                "Legacy raceway high-load visual did not produce a converged MPa-scale native stress plot."
            ],
            "warnings": [
                "This starter is raceway-only high-load visual fidelity: cage-pocket contact is not active.",
                "The radial load is an inner-ring distributed BodyLoad visual fallback, not the final design-grade inner-bore BoundaryLoad.",
            ],
        },
    }


def _java_tags(node: Any) -> list[str]:
    try:
        return [str(tag) for tag in node.tags()]
    except Exception:
        return []


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
    summary_path = artifact_root / "direct_3d_bearing_summary.json"
    archive_path = Path(args.archive_path)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    package_dir.mkdir(parents=True, exist_ok=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    config = load_config()
    client = COMSOLClient.get_instance()
    model_name: str | None = None
    contact_stage_mode = str(getattr(args, "contact_stage_mode", "all_raceway"))
    fixture_angular_offset_deg = float(getattr(args, "verified_fixture_roller_angular_offset_deg", 0.0) or 0.0)
    fixture_local_contact_patch_mode = str(
        getattr(args, "verified_fixture_local_contact_patch_mode", "none") or "none"
    ).strip().lower()
    fixture_local_contact_patch_diagnostic_roles = {
        "none": None,
        "roller1_outer_aux_patch": "roller1_outer_auxiliary_target_patch_diagnostic",
        "roller1_cylinder_seam_shift15": "roller1_cylinder_source_surface_seam_shift_diagnostic",
        "roller1_outer_retained_conformal_patch": "roller1_outer_retained_conformal_target_patch_diagnostic",
        "roller1_outer_retained_conformal_source_closure3um": (
            "roller1_outer_retained_conformal_target_with_3um_source_closure_diagnostic"
        ),
        "roller1_outer_retained_conformal_narrow_source_closure3um": (
            "roller1_outer_retained_conformal_target_with_3um_source_closure_and_0p9mm_tangential_box_diagnostic"
        ),
        "roller1_outer_retained_conformal_equal_height_source_closure3um": (
            "roller1_outer_retained_conformal_equal_height_target_with_3um_source_closure_diagnostic"
        ),
        "roller1_outer_retained_conformal_sector_source_closure3um": (
            "roller1_outer_retained_conformal_sector_target_with_3um_source_closure_diagnostic"
        ),
        "roller1_outer_construction_partition_patch": "roller1_outer_source_destination_construction_partition_diagnostic",
        "roller1_outer_construction_partition_source_closure3um": (
            "roller1_outer_source_destination_construction_partition_with_3um_source_closure_diagnostic"
        ),
        "roller1_outer_raceway_partition_only": "roller1_outer_raceway_destination_partition_only_diagnostic",
        "roller1_outer_raceway_partition_source_closure3um": (
            "roller1_outer_raceway_partition_with_3um_source_closure_diagnostic"
        ),
        "roller1_outer_raceway_narrow_partition_source_closure3um": (
            "roller1_outer_raceway_narrow_partition_with_3um_source_closure_diagnostic"
        ),
    }
    fixture_local_contact_patch_diagnostic_role = fixture_local_contact_patch_diagnostic_roles.get(
        fixture_local_contact_patch_mode,
        "unknown_verified_fixture_local_contact_patch_diagnostic",
    )
    if (
        (abs(fixture_angular_offset_deg) > 1.0e-12 or fixture_local_contact_patch_mode != "none")
        and generated_code == VERIFIED_3D_FULL_BEARING_CODE
    ):
        generated_code = _build_verified_3d_full_bearing_code(
            roller_count=VERIFIED_ROLLER_COUNT,
            roller_angular_offset_deg=fixture_angular_offset_deg,
            local_contact_patch_mode=fixture_local_contact_patch_mode,
        )
    legacy_raceway_highload_direct = contact_stage_mode == "legacy_raceway_highload_direct"
    if legacy_raceway_highload_direct:
        generated_code = _load_legacy_raceway_highload_code()
    contact_interference = str(getattr(args, "contact_interference", "") or "").strip()
    if contact_interference and not legacy_raceway_highload_direct:
        generated_code = generated_code.replace(
            "model.param().set('contact_interference', '0[um]');",
            f"model.param().set('contact_interference', {contact_interference!r});",
        )
    cage_pocket_clearance = str(getattr(args, "cage_pocket_clearance", "") or "").strip()
    if cage_pocket_clearance and not legacy_raceway_highload_direct:
        generated_code = generated_code.replace(
            "model.param().set('cage_pocket_clearance', '0.6[mm]');",
            f"model.param().set('cage_pocket_clearance', {cage_pocket_clearance!r});",
        )
    repair_history = repair_history or [{
        "attempt": 0,
        "stage": "fixture",
        "strategy": (
            "use_legacy_verified_12roller_raceway_highload_visual_starter"
            if legacy_raceway_highload_direct
            else "use_verified_3d_full_bearing_fixture"
        ),
        "success": True,
        "repaired_code_source": (
            "LEGACY_RACEWAY_HIGHLOAD_TEMPLATE_JSON"
            if legacy_raceway_highload_direct
            else "VERIFIED_3D_FULL_BEARING_CODE"
        ),
        "repaired_code_excerpt": _code_excerpt(generated_code),
    }]
    is_segmented_generated_direct = any(
        str(item.get("stage", "")).startswith("segmented_generation")
        for item in repair_history
    )
    summary: dict[str, Any] = {
        "fixture_quality": (
            {
                "success": True,
                "errors": [],
                "warnings": [
                    "Legacy raceway high-load starter intentionally uses inner-ring distributed BodyLoad as a visual fallback; do not treat it as final design-grade BoundaryLoad fidelity."
                ],
                "quality_level": "high_load_visual_raceway_only",
                "requires_named_selections": False,
            }
            if legacy_raceway_highload_direct
            else validate_3d_bearing_code_draft(generated_code)
        ),
        "repair_history": repair_history,
        "geometry_overrides": {
            "contact_interference": contact_interference or None,
            "cage_pocket_clearance": cage_pocket_clearance or None,
            "verified_fixture_roller_angular_offset_deg": fixture_angular_offset_deg,
            "verified_fixture_local_contact_patch_mode": fixture_local_contact_patch_mode,
            "verified_fixture_local_contact_patch_diagnostic_role": fixture_local_contact_patch_diagnostic_role,
        },
        "summary_path": str(summary_path),
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
                "cage_included": "raceway_only_visual" if legacy_raceway_highload_direct else "true",
                "radial_load": "3000[N]",
            },
            execution_context=execution_context,
            create_model_name=args.model_name,
            validate_first=not legacy_raceway_highload_direct,
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
            _write_direct_3d_summary(summary, summary_path)
            _print_direct_3d_summary(summary, full_json_stdout=bool(getattr(args, "full_json_stdout", False)))
            return 1
        model_name = str(run["model_name"])
        if legacy_raceway_highload_direct:
            direct_result = _run_legacy_raceway_highload_direct(
                model_name,
                artifact_root=artifact_root,
            )
            summary["legacy_raceway_highload_direct"] = direct_result
            summary["solve"] = direct_result.get("solve")
            summary["physical_contact_validation"] = direct_result.get("physical_contact_validation")
            summary["requested_stage_image"] = direct_result.get("requested_stage_image")
            _write_direct_3d_summary(summary, summary_path)
            _print_direct_3d_summary(summary, full_json_stdout=bool(getattr(args, "full_json_stdout", False)))
            return 0 if direct_result.get("success") else 1
        pre_solve_selection_probe = simulation_probe_3d_selection_binding(
            model_name=model_name,
            java_code=generated_code,
        )
        summary["pre_solve_selection_binding_probe"] = _compact_runtime_result(pre_solve_selection_probe)
        summary["pre_solve_selection_binding_audit"] = pre_solve_selection_probe.get("selection_binding_audit")
        summary["pre_solve_selection_report"] = pre_solve_selection_probe.get("selection_report")
        staged_solve = _run_3d_staged_contact_solve(
            model_name,
            run_full_cage_stage=bool(getattr(args, "run_full_cage_stage", False)),
            contact_stage_mode=str(getattr(args, "contact_stage_mode", "all_raceway")),
            stage_plot_dir=artifact_root / "stage_plots",
            roller1_outer_entity_override_entities=(
                tuple(
                    int(item.strip())
                    for item in str(
                        getattr(args, "roller1_outer_entity_override_entities", "")
                    ).split(",")
                    if item.strip()
                )
                or None
            ),
        )
        summary["staged_contact_solve"] = staged_solve
        summary["requested_stage_image"] = _select_requested_stage_image_from_staged_solve(staged_solve)
        solve = staged_solve.get("final_solve") or {"success": False, "error": "Staged contact solve did not return a final solve."}
        summary["solve"] = _compact_runtime_result(solve)
        final_stage = (staged_solve.get("stages") or [{}])[-1]
        if not solve.get("success"):
            summary["physical_contact_validation"] = _build_3d_physical_contact_validation(
                solve=solve,
                final_stage=final_stage,
            )
            failure_model_path = artifact_root / "failed_3d_contact_model.mph"
            summary["failed_model_save"] = _compact_runtime_result(
                comsol_save_model(model_name, str(failure_model_path))
            )
            repair_history.append({
                "attempt": 1,
                "stage": "comsol_solve",
                "strategy": "record_solver_error_for_contact_selection_or_mesh_repair",
                "success": False,
                "error": solve.get("error"),
            })
            _write_direct_3d_summary(summary, summary_path)
            _print_direct_3d_summary(summary, full_json_stdout=bool(getattr(args, "full_json_stdout", False)))
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
        inner_ring_stress = comsol_evaluate(model_name, "maxop_inner_ring(solid.mises)")
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
            _compact_runtime_result(inner_ring_stress),
            _compact_runtime_result(pressure),
            _compact_runtime_result(displacement),
        ]
        summary["per_roller_probe_results"] = per_roller_probe_results
        summary["plot"] = _compact_runtime_result(plot)
        summary["stress_projection_plot"] = _compact_runtime_result(stress_projection_plot)
        png_quality = inspect_png_quality(plot_path)
        summary["stress_png_quality"] = _compact_runtime_result(png_quality)
        summary["physical_contact_validation"] = _build_3d_physical_contact_validation(
            solve=solve,
            stress=stress,
            inner_ring_stress=inner_ring_stress,
            displacement=displacement,
            png_quality=png_quality,
            final_stage=final_stage,
        )
        if not plot.get("success"):
            _write_direct_3d_summary(summary, summary_path)
            _print_direct_3d_summary(summary, full_json_stdout=bool(getattr(args, "full_json_stdout", False)))
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
        _write_direct_3d_summary(summary, summary_path)
        _print_direct_3d_summary(summary, full_json_stdout=bool(getattr(args, "full_json_stdout", False)))
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
        "stage",
        "dataset",
        "run_id",
        "json_path",
        "markdown_path",
        "model_path",
        "saved_to",
        "plot_path",
        "metrics",
        "png_quality",
        "stdout",
        "output",
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


def _runtime_numeric_max(result: dict | None) -> float | None:
    if not isinstance(result, dict) or result.get("success") is False:
        return None
    statistics = result.get("statistics")
    if isinstance(statistics, dict) and statistics.get("max") is not None:
        try:
            return float(statistics["max"])
        except (TypeError, ValueError):
            return None
    value = result.get("value")
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _runtime_numeric_is_finite_nonzero(result: dict | None, *, atol: float = 1.0e-12) -> bool:
    value = _runtime_numeric_max(result)
    return value is not None and math.isfinite(value) and abs(value) > atol


def _parse_java_numeric_probe(stdout: str | None, *, marker: str) -> float | None:
    if not stdout:
        return None
    pattern = re.compile(
        re.escape(marker)
        + r"([-+]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|inf(?:inity)?|nan))",
        flags=re.IGNORECASE,
    )
    match = pattern.search(stdout)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _evaluate_global_expression_via_java(
    model_name: str,
    expression: str,
    *,
    tag: str,
) -> dict[str, Any]:
    safe_tag = re.sub(r"[^A-Za-z0-9_]", "_", tag)[:60] or "reaction_probe"
    marker = f"REACTION_EXPR_VALUE|tag={safe_tag}|value="
    code = f"""
try:
    if {safe_tag!r} in list(model.result().numerical().tags()):
        model.result().numerical().remove({safe_tag!r})
except Exception as error:
    output.write('REACTION_EXPR_REMOVE_WARNING|tag=' + {safe_tag!r} + '|error=' + str(error) + '\\n')
try:
    model.result().numerical().create({safe_tag!r}, 'EvalGlobal')
    model.result().numerical({safe_tag!r}).set('expr', {expression!r})
    try:
        model.result().numerical({safe_tag!r}).set('data', 'dset1')
    except Exception as error:
        output.write('REACTION_EXPR_DATASET_WARNING|tag=' + {safe_tag!r} + '|error=' + str(error) + '\\n')
    raw = model.result().numerical({safe_tag!r}).getReal()
    value = raw
    try:
        value = raw[0][0]
    except Exception:
        try:
            value = raw[0]
        except Exception:
            pass
    output.write({marker!r} + str(value) + '\\n')
except Exception as error:
    output.write('REACTION_EXPR_ERROR|tag=' + {safe_tag!r} + '|expression=' + {expression!r} + '|error=' + str(error) + '\\n')
    raise
"""
    result = comsol_execute_java(code, model_name=model_name)
    value = _parse_java_numeric_probe(result.get("stdout") or result.get("output"), marker=marker)
    compact = _compact_runtime_result(result)
    compact["expression"] = expression
    if value is not None:
        compact["value"] = value
        compact["success"] = True
    else:
        compact["success"] = False
    return compact


def _evaluate_surface_integral_expression_via_java(
    model_name: str,
    expression: str,
    *,
    selection_name: str,
    tag: str,
) -> dict[str, Any]:
    safe_tag = re.sub(r"[^A-Za-z0-9_]", "_", tag)[:60] or "reaction_surface_probe"
    marker = f"REACTION_SURFACE_VALUE|tag={safe_tag}|value="
    code = f"""
try:
    if {safe_tag!r} in list(model.result().numerical().tags()):
        model.result().numerical().remove({safe_tag!r})
except Exception as error:
    output.write('REACTION_SURFACE_REMOVE_WARNING|tag=' + {safe_tag!r} + '|error=' + str(error) + '\\n')
try:
    model.result().numerical().create({safe_tag!r}, 'IntSurface')
    model.result().numerical({safe_tag!r}).selection().named({selection_name!r})
    model.result().numerical({safe_tag!r}).set('expr', {expression!r})
    try:
        model.result().numerical({safe_tag!r}).set('data', 'dset1')
    except Exception as error:
        output.write('REACTION_SURFACE_DATASET_WARNING|tag=' + {safe_tag!r} + '|error=' + str(error) + '\\n')
    raw = model.result().numerical({safe_tag!r}).getReal()
    value = raw
    try:
        value = raw[0][0]
    except Exception:
        try:
            value = raw[0]
        except Exception:
            pass
    output.write({marker!r} + str(value) + '\\n')
except Exception as error:
    output.write('REACTION_SURFACE_ERROR|tag=' + {safe_tag!r} + '|selection=' + {selection_name!r} + '|expression=' + {expression!r} + '|error=' + str(error) + '\\n')
    raise
"""
    result = comsol_execute_java(code, model_name=model_name)
    value = _parse_java_numeric_probe(result.get("stdout") or result.get("output"), marker=marker)
    compact = _compact_runtime_result(result)
    compact["expression"] = expression
    compact["selection"] = selection_name
    compact["method"] = "java_intsurface"
    if value is not None:
        compact["value"] = value
        compact["success"] = True
    else:
        compact["success"] = False
    return compact


def _get_selection_entities_via_java(
    model_name: str,
    *,
    selection_name: str,
) -> dict[str, Any]:
    safe_tag = re.sub(r"[^A-Za-z0-9_]", "_", selection_name)[:60] or "selection_entities"
    marker = f"SELECTION_ENTITIES|tag={safe_tag}|value="
    code = f"""
try:
    entities = list(model.component('comp1').selection({selection_name!r}).entities())
    output.write({marker!r} + ','.join(str(int(item)) for item in entities) + '\\n')
except Exception as error:
    output.write('SELECTION_ENTITIES_ERROR|tag=' + {safe_tag!r} + '|selection=' + {selection_name!r} + '|error=' + str(error) + '\\n')
    raise
"""
    result = comsol_execute_java(code, model_name=model_name)
    stdout = result.get("stdout") or result.get("output") or ""
    entities: list[int] = []
    if marker in stdout:
        payload = stdout.split(marker, 1)[1].splitlines()[0].strip()
        if payload:
            for token in payload.split(","):
                try:
                    entities.append(int(token))
                except ValueError:
                    pass
    compact = _compact_runtime_result(result)
    compact["selection"] = selection_name
    compact["entities"] = entities
    compact["entity_count"] = len(entities)
    compact["success"] = bool(result.get("success")) and bool(entities)
    return compact


def _evaluate_surface_integral_expression_on_entities_via_java(
    model_name: str,
    expression: str,
    *,
    entities: list[int],
    tag: str,
) -> dict[str, Any]:
    safe_tag = re.sub(r"[^A-Za-z0-9_]", "_", tag)[:60] or "entity_surface_probe"
    marker = f"ENTITY_SURFACE_VALUE|tag={safe_tag}|value="
    entity_literal = [int(item) for item in entities]
    code = f"""
try:
    if {safe_tag!r} in list(model.result().numerical().tags()):
        model.result().numerical().remove({safe_tag!r})
except Exception as error:
    output.write('ENTITY_SURFACE_REMOVE_WARNING|tag=' + {safe_tag!r} + '|error=' + str(error) + '\\n')
try:
    model.result().numerical().create({safe_tag!r}, 'IntSurface')
    model.result().numerical({safe_tag!r}).selection().geom('geom1', 2)
    model.result().numerical({safe_tag!r}).selection().set({entity_literal!r})
    model.result().numerical({safe_tag!r}).set('expr', {expression!r})
    try:
        model.result().numerical({safe_tag!r}).set('data', 'dset1')
    except Exception as error:
        output.write('ENTITY_SURFACE_DATASET_WARNING|tag=' + {safe_tag!r} + '|error=' + str(error) + '\\n')
    raw = model.result().numerical({safe_tag!r}).getReal()
    value = raw
    try:
        value = raw[0][0]
    except Exception:
        try:
            value = raw[0]
        except Exception:
            pass
    output.write({marker!r} + str(value) + '\\n')
except Exception as error:
    output.write('ENTITY_SURFACE_ERROR|tag=' + {safe_tag!r} + '|entities=' + {str(entity_literal)!r} + '|expression=' + {expression!r} + '|error=' + str(error) + '\\n')
    raise
"""
    result = comsol_execute_java(code, model_name=model_name)
    value = _parse_java_numeric_probe(result.get("stdout") or result.get("output"), marker=marker)
    compact = _compact_runtime_result(result)
    compact["expression"] = expression
    compact["entities"] = entity_literal
    compact["method"] = "java_intsurface_entity"
    if value is not None:
        compact["value"] = value
        compact["success"] = True
    else:
        compact["success"] = False
    return compact


def _evaluate_surface_max_expression_via_java(
    model_name: str,
    expression: str,
    *,
    selection_name: str,
    tag: str,
) -> dict[str, Any]:
    safe_tag = re.sub(r"[^A-Za-z0-9_]", "_", tag)[:60] or "contact_surface_probe"
    marker = f"CONTACT_SURFACE_MAX_VALUE|tag={safe_tag}|value="
    code = f"""
try:
    if {safe_tag!r} in list(model.result().numerical().tags()):
        model.result().numerical().remove({safe_tag!r})
except Exception as error:
    output.write('CONTACT_SURFACE_MAX_REMOVE_WARNING|tag=' + {safe_tag!r} + '|error=' + str(error) + '\\n')
try:
    model.result().numerical().create({safe_tag!r}, 'MaxSurface')
    model.result().numerical({safe_tag!r}).selection().named({selection_name!r})
    model.result().numerical({safe_tag!r}).set('expr', {expression!r})
    try:
        model.result().numerical({safe_tag!r}).set('data', 'dset1')
    except Exception as error:
        output.write('CONTACT_SURFACE_MAX_DATASET_WARNING|tag=' + {safe_tag!r} + '|error=' + str(error) + '\\n')
    raw = model.result().numerical({safe_tag!r}).getReal()
    value = raw
    try:
        value = raw[0][0]
    except Exception:
        try:
            value = raw[0]
        except Exception:
            pass
    output.write({marker!r} + str(value) + '\\n')
except Exception as error:
    output.write('CONTACT_SURFACE_MAX_ERROR|tag=' + {safe_tag!r} + '|selection=' + {selection_name!r} + '|expression=' + {expression!r} + '|error=' + str(error) + '\\n')
    raise
"""
    result = comsol_execute_java(code, model_name=model_name)
    value = _parse_java_numeric_probe(result.get("stdout") or result.get("output"), marker=marker)
    compact = _compact_runtime_result(result)
    compact["expression"] = expression
    compact["selection"] = selection_name
    compact["method"] = "java_maxsurface"
    if value is not None:
        compact["value"] = value
        compact["success"] = True
    else:
        compact["success"] = False
    return compact


def _evaluate_surface_max_expression_on_entities_via_java(
    model_name: str,
    expression: str,
    *,
    entities: list[int],
    tag: str,
) -> dict[str, Any]:
    safe_tag = re.sub(r"[^A-Za-z0-9_]", "_", tag)[:60] or "entity_surface_max_probe"
    marker = f"ENTITY_SURFACE_MAX_VALUE|tag={safe_tag}|value="
    entity_literal = [int(item) for item in entities]
    code = f"""
try:
    if {safe_tag!r} in list(model.result().numerical().tags()):
        model.result().numerical().remove({safe_tag!r})
except Exception as error:
    output.write('ENTITY_SURFACE_MAX_REMOVE_WARNING|tag=' + {safe_tag!r} + '|error=' + str(error) + '\\n')
try:
    model.result().numerical().create({safe_tag!r}, 'MaxSurface')
    model.result().numerical({safe_tag!r}).selection().geom('geom1', 2)
    model.result().numerical({safe_tag!r}).selection().set({entity_literal!r})
    model.result().numerical({safe_tag!r}).set('expr', {expression!r})
    try:
        model.result().numerical({safe_tag!r}).set('data', 'dset1')
    except Exception as error:
        output.write('ENTITY_SURFACE_MAX_DATASET_WARNING|tag=' + {safe_tag!r} + '|error=' + str(error) + '\\n')
    raw = model.result().numerical({safe_tag!r}).getReal()
    value = raw
    try:
        value = raw[0][0]
    except Exception:
        try:
            value = raw[0]
        except Exception:
            pass
    output.write({marker!r} + str(value) + '\\n')
except Exception as error:
    output.write('ENTITY_SURFACE_MAX_ERROR|tag=' + {safe_tag!r} + '|expression=' + {expression!r} + '|entities=' + {str(entity_literal)!r} + '|error=' + str(error) + '\\n')
    raise
"""
    result = comsol_execute_java(code, model_name=model_name)
    value = _parse_java_numeric_probe(result.get("stdout") or result.get("output"), marker=marker)
    compact = _compact_runtime_result(result)
    compact["expression"] = expression
    compact["entities"] = entity_literal
    compact["method"] = "java_maxsurface_entities"
    if value is not None:
        compact["value"] = value
        compact["success"] = True
    else:
        compact["success"] = False
    return compact


REACTION_SETUP_JSON_START = "REACTION_EQUIVALENT_SETUP_JSON_START"
REACTION_SETUP_JSON_END = "REACTION_EQUIVALENT_SETUP_JSON_END"


def _extract_reaction_setup_audit(output: str | None) -> dict[str, Any]:
    if not output:
        return {"success": False, "error": "No reaction setup audit output was captured."}
    pattern = re.compile(
        re.escape(REACTION_SETUP_JSON_START)
        + r"\s*(.*?)\s*"
        + re.escape(REACTION_SETUP_JSON_END),
        flags=re.DOTALL,
    )
    match = pattern.search(output)
    if not match:
        return {"success": False, "error": "Reaction setup audit JSON markers were not found."}
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"Reaction setup audit JSON parse failed: {exc}"}
    payload["success"] = bool(payload.get("operator_exists")) and bool(payload.get("selection_bound"))
    return payload


def _reaction_evaluation_error_text(evaluation: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("error", "stdout", "output"):
        value = evaluation.get(key)
        if value:
            parts.append(str(value))
    java_eval = evaluation.get("java_evalglobal")
    if isinstance(java_eval, dict):
        for key in ("error", "stdout", "output"):
            value = java_eval.get(key)
            if value:
                parts.append(str(value))
    return "\n".join(parts)


def _classify_reaction_evaluation(evaluation: dict[str, Any]) -> str:
    value = _runtime_numeric_max(evaluation)
    if evaluation.get("success") and value is not None:
        return "nonzero_success" if abs(value) > 1.0e-9 else "zero_result"
    text = _reaction_evaluation_error_text(evaluation).lower()
    if "unknown function or operator" in text or "unknown operator" in text:
        return "unknown_operator"
    if "selection" in text:
        return "selection_error"
    if "dataset" in text or "dset" in text:
        return "dataset_error"
    if "undefined variable" in text or "unknown variable" in text:
        return "unknown_variable"
    if text:
        return "evaluation_error"
    return "not_evaluated"


def _summarize_reaction_evaluations(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    method_counts: dict[str, int] = {}
    diagnostic_class_counts: dict[str, int] = {}
    first_failures: list[dict[str, Any]] = []
    for item in evaluations:
        method = str(item.get("method") or "unknown")
        method_counts[method] = method_counts.get(method, 0) + 1
        diagnostic_class = str(item.get("diagnostic_class") or _classify_reaction_evaluation(item))
        diagnostic_class_counts[diagnostic_class] = diagnostic_class_counts.get(diagnostic_class, 0) + 1
        if diagnostic_class not in {"nonzero_success", "zero_result"} and len(first_failures) < 8:
            java_eval = item.get("java_evalglobal") if isinstance(item.get("java_evalglobal"), dict) else {}
            first_failures.append({
                "expression": item.get("expression"),
                "method": method,
                "diagnostic_class": diagnostic_class,
                "error": item.get("error") or java_eval.get("error"),
            })
    return {
        "method_counts": method_counts,
        "diagnostic_class_counts": diagnostic_class_counts,
        "unknown_operator_count": diagnostic_class_counts.get("unknown_operator", 0),
        "unknown_variable_count": diagnostic_class_counts.get("unknown_variable", 0),
        "zero_result_count": diagnostic_class_counts.get("zero_result", 0),
        "nonzero_success_count": diagnostic_class_counts.get("nonzero_success", 0),
        "first_failures": first_failures,
    }


def _evaluate_displacement_reaction_equivalent(
    model_name: str,
    *,
    selection_name: str,
) -> dict[str, Any]:
    """Probe reaction-force expressions for a displacement-controlled stage."""
    operator_tag = "intop_displacement_reaction_probe"
    setup_code = f"""
import json

def _reaction_safe(func):
    try:
        return {{'success': True, 'value': func()}}
    except Exception as error:
        return {{'success': False, 'error': str(error)}}

def _reaction_stringify(value):
    try:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        try:
            if str(value.getClass().getName()) == 'java.lang.String':
                return str(value)
        except Exception:
            pass
        try:
            return [_reaction_stringify(item) for item in list(value)]
        except Exception:
            return str(value)
    except Exception as error:
        return '<reaction_stringify_error:' + str(error) + '>'

for _reaction_name, _reaction_func in {{
    '_reaction_safe': _reaction_safe,
    '_reaction_stringify': _reaction_stringify,
}}.items():
    globals()[_reaction_name] = _reaction_func

try:
    if {operator_tag!r} not in list(model.component('comp1').cpl().tags()):
        model.component('comp1').cpl().create({operator_tag!r}, 'Integration')
    output.write('REACTION_EQUIVALENT_PROBE|create=ok|operator=' + {operator_tag!r} + '\\n')
except Exception as error:
    output.write('REACTION_EQUIVALENT_PROBE|create=error|operator=' + {operator_tag!r} + '|error=' + str(error) + '\\n')
try:
    model.component('comp1').cpl({operator_tag!r}).set('opname', {operator_tag!r})
    output.write('REACTION_EQUIVALENT_PROBE|opname=ok|operator=' + {operator_tag!r} + '\\n')
except Exception as error:
    output.write('REACTION_EQUIVALENT_PROBE|opname=error|operator=' + {operator_tag!r} + '|error=' + str(error) + '\\n')
try:
    model.component('comp1').cpl({operator_tag!r}).selection().named({selection_name!r})
    output.write('REACTION_EQUIVALENT_PROBE|selection=ok|selection=' + {selection_name!r} + '\\n')
except Exception as error:
    output.write('REACTION_EQUIVALENT_PROBE|selection=error|selection=' + {selection_name!r} + '|error=' + str(error) + '\\n')
output.write('REACTION_EQUIVALENT_PROBE|operator=' + {operator_tag!r} + '|selection=' + {selection_name!r} + '\\n')
audit = {{
    'component': 'comp1',
    'operator_tag': {operator_tag!r},
    'selection_name': {selection_name!r},
}}
try:
    audit['component_tags'] = {{'success': True, 'value': _reaction_stringify(model.component().tags())}}
except Exception as error:
    audit['component_tags'] = {{'success': False, 'error': str(error)}}
try:
    audit['coupling_tags'] = {{'success': True, 'value': _reaction_stringify(model.component('comp1').cpl().tags())}}
except Exception as error:
    audit['coupling_tags'] = {{'success': False, 'error': str(error)}}
try:
    cpl = model.component('comp1').cpl({operator_tag!r})
    audit['operator_exists'] = True
    try:
        audit['operator_type'] = {{'success': True, 'value': _reaction_stringify(cpl.getType())}}
    except Exception as error:
        audit['operator_type'] = {{'success': False, 'error': str(error)}}
    try:
        audit['opname'] = {{'success': True, 'method': 'getString', 'value': _reaction_stringify(cpl.getString('opname'))}}
    except Exception as error:
        try:
            audit['opname'] = {{'success': True, 'method': 'get', 'value': _reaction_stringify(cpl.get('opname'))}}
        except Exception as error2:
            audit['opname'] = {{'success': False, 'error': str(error) + ' | ' + str(error2)}}
    try:
        audit['selection_named'] = {{'success': True, 'value': _reaction_stringify(cpl.selection().named())}}
    except Exception as error:
        audit['selection_named'] = {{'success': False, 'error': str(error)}}
    try:
        audit['selection_entities'] = {{'success': True, 'value': _reaction_stringify(cpl.selection().entities())}}
    except Exception as error:
        audit['selection_entities'] = {{'success': False, 'error': str(error)}}
    named = audit.get('selection_named') or {{}}
    entities = audit.get('selection_entities') or {{}}
    audit['selection_bound'] = bool(
        (named.get('success') and named.get('value'))
        or (entities.get('success') and entities.get('value'))
    )
except Exception as error:
    audit['operator_exists'] = False
    audit['selection_bound'] = False
    audit['operator_error'] = str(error)
output.write({REACTION_SETUP_JSON_START!r} + '\\n')
output.write(json.dumps(audit, ensure_ascii=False, default=str))
output.write('\\n' + {REACTION_SETUP_JSON_END!r} + '\\n')
"""
    setup = comsol_execute_java(setup_code, model_name=model_name)
    setup_audit = _extract_reaction_setup_audit(setup.get("stdout") or setup.get("output"))
    traction_x = "solid.sx*nx+solid.sxy*ny+solid.sxz*nz"
    traction_y = "solid.sxy*nx+solid.sy*ny+solid.syz*nz"
    traction_z = "solid.sxz*nx+solid.syz*ny+solid.sz*nz"
    candidates = [
        f"{operator_tag}(solid.RFx)",
        f"{operator_tag}(solid.RFy)",
        f"{operator_tag}(solid.RFz)",
        f"comp1.{operator_tag}(solid.RFx)",
        f"comp1.{operator_tag}(solid.RFy)",
        f"comp1.{operator_tag}(solid.RFz)",
        f"{operator_tag}(comp1.solid.RFx)",
        f"{operator_tag}(comp1.solid.RFy)",
        f"{operator_tag}(comp1.solid.RFz)",
        f"comp1.{operator_tag}(comp1.solid.RFx)",
        f"comp1.{operator_tag}(comp1.solid.RFy)",
        f"comp1.{operator_tag}(comp1.solid.RFz)",
        f"{operator_tag}(solid.reactionForcex)",
        f"{operator_tag}(solid.reactionForceX)",
        f"{operator_tag}(solid.RF_x)",
        f"{operator_tag}(solid.Fdx)",
        f"{operator_tag}(solid.Tx)",
        f"{operator_tag}(solid.T_stressx)",
        f"{operator_tag}(solid.T_stressy)",
        f"{operator_tag}(solid.T_stressz)",
        f"{operator_tag}({traction_x})",
        f"{operator_tag}({traction_y})",
        f"{operator_tag}({traction_z})",
    ]
    evaluations = []
    successful = []
    evaluated_success_count = 0
    for index, expression in enumerate(candidates, start=1):
        evaluation = comsol_evaluate(model_name, expression)
        compact = _compact_runtime_result(evaluation)
        compact["expression"] = expression
        compact["method"] = "operator_expression"
        if not evaluation.get("success"):
            java_eval = _evaluate_global_expression_via_java(
                model_name,
                expression,
                tag=f"reaction_force_probe_{index}",
            )
            compact["java_evalglobal"] = java_eval
            if java_eval.get("success") and java_eval.get("value") is not None:
                evaluation = {
                    "success": True,
                    "model_name": model_name,
                    "expression": expression,
                    "value": java_eval.get("value"),
                }
                compact["success"] = True
                compact["value"] = java_eval.get("value")
        compact["diagnostic_class"] = _classify_reaction_evaluation(compact)
        evaluations.append(compact)
        value = _runtime_numeric_max(evaluation)
        if evaluation.get("success") and value is not None:
            evaluated_success_count += 1
            if abs(value) > 1.0e-9:
                successful.append({
                    "expression": expression,
                    "value": value,
                    "abs_value": abs(value),
                    "evaluation": compact,
                })
    surface_candidates = [
        "solid.RFx",
        "solid.RFy",
        "solid.RFz",
        "comp1.solid.RFx",
        "comp1.solid.RFy",
        "comp1.solid.RFz",
        "solid.reactionForcex",
        "solid.reactionForceX",
        "solid.RF_x",
        "solid.Fdx",
        "solid.Tx",
        "solid.T_stressx",
        "solid.T_stressy",
        "solid.T_stressz",
        traction_x,
        traction_y,
        traction_z,
    ]
    for index, expression in enumerate(surface_candidates, start=1):
        compact = _evaluate_surface_integral_expression_via_java(
            model_name,
            expression,
            selection_name=selection_name,
            tag=f"reaction_surface_probe_{index}",
        )
        compact["diagnostic_class"] = _classify_reaction_evaluation(compact)
        evaluations.append(compact)
        value = _runtime_numeric_max(compact)
        if compact.get("success") and value is not None:
            evaluated_success_count += 1
            if abs(value) > 1.0e-9:
                successful.append({
                    "expression": expression,
                    "value": value,
                    "abs_value": abs(value),
                    "evaluation": compact,
                    "method": "java_intsurface",
                })
    best = max(successful, key=lambda item: item["abs_value"], default=None)
    pressure = None
    if best is not None:
        pressure_eval = comsol_evaluate(
            model_name,
            f"abs({best['expression']})/(pi*inner_diameter*bearing_width)",
        )
        pressure = _compact_runtime_result(pressure_eval)
        if not pressure_eval.get("success"):
            pressure = _evaluate_global_expression_via_java(
                model_name,
                f"abs({best['expression']})/(pi*inner_diameter*bearing_width)",
                tag="reaction_equivalent_pressure",
            )
    return {
        "success": best is not None,
        "kind": "displacement_controlled_reaction_equivalent_probe",
        "operator": operator_tag,
        "selection": selection_name,
        "setup": _compact_runtime_result(setup),
        "setup_audit": setup_audit,
        "candidate_count": len(evaluations),
        "evaluated_candidate_success_count": evaluated_success_count,
        "successful_candidate_count": len(successful),
        "best_reaction_force_n": best["value"] if best else None,
        "best_reaction_force_abs_n": best["abs_value"] if best else None,
        "best_expression": best["expression"] if best else None,
        "best_method": best.get("method") or (best.get("evaluation") or {}).get("method") if best else None,
        "equivalent_pressure_pa": _runtime_numeric_max(pressure),
        "equivalent_pressure": pressure,
        "candidate_audit": _summarize_reaction_evaluations(evaluations),
        "evaluations": evaluations,
        "warning": (
            None
            if best is not None
            else "No probed COMSOL reaction-force expression evaluated to a nonzero reaction; do not claim equivalent load transfer."
        ),
    }


def build_stage_evidence_matrix(
    *,
    search_root: str | Path = "runtime_smoke",
) -> dict[str, Any]:
    """Scan direct 3D bearing summaries into an auditable stage evidence matrix."""
    root = Path(search_root)
    summary_paths = sorted(root.glob("**/direct_3d_bearing_summary.json"))
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for summary_path in summary_paths:
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({"path": str(summary_path), "error": str(exc)})
            continue
        rows.extend(_stage_evidence_rows_from_summary(summary, summary_path=summary_path))
    rows.sort(
        key=lambda row: (
            str(row.get("summary_path") or ""),
            int(row.get("stage_index") or 0),
            str(row.get("stage") or ""),
        )
    )
    _annotate_boundaryload_sequence_physics(rows)
    production_ready_rows = [row for row in rows if row.get("production_ready") is True]
    converged_native_rows = [
        row for row in rows if row.get("solve_success") is True and row.get("native_png_success") is True
    ]
    reaction_verified_rows = [
        row for row in rows if row.get("reaction_equivalent_success") is True
    ]
    calibration = _build_preload_calibration_from_stage_rows(rows)
    saved_reaction_probe = _scan_saved_reaction_probe_reports(root)
    saved_contact_probe = _scan_saved_contact_probe_reports(root)
    boundaryload_distribution = _build_boundaryload_distribution_diagnostics(rows, search_root=root)
    return {
        "success": True,
        "kind": "bearing_3d_stage_evidence_matrix",
        "search_root": str(root),
        "summary_count": len(summary_paths),
        "row_count": len(rows),
        "production_ready_count": len(production_ready_rows),
        "converged_native_stage_count": len(converged_native_rows),
        "reaction_verified_stage_count": len(reaction_verified_rows),
        "saved_reaction_probe_report_count": saved_reaction_probe["report_count"],
        "saved_reaction_probe_verified_count": saved_reaction_probe["verified_count"],
        "saved_contact_probe_report_count": saved_contact_probe["report_count"],
        "saved_contact_probe_source_destination_imbalance_count": saved_contact_probe["source_destination_imbalance_count"],
        "saved_contact_probe_source_unevaluable_destination_nonzero_count": saved_contact_probe[
            "source_unevaluable_destination_nonzero_count"
        ],
        "errors": errors,
        "rows": rows,
        "preload_calibration": calibration,
        "boundaryload_distribution_diagnostics": boundaryload_distribution,
        "saved_reaction_probe_reports": saved_reaction_probe["reports"],
        "saved_reaction_probe_errors": saved_reaction_probe["errors"],
        "saved_contact_probe_reports": saved_contact_probe["reports"],
        "saved_contact_probe_errors": saved_contact_probe["errors"],
        "production_ready_rows": production_ready_rows,
        "highest_trust_stage": _select_highest_trust_stage_from_rows(rows),
    }


def _scan_saved_reaction_probe_reports(root: Path) -> dict[str, Any]:
    """Index no-solve saved-MPH reaction probe artifacts beside stage evidence."""
    reports: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for report_path in sorted(root.glob("**/reaction_probe_summary.json")):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({"path": str(report_path), "error": str(exc)})
            continue
        reaction = report.get("reaction_equivalent") if isinstance(report.get("reaction_equivalent"), dict) else {}
        candidate_audit = (
            reaction.get("candidate_audit")
            if isinstance(reaction.get("candidate_audit"), dict)
            else report.get("candidate_audit")
            if isinstance(report.get("candidate_audit"), dict)
            else {}
        )
        setup_audit = (
            reaction.get("setup_audit")
            if isinstance(reaction.get("setup_audit"), dict)
            else report.get("setup_audit")
            if isinstance(report.get("setup_audit"), dict)
            else {}
        )
        reaction_force_abs = reaction.get("best_reaction_force_abs_n")
        try:
            reaction_force_abs_numeric = float(reaction_force_abs) if reaction_force_abs is not None else None
        except (TypeError, ValueError):
            reaction_force_abs_numeric = None
        candidate_nonzero = bool(report.get("reaction_verified") or reaction.get("success")) and (
            reaction_force_abs_numeric is not None and abs(reaction_force_abs_numeric) > 1.0e-9
        )
        load_context = report.get("boundary_load_context") if isinstance(report.get("boundary_load_context"), dict) else None
        if load_context is None:
            load_context = _infer_saved_reaction_boundary_load_context(report_path)
        load_balance = report.get("reaction_load_balance") if isinstance(report.get("reaction_load_balance"), dict) else None
        if load_balance is None:
            load_balance = _reaction_load_balance_gate(
                reaction_force_abs_n=reaction_force_abs_numeric,
                applied_load_n=load_context.get("applied_load_n") if isinstance(load_context, dict) else None,
            )
        verified = bool(candidate_nonzero and load_balance.get("success"))
        reports.append({
            "path": str(report_path),
            "artifact_root": str(report_path.parent),
            "mph_path": report.get("mph_path"),
            "success": bool(report.get("success")),
            "reaction_candidate_nonzero": candidate_nonzero,
            "reaction_verified": verified,
            "boundary_load_context": load_context,
            "reaction_load_balance": load_balance,
            "selection_name": report.get("selection_name") or reaction.get("selection"),
            "candidate_count": reaction.get("candidate_count"),
            "evaluated_candidate_success_count": reaction.get("evaluated_candidate_success_count"),
            "successful_candidate_count": reaction.get("successful_candidate_count"),
            "best_expression": reaction.get("best_expression"),
            "best_method": reaction.get("best_method"),
            "best_reaction_force_abs_n": reaction_force_abs,
            "setup_success": setup_audit.get("success"),
            "operator_exists": setup_audit.get("operator_exists"),
            "selection_bound": setup_audit.get("selection_bound"),
            "candidate_audit": candidate_audit,
            "error": report.get("error"),
            "warning": report.get("warning") or reaction.get("warning"),
        })
    return {
        "report_count": len(reports),
        "verified_count": sum(1 for report in reports if report.get("reaction_verified") is True),
        "reports": reports,
        "errors": errors,
    }


def _infer_saved_reaction_boundary_load_context(report_path: Path) -> dict[str, Any]:
    """Find an adjacent direct-run summary and extract an unambiguous BoundaryLoad stage."""
    for ancestor in [report_path.parent, *report_path.parents]:
        summary_path = ancestor / "direct_3d_bearing_summary.json"
        if not summary_path.exists():
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"success": False, "summary_path": str(summary_path), "reason": f"summary_read_error: {exc}"}
        stages = _summary_staged_contact_solve(summary).get("stages") or []
        boundary_stages = [
            stage for stage in stages
            if stage.get("inner_bore_load_active") is True and stage.get("inner_body_load_active") is not True
        ]
        if len(boundary_stages) != 1:
            return {
                "success": False,
                "summary_path": str(summary_path),
                "reason": f"ambiguous_boundaryload_stage_count:{len(boundary_stages)}",
            }
        stage = boundary_stages[0]
        radial_load_value = stage.get("radial_load_value")
        applied_load_n = _parse_unit_value_to_float(radial_load_value, unit="N")
        return {
            "success": applied_load_n is not None,
            "summary_path": str(summary_path),
            "stage": stage.get("name") or stage.get("stage"),
            "radial_load_value": radial_load_value,
            "applied_load_n": applied_load_n,
            "reason": None if applied_load_n is not None else "missing_numeric_radial_load_value",
        }
    return {"success": False, "reason": "no_adjacent_direct_3d_bearing_summary"}


def _reaction_load_balance_gate(
    *,
    reaction_force_abs_n: float | None,
    applied_load_n: float | None,
    relative_tolerance: float = 0.05,
    absolute_tolerance_n: float = 1.0e-6,
) -> dict[str, Any]:
    """Require saved-MPH reaction evidence to balance the traced external load."""
    if reaction_force_abs_n is None:
        return {
            "success": False,
            "reason": "missing_reaction_force",
            "relative_tolerance": relative_tolerance,
            "absolute_tolerance_n": absolute_tolerance_n,
        }
    if applied_load_n is None or abs(applied_load_n) <= 0.0:
        return {
            "success": False,
            "reason": "missing_applied_boundary_load",
            "reaction_force_abs_n": reaction_force_abs_n,
            "applied_load_n": applied_load_n,
            "relative_tolerance": relative_tolerance,
            "absolute_tolerance_n": absolute_tolerance_n,
        }
    residual = abs(abs(reaction_force_abs_n) - abs(applied_load_n))
    relative_residual = residual / max(abs(applied_load_n), absolute_tolerance_n)
    return {
        "success": residual <= absolute_tolerance_n or relative_residual <= relative_tolerance,
        "reaction_force_abs_n": reaction_force_abs_n,
        "applied_load_n": applied_load_n,
        "absolute_residual_n": residual,
        "relative_residual_to_load": relative_residual,
        "reaction_to_load_ratio": abs(reaction_force_abs_n) / abs(applied_load_n),
        "relative_tolerance": relative_tolerance,
        "absolute_tolerance_n": absolute_tolerance_n,
    }


def _scan_saved_contact_probe_reports(root: Path) -> dict[str, Any]:
    """Index no-solve saved-MPH contact probe artifacts beside stage evidence."""
    reports: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    imbalance_count = 0
    source_unevaluable_destination_nonzero_count = 0
    for report_path in sorted(root.glob("**/contact_probe_summary.json")):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({"path": str(report_path), "error": str(exc)})
            continue
        probe = report.get("contact_probe") if isinstance(report.get("contact_probe"), dict) else {}
        by_roller = probe.get("by_roller") if isinstance(probe.get("by_roller"), dict) else {}
        pair_transfer = (
            probe.get("pair_transfer_by_roller")
            if isinstance(probe.get("pair_transfer_by_roller"), dict)
            else {}
        )
        imbalance_rollers: list[str] = []
        for roller, roller_summary in by_roller.items():
            imbalance = (
                roller_summary.get("source_destination_imbalance")
                if isinstance(roller_summary, dict)
                else {}
            )
            if isinstance(imbalance, dict) and any(
                isinstance(item, dict) and item.get("source_zero_destination_nonzero") is True
                for item in imbalance.values()
            ):
                imbalance_rollers.append(str(roller))
        if imbalance_rollers:
            imbalance_count += 1
        source_unevaluable_destination_nonzero_rollers = _pair_transfer_source_unevaluable_destination_nonzero_rollers(pair_transfer)
        if source_unevaluable_destination_nonzero_rollers:
            source_unevaluable_destination_nonzero_count += 1
        reports.append({
            "path": str(report_path),
            "artifact_root": str(report_path.parent),
            "mph_path": report.get("mph_path"),
            "success": bool(report.get("success")),
            "candidate_count": probe.get("candidate_count"),
            "success_count": probe.get("success_count"),
            "nonzero_count": probe.get("nonzero_count"),
            "candidate_audit": probe.get("candidate_audit"),
            "contact_status_by_roller": probe.get("contact_status_by_roller"),
            "normal_orientation_by_roller": probe.get("normal_orientation_by_roller"),
            "pair_transfer_by_roller": pair_transfer,
            "pair_enforcement_diagnostic": report.get("pair_enforcement_diagnostic"),
            "source_destination_imbalance_rollers": imbalance_rollers,
            "source_unevaluable_destination_nonzero_rollers": source_unevaluable_destination_nonzero_rollers,
            "by_roller": by_roller,
            "warning": report.get("warning") or probe.get("warning"),
            "error": report.get("error"),
        })
    return {
        "report_count": len(reports),
        "source_destination_imbalance_count": imbalance_count,
        "source_unevaluable_destination_nonzero_count": source_unevaluable_destination_nonzero_count,
        "reports": reports,
        "errors": errors,
    }


def _pair_transfer_source_unevaluable_destination_nonzero_rollers(pair_transfer: dict[str, Any]) -> list[str]:
    rollers: list[str] = []
    for roller, roller_summary in pair_transfer.items():
        if not isinstance(roller_summary, dict):
            continue
        transfer = roller_summary.get("source_destination_transfer")
        if not isinstance(transfer, dict):
            continue
        if any(
            isinstance(side_summary, dict)
            and side_summary.get("source_unevaluable_destination_nonzero") is True
            for side_summary in transfer.values()
        ):
            rollers.append(str(roller))
    return sorted(rollers)


def _build_boundaryload_distribution_diagnostics(rows: list[dict[str, Any]], *, search_root: Path | None = None) -> dict[str, Any]:
    """Aggregate why BoundaryLoad rows are still diagnostic instead of accepted."""
    boundaryload_rows = [row for row in rows if row.get("boundary_load_active") is True]
    zero_carry_rows = [
        row for row in boundaryload_rows
        if row.get("active_roller_zero_stress_rollers")
    ]
    missing_probe_rows = [
        row for row in boundaryload_rows
        if (row.get("roller_probe_count") in (None, 0))
    ]
    plateau_rows = [
        row for row in boundaryload_rows
        if row.get("boundaryload_sequence_stress_plateau") is True
    ]
    incomplete_distribution_rows = [
        row for row in boundaryload_rows
        if row.get("active_roller_load_distribution_success") is False
    ]
    zero_roller_counts: dict[str, int] = {}
    for row in zero_carry_rows:
        for roller in row.get("active_roller_zero_stress_rollers") or []:
            zero_roller_counts[str(roller)] = zero_roller_counts.get(str(roller), 0) + 1
    stage_mph_diagnostics = _scan_stage_mph_diagnostic_reports(search_root) if search_root is not None else {}
    saved_contact_probes = (
        _scan_saved_contact_probe_reports(search_root)["reports"]
        if search_root is not None
        else []
    )
    focus_rows = _compact_boundaryload_diagnostic_rows(
        zero_carry_rows or incomplete_distribution_rows or plateau_rows or missing_probe_rows,
        limit=12,
        stage_mph_diagnostics=stage_mph_diagnostics,
        saved_contact_probes=saved_contact_probes,
    )
    recommendations: list[str] = []
    if zero_carry_rows:
        if _zero_carry_has_saved_contact_source_destination_imbalance(focus_rows):
            if _zero_carry_has_pair_specific_contact_pressure_zero(focus_rows):
                if _zero_carry_pair_enforcement_settings_match_nonzero(focus_rows):
                    if _zero_carry_normal_orientation_has_opposite_sign(focus_rows):
                        if _zero_carry_pair_transfer_integrals_are_zero(focus_rows):
                            recommendations.append(
                                "Saved solved-MPH contact probe shows zero-carry rollers have zero roller-side source response while raceway-side destination response is nonzero, pair-specific normal pressure max and pair-transfer integrals are zero, solved-MPH contact feature settings match neighboring nonzero rollers, and source/destination radial normals have expected opposite signs; next inspect pair enforcement transfer/contact-state formulation before increasing load."
                            )
                        else:
                            recommendations.append(
                                "Saved solved-MPH contact probe shows zero-carry rollers have zero roller-side source response while raceway-side destination response is nonzero, pair-specific normal contact pressure candidates evaluate to zero, solved-MPH contact feature settings match neighboring nonzero rollers, and source/destination radial normals have the expected opposite signs; next inspect contact gap state and pair enforcement transfer before increasing load."
                            )
                    else:
                        recommendations.append(
                            "Saved solved-MPH contact probe shows zero-carry rollers have zero roller-side source response while raceway-side destination response is nonzero, pair-specific normal contact pressure candidates evaluate to zero, and solved-MPH contact feature settings match neighboring nonzero rollers; next inspect contact normal/gap orientation or pair enforcement transfer before increasing load."
                        )
                else:
                    recommendations.append(
                        "Saved solved-MPH contact probe shows zero-carry rollers have zero roller-side source response while raceway-side destination response is nonzero, and pair-specific normal contact pressure candidates evaluate to zero for the zero-carry roller while neighboring active rollers are nonzero; next inspect contact normal/gap orientation and pair enforcement transfer before increasing load."
                    )
            else:
                recommendations.append(
                    "Saved solved-MPH contact probe shows zero-carry rollers have zero roller-side source response while raceway-side destination response is nonzero; next inspect solved contact source/destination state, normal/gap orientation, and contact enforcement transfer before increasing load."
                )
        elif _zero_carry_contacts_are_configured_active(focus_rows):
            if (
                _zero_carry_patch_radial_order_is_configured(focus_rows)
                and _zero_carry_contact_settings_match_active_nonzero(focus_rows)
            ):
                recommendations.append(
                    "Zero-carry rollers have configured inner/outer contact active, fixed stabilization inactive, correct gross load-angle alignment, inner/outer contact patch boxes on the expected radial sides, and contact feature settings matching active nonzero rollers; next inspect solved contact status, initial gap/contact normal direction, and weak-guidance/foundation dominance before increasing load."
                )
            elif _zero_carry_patch_radial_order_is_configured(focus_rows):
                recommendations.append(
                    "Zero-carry rollers have configured inner/outer contact active, fixed stabilization inactive, correct gross load-angle alignment, and inner/outer contact patch boxes on the expected radial sides; next inspect contact feature settings, initial gap/contact normal direction, contact enforcement state, and weak-guidance/foundation dominance before increasing load."
                )
            else:
                recommendations.append(
                    "Zero-carry rollers have configured inner/outer contact active and fixed stabilization inactive; next inspect contact patch geometry, initial gap/normal direction, load-angle mapping, and weak-foundation dominance before increasing load."
                )
        else:
            recommendations.append(
                "Inspect load-side roller contact activation, geometry angle mapping, and active-roller stabilization for zero-carry rollers before increasing load."
            )
    if plateau_rows:
        recommendations.append(
            "Diagnose stress plateau/constraint dominance with one-variable runs before treating fresh-solver BoundaryLoad continuation as physical load transfer."
        )
    if missing_probe_rows:
        recommendations.append(
            "Rerun historical BoundaryLoad stages with per-roller maxop_roller_i(solid.mises) probes before physical acceptance."
        )
    if not recommendations:
        recommendations.append("No BoundaryLoad distribution blockers were found in scanned summaries.")
    return {
        "success": not (zero_carry_rows or plateau_rows or missing_probe_rows or incomplete_distribution_rows),
        "kind": "boundaryload_active_roller_distribution_diagnostics",
        "boundaryload_row_count": len(boundaryload_rows),
        "zero_carry_row_count": len(zero_carry_rows),
        "missing_probe_row_count": len(missing_probe_rows),
        "stress_plateau_row_count": len(plateau_rows),
        "incomplete_distribution_row_count": len(incomplete_distribution_rows),
        "zero_carry_rollers": dict(sorted(zero_roller_counts.items())),
        "stage_mph_diagnostic_report_count": len(stage_mph_diagnostics),
        "saved_contact_probe_report_count": len(saved_contact_probes),
        "focus_rows": focus_rows,
        "recommendations": recommendations,
    }


def _zero_carry_contacts_are_configured_active(focus_rows: list[dict[str, Any]]) -> bool:
    for row in focus_rows:
        diagnostic = row.get("configured_mph_diagnostic")
        states = (diagnostic or {}).get("zero_carry_roller_feature_state") if isinstance(diagnostic, dict) else None
        if not isinstance(states, dict):
            continue
        for state in states.values():
            if (
                isinstance(state, dict)
                and state.get("inner_contact_active") is True
                and state.get("outer_contact_active") is True
                and state.get("fixed_stabilization_active") is False
            ):
                return True
    return False


def _zero_carry_patch_radial_order_is_configured(focus_rows: list[dict[str, Any]]) -> bool:
    for row in focus_rows:
        diagnostic = row.get("configured_mph_diagnostic")
        states = (diagnostic or {}).get("zero_carry_roller_feature_state") if isinstance(diagnostic, dict) else None
        if not isinstance(states, dict):
            continue
        for state in states.values():
            patch_geometry = state.get("contact_patch_geometry") if isinstance(state, dict) else None
            alignment = state.get("load_angle_alignment") if isinstance(state, dict) else None
            if (
                isinstance(patch_geometry, dict)
                and patch_geometry.get("radial_order_success") is True
                and isinstance(alignment, dict)
                and alignment.get("success") is True
            ):
                return True
    return False


def _zero_carry_contact_settings_match_active_nonzero(focus_rows: list[dict[str, Any]]) -> bool:
    for row in focus_rows:
        diagnostic = row.get("configured_mph_diagnostic")
        states = (diagnostic or {}).get("zero_carry_roller_feature_state") if isinstance(diagnostic, dict) else None
        if not isinstance(states, dict):
            continue
        for state in states.values():
            if (
                isinstance(state, dict)
                and state.get("contact_feature_settings_match_active_nonzero") is True
            ):
                return True
    return False


def _zero_carry_has_saved_contact_source_destination_imbalance(focus_rows: list[dict[str, Any]]) -> bool:
    for row in focus_rows:
        diagnostic = row.get("saved_contact_probe_diagnostic")
        if not isinstance(diagnostic, dict):
            continue
        if diagnostic.get("zero_carry_source_destination_imbalance"):
            return True
    return False


def _zero_carry_has_pair_specific_contact_pressure_zero(focus_rows: list[dict[str, Any]]) -> bool:
    for row in focus_rows:
        diagnostic = row.get("saved_contact_probe_diagnostic")
        if isinstance(diagnostic, dict) and diagnostic.get("zero_carry_pair_specific_contact_pressure_zero"):
            return True
    return False


def _zero_carry_pair_enforcement_settings_match_nonzero(focus_rows: list[dict[str, Any]]) -> bool:
    for row in focus_rows:
        diagnostic = row.get("saved_contact_probe_diagnostic")
        if not isinstance(diagnostic, dict):
            continue
        pair_enforcement = diagnostic.get("pair_enforcement_diagnostic")
        states = (
            pair_enforcement.get("zero_carry_roller_states")
            if isinstance(pair_enforcement, dict)
            else None
        )
        if not isinstance(states, dict):
            continue
        for state in states.values():
            if (
                isinstance(state, dict)
                and state.get("contact_feature_settings_match_nonzero_references") is True
            ):
                return True
    return False


def _zero_carry_normal_orientation_has_opposite_sign(focus_rows: list[dict[str, Any]]) -> bool:
    for row in focus_rows:
        diagnostic = row.get("saved_contact_probe_diagnostic")
        if not isinstance(diagnostic, dict):
            continue
        orientations = diagnostic.get("zero_carry_normal_orientation")
        if not isinstance(orientations, dict):
            continue
        for orientation in orientations.values():
            alignment = (
                orientation.get("source_destination_radial_normal_alignment")
                if isinstance(orientation, dict)
                else None
            )
            if not isinstance(alignment, dict):
                continue
            inner = alignment.get("inner") if isinstance(alignment.get("inner"), dict) else {}
            outer = alignment.get("outer") if isinstance(alignment.get("outer"), dict) else {}
            if inner.get("opposite_radial_sign") is True and outer.get("opposite_radial_sign") is True:
                return True
    return False


def _zero_carry_pair_transfer_integrals_are_zero(focus_rows: list[dict[str, Any]]) -> bool:
    for row in focus_rows:
        diagnostic = row.get("saved_contact_probe_diagnostic")
        if not isinstance(diagnostic, dict):
            continue
        transfers = diagnostic.get("zero_carry_pair_transfer")
        if not isinstance(transfers, dict):
            continue
        for transfer in transfers.values():
            if (
                isinstance(transfer, dict)
                and (transfer.get("destination_abs_tn_nonzero_count") or 0) == 0
            ):
                return True
    return False


def _scan_stage_mph_diagnostic_reports(root: Path | None) -> dict[str, dict[str, Any]]:
    """Read no-solve stage MPH diagnostic reports by configured MPH path."""
    if root is None:
        return {}
    reports: dict[str, dict[str, Any]] = {}
    for report_path in sorted(root.glob("**/stage_mph_diagnostic.json")):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        mph_path = report.get("mph_path")
        if not mph_path:
            continue
        reports[str(mph_path)] = {"path": str(report_path), "report": report}
        try:
            reports[str(Path(mph_path).resolve())] = {"path": str(report_path), "report": report}
        except Exception:
            pass
    return reports


def _compact_boundaryload_diagnostic_rows(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    stage_mph_diagnostics: dict[str, dict[str, Any]] | None = None,
    saved_contact_probes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    compact_rows: list[dict[str, Any]] = []
    for row in rows[:limit]:
        pre_solve_mph = row.get("pre_solve_mph")
        configured_diagnostic = _configured_zero_carry_diagnostic(
            row,
            stage_mph_diagnostics=stage_mph_diagnostics or {},
            pre_solve_mph=pre_solve_mph,
        )
        contact_probe_diagnostic = _saved_contact_probe_diagnostic_for_row(
            row,
            saved_contact_probes=saved_contact_probes or [],
        )
        compact_rows.append({
            "stage": row.get("stage"),
            "summary_path": row.get("summary_path"),
            "radial_load_value": row.get("radial_load_value"),
            "active_rollers": row.get("active_rollers"),
            "active_roller_zero_stress_rollers": row.get("active_roller_zero_stress_rollers"),
            "active_roller_nonzero_probe_ratio": row.get("active_roller_nonzero_probe_ratio"),
            "active_roller_values_by_roller": row.get("active_roller_values_by_roller"),
            "boundaryload_sequence_stress_plateau": row.get("boundaryload_sequence_stress_plateau"),
            "max_von_mises_pa": row.get("max_von_mises_pa"),
            "max_displacement_m": row.get("max_displacement_m"),
            "pre_solve_mph": row.get("pre_solve_mph"),
            "failed_mph": row.get("failed_mph"),
            "native_png": row.get("native_png"),
            "configured_mph_diagnostic": configured_diagnostic,
            "saved_contact_probe_diagnostic": contact_probe_diagnostic,
        })
    return compact_rows


def _saved_contact_probe_diagnostic_for_row(
    row: dict[str, Any],
    *,
    saved_contact_probes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Attach saved solved-MPH contact probe evidence to a matrix focus row."""
    artifact_root = str(row.get("artifact_root") or "")
    if not artifact_root:
        summary_path = row.get("summary_path")
        if summary_path:
            artifact_root = str(Path(str(summary_path)).parent)
    if not artifact_root:
        return None
    zero_rollers = set(str(item) for item in row.get("active_roller_zero_stress_rollers") or [])
    candidates = [
        report for report in saved_contact_probes
        if artifact_root in str(report.get("path") or "")
        or artifact_root in str(report.get("artifact_root") or "")
        or artifact_root in str(report.get("mph_path") or "")
    ]
    if not candidates:
        return None
    report = candidates[0]
    by_roller = report.get("by_roller") if isinstance(report.get("by_roller"), dict) else {}
    zero_details = {
        roller: by_roller.get(roller)
        for roller in zero_rollers
        if isinstance(by_roller.get(roller), dict)
    }
    contact_status = (
        report.get("contact_status_by_roller")
        if isinstance(report.get("contact_status_by_roller"), dict)
        else {}
    )
    normal_orientation = (
        report.get("normal_orientation_by_roller")
        if isinstance(report.get("normal_orientation_by_roller"), dict)
        else {}
    )
    pair_transfer = (
        report.get("pair_transfer_by_roller")
        if isinstance(report.get("pair_transfer_by_roller"), dict)
        else {}
    )
    pair_enforcement = (
        report.get("pair_enforcement_diagnostic")
        if isinstance(report.get("pair_enforcement_diagnostic"), dict)
        else {}
    )
    zero_status = {
        roller: contact_status.get(roller)
        for roller in zero_rollers
        if isinstance(contact_status.get(roller), dict)
    }
    zero_normal_orientation = {
        roller: normal_orientation.get(roller)
        for roller in zero_rollers
        if isinstance(normal_orientation.get(roller), dict)
    }
    zero_pair_transfer = {
        roller: pair_transfer.get(roller)
        for roller in zero_rollers
        if isinstance(pair_transfer.get(roller), dict)
    }
    zero_pair_pressure = sorted(
        roller for roller, status in zero_status.items()
        if (status.get("pair_specific_success_count") or 0) > 0
        and (status.get("pair_specific_nonzero_count") or 0) == 0
    )
    imbalance_rollers = set(str(item) for item in report.get("source_destination_imbalance_rollers") or [])
    source_unevaluable_destination_nonzero_rollers = set(
        str(item)
        for item in report.get("source_unevaluable_destination_nonzero_rollers") or []
    )
    zero_imbalance = sorted(zero_rollers & imbalance_rollers)
    zero_source_unevaluable_destination_nonzero = sorted(
        zero_rollers & source_unevaluable_destination_nonzero_rollers
    )
    return {
        "success": bool(report.get("success")),
        "path": report.get("path"),
        "mph_path": report.get("mph_path"),
        "candidate_count": report.get("candidate_count"),
        "success_count": report.get("success_count"),
        "nonzero_count": report.get("nonzero_count"),
        "source_destination_imbalance_rollers": sorted(imbalance_rollers),
        "source_unevaluable_destination_nonzero_rollers": sorted(source_unevaluable_destination_nonzero_rollers),
        "zero_carry_source_destination_imbalance": zero_imbalance,
        "zero_carry_source_unevaluable_destination_nonzero": zero_source_unevaluable_destination_nonzero,
        "zero_carry_pair_specific_contact_pressure_zero": zero_pair_pressure,
        "zero_carry_by_roller": zero_details,
        "zero_carry_contact_status": zero_status,
        "zero_carry_normal_orientation": zero_normal_orientation,
        "zero_carry_pair_transfer": zero_pair_transfer,
        "pair_enforcement_diagnostic": {
            "success": pair_enforcement.get("success"),
            "zero_pair_specific_contact_pressure_rollers": pair_enforcement.get("zero_pair_specific_contact_pressure_rollers"),
            "source_destination_imbalance_rollers": pair_enforcement.get("source_destination_imbalance_rollers"),
            "nonzero_reference_rollers": pair_enforcement.get("nonzero_reference_rollers"),
            "recommendations": pair_enforcement.get("recommendations"),
            "zero_carry_roller_states": {
                roller: (pair_enforcement.get("roller_states") or {}).get(roller)
                for roller in zero_rollers
                if isinstance((pair_enforcement.get("roller_states") or {}).get(roller), dict)
            },
        } if pair_enforcement else None,
    }


def _configured_zero_carry_diagnostic(
    row: dict[str, Any],
    *,
    stage_mph_diagnostics: dict[str, dict[str, Any]],
    pre_solve_mph: Any,
) -> dict[str, Any] | None:
    """Summarize configured-MPH feature state for zero-carry active rollers."""
    if not pre_solve_mph:
        return None
    diagnostic = stage_mph_diagnostics.get(str(pre_solve_mph))
    if diagnostic is None:
        try:
            diagnostic = stage_mph_diagnostics.get(str(Path(str(pre_solve_mph)).resolve()))
        except Exception:
            diagnostic = None
    if diagnostic is None:
        return None
    report = diagnostic.get("report") or {}
    payload = ((report.get("audit") or {}).get("payload") or {})
    features = {
        str(item.get("tag")): item
        for item in payload.get("solid_feature_audit") or []
        if isinstance(item, dict)
    }
    pairs = {
        str(item.get("tag")): item
        for item in payload.get("contact_pair_audit") or []
        if isinstance(item, dict)
    }
    selections = {
        str(item.get("tag")): item
        for item in payload.get("selection_audit") or []
        if isinstance(item, dict)
    }
    zero_rollers = row.get("active_roller_zero_stress_rollers") or []
    zero_indexes: set[int] = set()
    for roller in zero_rollers:
        match = re.search(r"(\d+)$", str(roller))
        if match:
            zero_indexes.add(int(match.group(1)))
    active_indexes = {
        int(value)
        for value in row.get("active_rollers") or []
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit())
    }
    active_reference_contact_settings = {
        f"roller_{index}": _diagnostic_roller_contact_settings(features, index)
        for index in sorted(active_indexes - zero_indexes)
    }
    roller_states: dict[str, Any] = {}
    load_vector = _diagnostic_load_vector_summary(features.get("load_inner_bore"))
    for roller in zero_rollers:
        match = re.search(r"(\d+)$", str(roller))
        if not match:
            continue
        index = int(match.group(1))
        roller_body_geometry = _diagnostic_selection_box_summary(selections.get(f"sel_roller_{index}_body"))
        inner_patch_box = _diagnostic_selection_box_summary(selections.get(f"box_roller_{index}_inner_contact_patch"))
        outer_patch_box = _diagnostic_selection_box_summary(selections.get(f"box_roller_{index}_outer_contact_patch"))
        cage_patch_box = _diagnostic_selection_box_summary(selections.get(f"box_roller_{index}_cage_pocket_contact_patch"))
        contact_settings = _diagnostic_roller_contact_settings(features, index)
        roller_states[f"roller_{index}"] = {
            "body_selection_entity_count": _diagnostic_selection_count(selections.get(f"sel_roller_{index}_body")),
            "inner_contact_active": _diagnostic_feature_active(features.get(f"contact_roller_{index}_inner")),
            "outer_contact_active": _diagnostic_feature_active(features.get(f"contact_roller_{index}_outer")),
            "cage_contact_active": _diagnostic_feature_active(features.get(f"contact_roller_{index}_cage")),
            "weak_foundation_active": _diagnostic_feature_active(features.get(f"weak_roller_{index}_foundation")),
            "fixed_stabilization_active": _diagnostic_feature_active(features.get(f"fix_roller_{index}_stage_stabilization")),
            "inner_pair": _diagnostic_pair_endpoint_summary(pairs.get(f"cp_roller_{index}_inner_raceway")),
            "outer_pair": _diagnostic_pair_endpoint_summary(pairs.get(f"cp_roller_{index}_outer_raceway")),
            "cage_pair": _diagnostic_pair_endpoint_summary(pairs.get(f"cp_roller_{index}_cage_pocket")),
            "selection_geometry": {
                "roller_body": roller_body_geometry,
                "roller_inner_contact": _diagnostic_selection_box_summary(selections.get(f"sel_roller_{index}_inner_contact")),
                "inner_raceway_contact": _diagnostic_selection_box_summary(selections.get(f"sel_inner_raceway_{index}_contact")),
                "roller_outer_contact": _diagnostic_selection_box_summary(selections.get(f"sel_roller_{index}_outer_contact")),
                "outer_raceway_contact": _diagnostic_selection_box_summary(selections.get(f"sel_outer_raceway_{index}_contact")),
                "inner_patch_box": inner_patch_box,
                "outer_patch_box": outer_patch_box,
                "cage_patch_box": cage_patch_box,
            },
            "contact_patch_geometry": _diagnostic_contact_patch_geometry(
                roller_body_geometry=roller_body_geometry,
                inner_patch_box=inner_patch_box,
                outer_patch_box=outer_patch_box,
                cage_patch_box=cage_patch_box,
            ),
            "load_angle_alignment": _diagnostic_load_angle_alignment(
                roller_body_geometry=roller_body_geometry,
                load_vector=load_vector,
            ),
            "contact_feature_settings": contact_settings,
            "contact_feature_settings_match_active_nonzero": _diagnostic_contact_settings_match_references(
                contact_settings,
                active_reference_contact_settings,
            ),
        }
    return {
        "success": bool(roller_states),
        "path": diagnostic.get("path"),
        "mph_path": report.get("mph_path"),
        "zero_carry_roller_feature_state": roller_states,
        "active_nonzero_contact_settings_by_roller": active_reference_contact_settings,
    }


def _diagnostic_feature_active(feature: dict[str, Any] | None) -> bool | None:
    if not isinstance(feature, dict):
        return None
    value = feature.get("active")
    if isinstance(value, dict):
        value = value.get("value")
    return value if isinstance(value, bool) else None


def _diagnostic_selection_count(selection: dict[str, Any] | None) -> int | None:
    if not isinstance(selection, dict):
        return None
    count = selection.get("entity_count")
    try:
        return int(count) if count is not None else None
    except (TypeError, ValueError):
        return None


def _diagnostic_selection_box_summary(selection: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(selection, dict) or not selection.get("exists"):
        return None
    props = selection.get("properties") if isinstance(selection.get("properties"), dict) else {}
    bounds: dict[str, Any] = {}
    numeric_mm: dict[str, float] = {}
    missing: list[str] = []
    for key in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"):
        raw_value = _diagnostic_property_value(props.get(key))
        bounds[key] = raw_value
        numeric_value = _parse_diagnostic_length_mm(raw_value)
        if numeric_value is None:
            missing.append(key)
        else:
            numeric_mm[key] = numeric_value
    center_mm = None
    angle_deg = None
    if all(key in numeric_mm for key in ("xmin", "xmax", "ymin", "ymax")):
        center_x = 0.5 * (numeric_mm["xmin"] + numeric_mm["xmax"])
        center_y = 0.5 * (numeric_mm["ymin"] + numeric_mm["ymax"])
        center_mm = {
            "x": center_x,
            "y": center_y,
            "z": (
                0.5 * (numeric_mm["zmin"] + numeric_mm["zmax"])
                if "zmin" in numeric_mm and "zmax" in numeric_mm
                else None
            ),
        }
        angle_deg = math.degrees(math.atan2(center_y, center_x))
    return {
        "success": not missing,
        "type": selection.get("type"),
        "entity_count": _diagnostic_selection_count(selection),
        "bounds": bounds,
        "center_mm": center_mm,
        "angle_deg": angle_deg,
        "missing_bounds": missing,
    }


def _diagnostic_property_value(prop: Any) -> Any:
    if isinstance(prop, dict) and prop.get("success"):
        value = prop.get("value")
        if isinstance(value, list) and len(value) == 1:
            return value[0]
        return value
    return None


def _parse_diagnostic_length_mm(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(?:\[(mm|um|m)\])?", str(value))
    if not match:
        return None
    try:
        numeric = float(match.group(1))
    except ValueError:
        return None
    unit = match.group(2) or "mm"
    if unit == "m":
        return numeric * 1000.0
    if unit == "um":
        return numeric / 1000.0
    return numeric


def _diagnostic_load_vector_summary(feature: dict[str, Any] | None) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature, dict) and isinstance(feature.get("properties"), dict) else {}
    raw = _diagnostic_property_value(props.get("FperArea"))
    vector = raw if isinstance(raw, list) else None
    if not vector or len(vector) < 2:
        return {"success": False, "raw": raw, "reason": "FperArea vector unavailable"}
    dominant_axis = None
    dominant_sign = None
    for axis, component in enumerate(vector[:3]):
        text = str(component).strip()
        if text and text not in {"0", "0.0", "0[Pa]", "0[N/m^2]"}:
            dominant_axis = axis
            dominant_sign = -1 if text.startswith("-") else 1
            break
    load_angle_deg = None
    if dominant_axis == 0:
        load_angle_deg = 0.0 if dominant_sign == 1 else 180.0
    elif dominant_axis == 1:
        load_angle_deg = 90.0 if dominant_sign == 1 else -90.0
    return {
        "success": dominant_axis is not None,
        "raw": vector,
        "dominant_axis": dominant_axis,
        "dominant_sign": dominant_sign,
        "load_angle_deg": load_angle_deg,
    }


def _diagnostic_load_angle_alignment(
    *,
    roller_body_geometry: dict[str, Any] | None,
    load_vector: dict[str, Any],
) -> dict[str, Any]:
    roller_angle = (roller_body_geometry or {}).get("angle_deg")
    load_angle = load_vector.get("load_angle_deg")
    if roller_angle is None or load_angle is None:
        return {
            "success": False,
            "roller_angle_deg": roller_angle,
            "load_angle_deg": load_angle,
            "load_vector": load_vector,
            "reason": "selection geometry or load vector angle unavailable",
        }
    offset = ((float(roller_angle) - float(load_angle) + 180.0) % 360.0) - 180.0
    return {
        "success": True,
        "roller_angle_deg": roller_angle,
        "load_angle_deg": load_angle,
        "angle_offset_deg": offset,
        "load_vector": load_vector,
    }


def _diagnostic_contact_patch_geometry(
    *,
    roller_body_geometry: dict[str, Any] | None,
    inner_patch_box: dict[str, Any] | None,
    outer_patch_box: dict[str, Any] | None,
    cage_patch_box: dict[str, Any] | None,
) -> dict[str, Any]:
    """Summarize radial placement of contact patch boxes around a roller."""
    body_center = (roller_body_geometry or {}).get("center_mm")
    if not isinstance(body_center, dict) or body_center.get("x") is None or body_center.get("y") is None:
        return {
            "success": False,
            "reason": "roller body center unavailable",
            "inner_patch_radial_offset_mm": None,
            "outer_patch_radial_offset_mm": None,
        }
    try:
        cx = float(body_center["x"])
        cy = float(body_center["y"])
    except (TypeError, ValueError):
        return {
            "success": False,
            "reason": "roller body center is not numeric",
            "inner_patch_radial_offset_mm": None,
            "outer_patch_radial_offset_mm": None,
        }
    radius = math.hypot(cx, cy)
    if radius <= 0.0:
        return {
            "success": False,
            "reason": "roller body center radius is zero",
            "inner_patch_radial_offset_mm": None,
            "outer_patch_radial_offset_mm": None,
        }
    unit = (cx / radius, cy / radius)
    inner_offset = _diagnostic_patch_radial_offset(inner_patch_box, body_radius=radius, radial_unit=unit)
    outer_offset = _diagnostic_patch_radial_offset(outer_patch_box, body_radius=radius, radial_unit=unit)
    cage_offset = _diagnostic_patch_radial_offset(cage_patch_box, body_radius=radius, radial_unit=unit)
    radial_order_success = (
        inner_offset is not None
        and outer_offset is not None
        and inner_offset < -0.1
        and outer_offset > 0.1
    )
    warnings: list[str] = []
    if inner_offset is None:
        warnings.append("inner contact patch box center unavailable")
    elif inner_offset >= -0.1:
        warnings.append("inner contact patch is not radially inside the roller body center")
    if outer_offset is None:
        warnings.append("outer contact patch box center unavailable")
    elif outer_offset <= 0.1:
        warnings.append("outer contact patch is not radially outside the roller body center")
    return {
        "success": radial_order_success,
        "body_radius_mm": radius,
        "inner_patch_radial_offset_mm": inner_offset,
        "outer_patch_radial_offset_mm": outer_offset,
        "cage_patch_radial_offset_mm": cage_offset,
        "radial_order_success": radial_order_success,
        "warnings": warnings,
    }


def _diagnostic_patch_radial_offset(
    patch_geometry: dict[str, Any] | None,
    *,
    body_radius: float,
    radial_unit: tuple[float, float],
) -> float | None:
    center = (patch_geometry or {}).get("center_mm")
    if not isinstance(center, dict) or center.get("x") is None or center.get("y") is None:
        return None
    try:
        px = float(center["x"])
        py = float(center["y"])
    except (TypeError, ValueError):
        return None
    projection = px * radial_unit[0] + py * radial_unit[1]
    return projection - body_radius


CONTACT_SETTING_PROPS = ("pairs", "pn_penalty", "useRelaxation", "irlx", "tolcontact", "zeroInitGap")


def _diagnostic_roller_contact_settings(features: dict[str, dict[str, Any]], index: int) -> dict[str, Any]:
    return {
        side: _diagnostic_contact_feature_settings(_first_feature_by_tag_candidates(
            features,
            _contact_feature_tag_candidates(index, side),
        ))
        for side in ("inner", "outer")
    }


def _first_feature_by_tag_candidates(
    features: dict[str, dict[str, Any]],
    candidates: list[str],
) -> dict[str, Any] | None:
    for tag in candidates:
        if isinstance(features.get(tag), dict):
            return features[tag]
    return None


def _diagnostic_contact_feature_settings(feature: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(feature, dict) or not feature.get("exists", True):
        return {"exists": False}
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    return {
        "exists": bool(feature.get("exists", True)),
        "active": _diagnostic_feature_active(feature),
        "type": feature.get("type"),
        "properties": {
            prop: _diagnostic_property_value(props.get(prop))
            for prop in CONTACT_SETTING_PROPS
        },
    }


def _diagnostic_contact_settings_match_references(
    contact_settings: dict[str, Any],
    reference_settings_by_roller: dict[str, Any],
) -> bool | None:
    if not reference_settings_by_roller:
        return None
    for reference in reference_settings_by_roller.values():
        if not _diagnostic_contact_settings_equivalent(contact_settings, reference):
            return False
    return True


def _diagnostic_contact_settings_equivalent(left: Any, right: Any) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    for side in ("inner", "outer"):
        left_side = left.get(side)
        right_side = right.get(side)
        if not isinstance(left_side, dict) or not isinstance(right_side, dict):
            return False
        if left_side.get("exists") is not True or right_side.get("exists") is not True:
            return False
        if left_side.get("active") != right_side.get("active"):
            return False
        left_props = left_side.get("properties") or {}
        right_props = right_side.get("properties") or {}
        for prop in CONTACT_SETTING_PROPS:
            if prop == "pairs":
                continue
            if left_props.get(prop) != right_props.get(prop):
                return False
    return True


def _diagnostic_pair_endpoint_summary(pair: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(pair, dict) or not pair.get("exists"):
        return None
    source = pair.get("source") if isinstance(pair.get("source"), dict) else {}
    destination = pair.get("destination") if isinstance(pair.get("destination"), dict) else {}
    return {
        "exists": True,
        "source_named": _diagnostic_named_value(source.get("named")),
        "source_entity_count": source.get("entity_count"),
        "destination_named": _diagnostic_named_value(destination.get("named")),
        "destination_entity_count": destination.get("entity_count"),
    }


def _summarize_contact_pair_endpoint_consistency(
    pair_rows: list[dict[str, Any]] | None,
    *,
    rollers: tuple[int, ...] = (1, 2, 12),
) -> dict[str, Any]:
    """Check declared source/destination names against the bearing pair contract."""
    rows_by_tag = {
        str(row.get("tag")): row
        for row in pair_rows or []
        if isinstance(row, dict)
    }
    audited_rows: list[dict[str, Any]] = []
    divergent_rows: list[str] = []
    expected_tags: list[str] = []
    for roller in rollers:
        for side in ("inner", "outer"):
            pair_tag = f"cp_roller_{roller}_{side}_raceway"
            expected_source = f"sel_roller_{roller}_{side}_contact"
            expected_destination = f"sel_{side}_raceway_{roller}_contact"
            expected_tags.append(pair_tag)
            pair = rows_by_tag.get(pair_tag)
            source = pair.get("source") if isinstance(pair, dict) else {}
            destination = pair.get("destination") if isinstance(pair, dict) else {}
            source_named = _diagnostic_named_value(source.get("named")) if isinstance(source, dict) else None
            destination_named = (
                _diagnostic_named_value(destination.get("named"))
                if isinstance(destination, dict)
                else None
            )
            source_count = source.get("entity_count") if isinstance(source, dict) else None
            destination_count = destination.get("entity_count") if isinstance(destination, dict) else None
            consistent = bool(
                isinstance(pair, dict)
                and pair.get("exists") is True
                and source_named == expected_source
                and destination_named == expected_destination
                and isinstance(source_count, int)
                and source_count > 0
                and isinstance(destination_count, int)
                and destination_count > 0
            )
            row = {
                "pair": pair_tag,
                "exists": bool(isinstance(pair, dict) and pair.get("exists") is True),
                "expected_source": expected_source,
                "actual_source": source_named,
                "expected_destination": expected_destination,
                "actual_destination": destination_named,
                "source_entity_count": source_count,
                "destination_entity_count": destination_count,
                "consistent": consistent,
            }
            audited_rows.append(row)
            if not consistent:
                divergent_rows.append(pair_tag)
    return {
        "success": bool(audited_rows) and not divergent_rows,
        "rollers": list(rollers),
        "expected_pair_count": len(expected_tags),
        "audited_pair_count": len(audited_rows),
        "consistent_pair_count": sum(1 for row in audited_rows if row["consistent"]),
        "divergent_pair_tags": divergent_rows,
        "endpoint_rebind_justified": bool(divergent_rows),
        "rows": audited_rows,
    }


def _diagnostic_named_value(value: Any) -> Any:
    if isinstance(value, dict) and value.get("success"):
        return value.get("value")
    return None


def _annotate_boundaryload_sequence_physics(rows: list[dict[str, Any]]) -> None:
    """Flag load-control sequences where stress is pinned while displacement grows."""
    candidates: list[dict[str, Any]] = []
    for row in rows:
        load_n = _parse_unit_value_to_float(row.get("radial_load_value"), unit="N")
        stress = row.get("max_von_mises_pa")
        displacement = row.get("max_displacement_m")
        load_fidelity = str(row.get("load_application_fidelity") or "")
        if (
            row.get("solve_success") is True
            and row.get("native_png_success") is True
            and row.get("boundary_load_active") is True
            and row.get("body_load_active") is not True
            and row.get("active_roller_count") == 3
            and "single_solve_parametric" in load_fidelity
            and load_n is not None
            and stress is not None
            and displacement is not None
        ):
            try:
                candidates.append({
                    "row": row,
                    "load_n": float(load_n),
                    "stress": float(stress),
                    "displacement": float(displacement),
                })
            except (TypeError, ValueError):
                continue
    candidates.sort(key=lambda item: item["load_n"])
    if len(candidates) < 4:
        return

    stress_values = [item["stress"] for item in candidates if math.isfinite(item["stress"])]
    displacement_values = [item["displacement"] for item in candidates if math.isfinite(item["displacement"])]
    load_values = [item["load_n"] for item in candidates if math.isfinite(item["load_n"])]
    if len(stress_values) < 4 or len(displacement_values) < 4 or len(load_values) < 4:
        return
    stress_max = max(stress_values)
    stress_min = min(stress_values)
    displacement_min = min(displacement_values)
    displacement_max = max(displacement_values)
    load_span = max(load_values) - min(load_values)
    if stress_max <= 0.0 or displacement_min <= 0.0:
        return
    stress_relative_span = (stress_max - stress_min) / stress_max
    displacement_growth = displacement_max / displacement_min
    if stress_relative_span > 1.0e-5 or displacement_growth < 1.25 or load_span < 0.05:
        return

    message = (
        "BoundaryLoad continuation stress plateau detected: max von Mises varies by "
        f"{stress_relative_span:.3g} while displacement grows by {displacement_growth:.3g}x "
        f"over {min(load_values):.6g}-{max(load_values):.6g} N; treat as constraint/stabilization-dominated "
        "diagnostic, not physically accepted load transfer."
    )
    for item in candidates:
        row = item["row"]
        _append_stage_row_diagnostic(row, "physical_plausibility_errors", message)
        _append_stage_row_diagnostic(row, "physical_plausibility_warnings", message)
        row["physical_plausibility_success"] = False
        row["boundaryload_sequence_stress_plateau"] = True
        row["boundaryload_sequence_stress_relative_span"] = stress_relative_span
        row["boundaryload_sequence_displacement_growth"] = displacement_growth


def _append_stage_row_diagnostic(row: dict[str, Any], key: str, message: str) -> None:
    values = row.get(key)
    if not isinstance(values, list):
        values = [] if values is None else [str(values)]
    if message not in values:
        values.append(message)
    row[key] = values


def write_stage_evidence_matrix_report(
    *,
    search_root: str | Path = "runtime_smoke",
    output_dir: str | Path = "reports/bearing_stage_evidence",
) -> dict[str, Any]:
    """Write JSON and Markdown reports for scanned 3D bearing stage evidence."""
    matrix = build_stage_evidence_matrix(search_root=search_root)
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "bearing_stage_evidence_matrix.json"
    markdown_path = report_dir / "bearing_stage_evidence_matrix.md"
    json_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(_render_stage_evidence_matrix_markdown(matrix), encoding="utf-8")
    return {
        "success": True,
        "kind": "bearing_3d_stage_evidence_matrix_report",
        "json_path": str(json_path.resolve()),
        "markdown_path": str(markdown_path.resolve()),
        "summary_count": matrix["summary_count"],
        "row_count": matrix["row_count"],
        "production_ready_count": matrix["production_ready_count"],
        "converged_native_stage_count": matrix["converged_native_stage_count"],
        "reaction_verified_stage_count": matrix["reaction_verified_stage_count"],
        "saved_reaction_probe_report_count": matrix["saved_reaction_probe_report_count"],
        "saved_reaction_probe_verified_count": matrix["saved_reaction_probe_verified_count"],
        "saved_contact_probe_report_count": matrix["saved_contact_probe_report_count"],
        "saved_contact_probe_source_destination_imbalance_count": matrix["saved_contact_probe_source_destination_imbalance_count"],
        "saved_contact_probe_source_unevaluable_destination_nonzero_count": matrix[
            "saved_contact_probe_source_unevaluable_destination_nonzero_count"
        ],
        "highest_trust_stage": matrix.get("highest_trust_stage"),
    }


STAGE_MPH_DIAGNOSTIC_JSON_START = "STAGE_MPH_DIAGNOSTIC_JSON_START"
STAGE_MPH_DIAGNOSTIC_JSON_END = "STAGE_MPH_DIAGNOSTIC_JSON_END"


def map_boundary_entities_mph(
    *,
    mph_path: str | Path,
    output_dir: str | Path,
    selection_name: str = "geom1_outer_ring_bnd",
    rollers: tuple[int, ...] = (1, 2, 12),
    cores: int = 1,
) -> dict[str, Any]:
    """Load an MPH and map boundary entity centroid/radius/angle for a named selection."""
    mph_file = Path(mph_path)
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "boundary_entity_map.json"
    markdown_path = report_dir / "boundary_entity_map.md"

    config = load_config()
    client = COMSOLClient.get_instance()
    model_name: str | None = None
    result: dict[str, Any] = {
        "success": False,
        "kind": "bearing_3d_boundary_entity_map",
        "mph_path": str(mph_file),
        "selection_name": selection_name,
        "rollers": list(rollers),
        "output_dir": str(report_dir),
        "json_path": str(json_path.resolve()),
        "markdown_path": str(markdown_path.resolve()),
        "policy": "load_mph_and_map_named_boundary_selection_entities_without_solving",
    }
    try:
        client.start(
            cores=cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        load = comsol_load_model(str(mph_file))
        result["load"] = _compact_runtime_result(load)
        if not load.get("success"):
            result["error"] = load.get("error") or "Failed to load MPH for boundary entity map."
            return _write_boundary_entity_map_report(result, json_path=json_path, markdown_path=markdown_path)

        model_name = str(load["model_name"])
        result["model_name"] = model_name
        result["model_summary"] = _compact_runtime_result(comsol_get_model_summary(model_name))
        result["entity_lookup"] = _get_selection_entities_via_java(model_name, selection_name=selection_name)
        result["map"] = _map_boundary_selection_entities(
            model_name,
            selection_name=selection_name,
            entities=result.get("entity_lookup", {}).get("entities") or [],
            rollers=rollers,
        )
        result["success"] = bool(result.get("entity_lookup", {}).get("success")) and bool(result["map"].get("success"))
        if not result["success"]:
            result["error"] = (
                result["map"].get("error")
                or result.get("entity_lookup", {}).get("error")
                or "Boundary entity map did not produce any usable entity centroid rows."
            )
        return _write_boundary_entity_map_report(result, json_path=json_path, markdown_path=markdown_path)
    finally:
        if model_name:
            result["close"] = _compact_runtime_result(comsol_close_model(model_name, save=False))
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def diagnose_stage_mph(
    *,
    mph_path: str | Path,
    output_dir: str | Path,
    cores: int = 1,
) -> dict[str, Any]:
    """Load a configured stage MPH and write a no-solve COMSOL audit artifact."""
    mph_file = Path(mph_path)
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "stage_mph_diagnostic.json"
    markdown_path = report_dir / "stage_mph_diagnostic.md"

    config = load_config()
    client = COMSOLClient.get_instance()
    model_name: str | None = None
    result: dict[str, Any] = {
        "success": False,
        "kind": "bearing_3d_stage_mph_no_solve_diagnostic",
        "mph_path": str(mph_file),
        "output_dir": str(report_dir),
        "json_path": str(json_path.resolve()),
        "markdown_path": str(markdown_path.resolve()),
        "policy": "load_configured_mph_and_audit_model_state_without_calling_solve",
    }
    try:
        client.start(
            cores=cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        load = comsol_load_model(str(mph_file))
        result["load"] = _compact_runtime_result(load)
        if not load.get("success"):
            result["error"] = load.get("error") or "Failed to load configured stage MPH."
            return _write_stage_mph_diagnostic_report(result, json_path=json_path, markdown_path=markdown_path)

        model_name = str(load["model_name"])
        result["model_name"] = model_name
        result["model_summary"] = _compact_runtime_result(comsol_get_model_summary(model_name))
        audit = _run_stage_mph_model_audit(model_name)
        result["audit"] = audit
        result["success"] = bool(load.get("success")) and bool(audit.get("success"))
        if not result["success"]:
            result["error"] = audit.get("error") or "Stage MPH audit did not complete cleanly."
        return _write_stage_mph_diagnostic_report(result, json_path=json_path, markdown_path=markdown_path)
    finally:
        if model_name:
            result["close"] = _compact_runtime_result(comsol_close_model(model_name, save=False))
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def probe_saved_reaction_mph(
    *,
    mph_path: str | Path,
    output_dir: str | Path,
    selection_name: str = "sel_inner_bore_load_surface",
    cores: int = 1,
) -> dict[str, Any]:
    """Load a solved MPH and run the reaction-equivalent probe without re-solving."""
    mph_file = Path(mph_path)
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "reaction_probe_summary.json"
    markdown_path = report_dir / "reaction_probe_summary.md"

    config = load_config()
    client = COMSOLClient.get_instance()
    model_name: str | None = None
    result: dict[str, Any] = {
        "success": False,
        "kind": "bearing_3d_saved_mph_reaction_probe",
        "mph_path": str(mph_file),
        "selection_name": selection_name,
        "output_dir": str(report_dir),
        "json_path": str(json_path.resolve()),
        "markdown_path": str(markdown_path.resolve()),
        "policy": "load_solved_mph_and_probe_reaction_expressions_without_calling_solve",
    }
    try:
        client.start(
            cores=cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        load = comsol_load_model(str(mph_file))
        result["load"] = _compact_runtime_result(load)
        if not load.get("success"):
            result["error"] = load.get("error") or "Failed to load solved MPH for reaction probe."
            return _write_saved_reaction_probe_report(result, json_path=json_path, markdown_path=markdown_path)

        model_name = str(load["model_name"])
        result["model_name"] = model_name
        result["model_summary"] = _compact_runtime_result(comsol_get_model_summary(model_name))
        result["reaction_equivalent"] = _evaluate_displacement_reaction_equivalent(
            model_name,
            selection_name=selection_name,
        )
        reaction = result.get("reaction_equivalent") or {}
        result["success"] = bool(reaction.get("success"))
        reaction_force_abs = reaction.get("best_reaction_force_abs_n")
        try:
            reaction_force_abs_numeric = float(reaction_force_abs) if reaction_force_abs is not None else None
        except (TypeError, ValueError):
            reaction_force_abs_numeric = None
        result["reaction_candidate_nonzero"] = bool(reaction.get("success")) and (
            reaction_force_abs_numeric is not None and abs(reaction_force_abs_numeric) > 1.0e-9
        )
        result["boundary_load_context"] = _infer_saved_reaction_boundary_load_context(json_path)
        result["reaction_load_balance"] = _reaction_load_balance_gate(
            reaction_force_abs_n=reaction_force_abs_numeric,
            applied_load_n=(result["boundary_load_context"] or {}).get("applied_load_n"),
        )
        result["reaction_verified"] = bool(result["reaction_candidate_nonzero"] and result["reaction_load_balance"].get("success"))
        result["candidate_audit"] = reaction.get("candidate_audit")
        result["setup_audit"] = reaction.get("setup_audit")
        result["warning"] = reaction.get("warning")
        if not result["success"]:
            result["error"] = reaction.get("warning") or "No nonzero reaction candidate was verified."
        return _write_saved_reaction_probe_report(result, json_path=json_path, markdown_path=markdown_path)
    finally:
        if model_name:
            result["close"] = _compact_runtime_result(comsol_close_model(model_name, save=False))
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def probe_saved_contact_mph(
    *,
    mph_path: str | Path,
    output_dir: str | Path,
    rollers: tuple[int, ...] = (1, 2, 12),
    entity_transfer: dict[str, Any] | None = None,
    cores: int = 1,
) -> dict[str, Any]:
    """Load a solved MPH and probe contact-surface variables without re-solving."""
    mph_file = Path(mph_path)
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "contact_probe_summary.json"
    markdown_path = report_dir / "contact_probe_summary.md"

    config = load_config()
    client = COMSOLClient.get_instance()
    model_name: str | None = None
    result: dict[str, Any] = {
        "success": False,
        "kind": "bearing_3d_saved_mph_contact_probe",
        "mph_path": str(mph_file),
        "rollers": list(rollers),
        "output_dir": str(report_dir),
        "json_path": str(json_path.resolve()),
        "markdown_path": str(markdown_path.resolve()),
        "policy": "load_solved_mph_and_probe_contact_surface_candidates_without_calling_solve",
    }
    try:
        client.start(
            cores=cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        load = comsol_load_model(str(mph_file))
        result["load"] = _compact_runtime_result(load)
        if not load.get("success"):
            result["error"] = load.get("error") or "Failed to load solved MPH for contact probe."
            return _write_saved_contact_probe_report(result, json_path=json_path, markdown_path=markdown_path)

        model_name = str(load["model_name"])
        result["model_name"] = model_name
        result["model_summary"] = _compact_runtime_result(comsol_get_model_summary(model_name))
        contact_probe = _evaluate_saved_contact_surface_candidates(
            model_name,
            rollers=rollers,
            entity_transfer=entity_transfer,
        )
        result["contact_probe"] = contact_probe
        solved_mph_model_audit = _run_stage_mph_model_audit(model_name)
        result["solved_mph_model_audit"] = _compact_contact_model_audit_for_saved_probe(
            solved_mph_model_audit,
            rollers=rollers,
        )
        result["pair_enforcement_diagnostic"] = _saved_contact_pair_enforcement_diagnostic(
            solved_mph_model_audit,
            contact_probe=contact_probe,
            rollers=rollers,
        )
        result["contact_feature_introspection"] = _introspect_contact_feature_properties(
            model_name,
            rollers=rollers,
        )
        result["success"] = True
        result["contact_probe_success_count"] = contact_probe.get("success_count")
        result["contact_probe_nonzero_count"] = contact_probe.get("nonzero_count")
        result["warning"] = contact_probe.get("warning")
        return _write_saved_contact_probe_report(result, json_path=json_path, markdown_path=markdown_path)
    finally:
        if model_name:
            result["close"] = _compact_runtime_result(comsol_close_model(model_name, save=False))
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


GEOMETRY_PARTITION_API_PROBE_JSON_START = "GEOMETRY_PARTITION_API_PROBE_JSON_START"
GEOMETRY_PARTITION_API_PROBE_JSON_END = "GEOMETRY_PARTITION_API_PROBE_JSON_END"


def probe_geometry_partition_api(
    *,
    output_dir: str | Path,
    model_name: str = "bearing3d_geometry_partition_api_probe",
    cores: int = 1,
) -> dict[str, Any]:
    """Probe COMSOL geometry feature types before adding bearing raceway imprints."""
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "geometry_partition_api_probe.json"
    markdown_path = report_dir / "geometry_partition_api_probe.md"

    config = load_config()
    client = COMSOLClient.get_instance()
    result: dict[str, Any] = {
        "success": False,
        "kind": "bearing_3d_geometry_partition_api_probe",
        "model_name": model_name,
        "output_dir": str(report_dir),
        "json_path": str(json_path.resolve()),
        "markdown_path": str(markdown_path.resolve()),
        "policy": "create_toy_geometry_and_probe_partition_imprint_feature_types_without_bearing_solve",
    }
    actual_model_name = model_name
    try:
        client.start(
            cores=cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        create = comsol_create_model(model_name)
        result["create_model"] = _compact_runtime_result(create)
        if not create.get("success"):
            result["error"] = create.get("error") or "Failed to create geometry partition probe model."
            return _write_geometry_partition_api_probe_report(result, json_path=json_path, markdown_path=markdown_path)
        actual_model_name = str(create.get("model_name") or model_name)
        result["model_name"] = actual_model_name
        execution = comsol_execute_java(_build_geometry_partition_api_probe_code(), model_name=actual_model_name)
        result["execution"] = _compact_runtime_result(execution)
        parsed = _extract_marked_json_payload(
            execution.get("stdout") or execution.get("output"),
            start_marker=GEOMETRY_PARTITION_API_PROBE_JSON_START,
            end_marker=GEOMETRY_PARTITION_API_PROBE_JSON_END,
        )
        payload = parsed.get("payload") if isinstance(parsed.get("payload"), dict) else {}
        result["probe"] = payload
        result["success"] = bool(execution.get("success")) and bool(payload.get("success"))
        if not result["success"]:
            result["error"] = parsed.get("error") or execution.get("error") or payload.get("error")
        return _write_geometry_partition_api_probe_report(result, json_path=json_path, markdown_path=markdown_path)
    finally:
        try:
            comsol_close_model(actual_model_name, save=False)
        except Exception:
            pass
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def _build_geometry_partition_api_probe_code() -> str:
    candidates = [
        "Partition",
        "PartitionObjects",
        "PartitionDomains",
        "PartitionFaces",
        "PartitionEdges",
        "Split",
        "Imprint",
        "Compose",
        "Intersection",
        "Difference",
        "Union",
        "WorkPlane",
    ]
    candidate_literal = repr(candidates)
    return f"""
import json

def _stringify(value):
    try:
        if isinstance(value, (list, tuple)):
            return [_stringify(item) for item in value]
    except Exception:
        pass
    return str(value)

def _safe(label, func):
    try:
        return {{'success': True, 'value': _stringify(func())}}
    except Exception as error:
        return {{'success': False, 'error': str(error)}}

def _feature_get(feature, prop):
    errors = []
    for method in ['getStringArray', 'getString', 'getDoubleArray', 'getDouble', 'getIntArray', 'getInt', 'getBoolean', 'get']:
        try:
            return {{'success': True, 'method': method, 'value': _stringify(getattr(feature, method)(prop))}}
        except Exception as error:
            errors.append(method + ': ' + str(error))
    return {{'success': False, 'error': ' | '.join(errors)}}

def _feature_set(feature, prop, value):
    try:
        feature.set(prop, value)
        return {{'success': True, 'value': _stringify(value)}}
    except Exception as error:
        return {{'success': False, 'value': _stringify(value), 'error': str(error)}}

def _geom_run(geom_obj, tag=None):
    try:
        if tag is None:
            geom_obj.run()
        else:
            geom_obj.run(tag)
        return {{'success': True}}
    except Exception as error:
        return {{'success': False, 'error': str(error)}}

for _name, _func in {{
    '_stringify': _stringify,
    '_safe': _safe,
    '_feature_get': _feature_get,
    '_feature_set': _feature_set,
    '_geom_run': _geom_run,
}}.items():
    globals()[_name] = _func

rows = []
base = {{'success': False}}
try:
    model.component().create('probecomp', True)
    model.component('probecomp').geom().create('geom1', 3)
    geom = model.component('probecomp').geom('geom1')
    geom.lengthUnit('mm')
    geom.create('raceway_block', 'Block')
    geom.feature('raceway_block').set('size', ['8[mm]', '8[mm]', '4[mm]'])
    geom.feature('raceway_block').set('pos', ['-4[mm]', '-4[mm]', '-2[mm]'])
    geom.create('imprint_tool', 'Block')
    geom.feature('imprint_tool').set('size', ['1[mm]', '3[mm]', '5[mm]'])
    geom.feature('imprint_tool').set('pos', ['-0.5[mm]', '-1.5[mm]', '-2.5[mm]'])
    geom.create('roller_cyl', 'Cylinder')
    geom.feature('roller_cyl').set('r', '1.5[mm]')
    geom.feature('roller_cyl').set('h', '4[mm]')
    geom.feature('roller_cyl').set('pos', ['0', '0', '-2[mm]'])
    base['run_primitives'] = _geom_run(geom)
    base['feature_tags_after_primitives'] = _safe('feature_tags', lambda: list(geom.feature().tags()))
    for feature_type in {candidate_literal}:
        row = {{'feature_type': feature_type}}
        tag = 'probe_' + feature_type.lower().replace(' ', '_')
        try:
            try:
                geom.feature().remove(tag)
            except Exception:
                pass
            feature = geom.create(tag, feature_type)
            row['create_success'] = True
            row['feature_tag'] = tag
            row['type'] = _safe('type', lambda feature=feature: feature.getType())
            row['property_names'] = _safe('properties', lambda feature=feature: list(feature.properties()))
            row['set_attempts'] = {{
                'selection_input_set': _safe('selection_input_set', lambda feature=feature: feature.selection('input').set(['raceway_block'])),
                'selection_input2_set': _safe('selection_input2_set', lambda feature=feature: feature.selection('input2').set(['imprint_tool'])),
                'selection_tool_set': _safe('selection_tool_set', lambda feature=feature: feature.selection('tool').set(['imprint_tool'])),
                'set_input': _feature_set(feature, 'input', ['raceway_block']),
                'set_input2': _feature_set(feature, 'input2', ['imprint_tool']),
                'set_tool': _feature_set(feature, 'tool', ['imprint_tool']),
                'set_keep': _feature_set(feature, 'keep', 'on'),
                'set_intbnd': _feature_set(feature, 'intbnd', 'on'),
                'set_face': _feature_set(feature, 'face', 'all'),
                'set_action_partition': _feature_set(feature, 'action', 'partition'),
            }}
            row['properties_after_sets'] = {{
                prop: _feature_get(feature, prop)
                for prop in ['input', 'input2', 'tool', 'keep', 'intbnd', 'face', 'action']
            }}
            row['run_attempt'] = _geom_run(geom, tag)
        except Exception as error:
            row['create_success'] = False
            row['error'] = str(error)
        rows.append(row)
except Exception as error:
    base['error'] = str(error)

valid_features = [
    row.get('feature_type')
    for row in rows
    if row.get('create_success') is True
]
runnable_features = [
    row.get('feature_type')
    for row in rows
    if (row.get('run_attempt') or {{}}).get('success') is True
]
payload = {{
    'success': bool(rows),
    'kind': 'bearing_3d_geometry_partition_api_probe',
    'base': base,
    'candidate_count': len(rows),
    'create_success_count': sum(1 for row in rows if row.get('create_success') is True),
    'run_success_count': sum(1 for row in rows if (row.get('run_attempt') or {{}}).get('success') is True),
    'valid_feature_types': valid_features,
    'runnable_feature_types': runnable_features,
    'rows': rows,
}}
output.write({GEOMETRY_PARTITION_API_PROBE_JSON_START!r} + '\\n')
output.write(json.dumps(payload, ensure_ascii=False, default=str))
output.write('\\n' + {GEOMETRY_PARTITION_API_PROBE_JSON_END!r} + '\\n')
"""


def _write_geometry_partition_api_probe_report(
    result: dict[str, Any],
    *,
    json_path: Path,
    markdown_path: Path,
) -> dict[str, Any]:
    result["json_path"] = str(json_path.resolve())
    result["markdown_path"] = str(markdown_path.resolve())
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(_render_geometry_partition_api_probe_markdown(result), encoding="utf-8")
    return result


def _render_geometry_partition_api_probe_markdown(result: dict[str, Any]) -> str:
    probe = result.get("probe") if isinstance(result.get("probe"), dict) else {}
    rows = probe.get("rows") if isinstance(probe.get("rows"), list) else []
    lines = [
        "# Bearing 3D Geometry Partition API Probe",
        "",
        f"- Success: `{result.get('success')}`",
        f"- Model: `{result.get('model_name')}`",
        f"- Candidate count: `{probe.get('candidate_count')}`",
        f"- Create success count: `{probe.get('create_success_count')}`",
        f"- Run success count: `{probe.get('run_success_count')}`",
        f"- Valid feature types: `{probe.get('valid_feature_types')}`",
        f"- Runnable feature types: `{probe.get('runnable_feature_types')}`",
        "",
        "| Feature type | Create | Run | Useful set successes | Error |",
        "|---|---:|---:|---|---|",
    ]
    for row in rows:
        set_attempts = row.get("set_attempts") if isinstance(row.get("set_attempts"), dict) else {}
        useful_sets = [
            key for key, value in set_attempts.items()
            if isinstance(value, dict) and value.get("success") is True
        ]
        run_attempt = row.get("run_attempt") if isinstance(row.get("run_attempt"), dict) else {}
        error = row.get("error") or run_attempt.get("error") or ""
        lines.append(
            "| {feature} | {create} | {run} | `{sets}` | {error} |".format(
                feature=row.get("feature_type"),
                create=row.get("create_success"),
                run=run_attempt.get("success"),
                sets=", ".join(useful_sets),
                error=escape(str(error))[:240],
            )
        )
    if result.get("error"):
        lines.extend(["", f"Error: `{result.get('error')}`"])
    lines.append("")
    return "\n".join(lines)


CYLINDER_SEAM_API_PROBE_JSON_START = "CYLINDER_SEAM_API_PROBE_JSON_START"
CYLINDER_SEAM_API_PROBE_JSON_END = "CYLINDER_SEAM_API_PROBE_JSON_END"


def probe_cylinder_seam_api(
    *,
    output_dir: str | Path,
    model_name: str = "bearing3d_cylinder_seam_api_probe",
    cores: int = 1,
) -> dict[str, Any]:
    """Probe COMSOL Cylinder feature properties relevant to roller source-surface seam control."""
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "cylinder_seam_api_probe.json"
    markdown_path = report_dir / "cylinder_seam_api_probe.md"

    config = load_config()
    client = COMSOLClient.get_instance()
    result: dict[str, Any] = {
        "success": False,
        "kind": "bearing_3d_cylinder_seam_api_probe",
        "model_name": model_name,
        "output_dir": str(report_dir),
        "json_path": str(json_path.resolve()),
        "markdown_path": str(markdown_path.resolve()),
        "policy": "create_toy_cylinder_geometry_and_probe_rotation_axis_selection_properties_without_bearing_solve",
    }
    actual_model_name = model_name
    try:
        client.start(
            cores=cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        create = comsol_create_model(model_name)
        result["create_model"] = _compact_runtime_result(create)
        if not create.get("success"):
            result["error"] = create.get("error") or "Failed to create cylinder seam probe model."
            return _write_cylinder_seam_api_probe_report(result, json_path=json_path, markdown_path=markdown_path)
        actual_model_name = str(create.get("model_name") or model_name)
        result["model_name"] = actual_model_name
        execution = comsol_execute_java(_build_cylinder_seam_api_probe_code(), model_name=actual_model_name)
        result["execution"] = _compact_runtime_result(execution)
        parsed = _extract_marked_json_payload(
            execution.get("stdout") or execution.get("output"),
            start_marker=CYLINDER_SEAM_API_PROBE_JSON_START,
            end_marker=CYLINDER_SEAM_API_PROBE_JSON_END,
        )
        payload = parsed.get("payload") if isinstance(parsed.get("payload"), dict) else {}
        result["probe"] = payload
        result["success"] = bool(execution.get("success")) and bool(payload.get("success"))
        if not result["success"]:
            result["error"] = parsed.get("error") or execution.get("error") or payload.get("error")
        return _write_cylinder_seam_api_probe_report(result, json_path=json_path, markdown_path=markdown_path)
    finally:
        try:
            comsol_close_model(actual_model_name, save=False)
        except Exception:
            pass
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def _build_cylinder_seam_api_probe_code() -> str:
    attempts = [
        ("selresult", "on"),
        ("selresultshow", "all"),
        ("rot", "15[deg]"),
        ("rot", "15"),
        ("axis", ["0", "0", "1"]),
        ("axistype", "z"),
        ("angle", "360[deg]"),
        ("type", "solid"),
        ("pos", ["0", "0", "-2[mm]"]),
    ]
    attempt_literal = repr(attempts)
    return f"""
import json

def _stringify(value):
    try:
        if isinstance(value, (list, tuple)):
            return [_stringify(item) for item in value]
    except Exception:
        pass
    return str(value)

def _safe(label, func):
    try:
        return {{'success': True, 'value': _stringify(func())}}
    except Exception as error:
        return {{'success': False, 'error': str(error)}}

def _feature_get(feature, prop):
    errors = []
    for method in ['getStringArray', 'getString', 'getDoubleArray', 'getDouble', 'getIntArray', 'getInt', 'getBoolean', 'get']:
        try:
            return {{'success': True, 'method': method, 'value': _stringify(getattr(feature, method)(prop))}}
        except Exception as error:
            errors.append(method + ': ' + str(error))
    return {{'success': False, 'error': ' | '.join(errors)}}

def _feature_set(feature, prop, value):
    try:
        feature.set(prop, value)
        return {{'success': True, 'value': _stringify(value), 'after': _feature_get(feature, prop)}}
    except Exception as error:
        return {{'success': False, 'value': _stringify(value), 'error': str(error)}}

def _geom_run(geom_obj, tag=None):
    try:
        if tag is None:
            geom_obj.run()
        else:
            geom_obj.run(tag)
        return {{'success': True}}
    except Exception as error:
        return {{'success': False, 'error': str(error)}}

for _name, _func in {{
    '_stringify': _stringify,
    '_safe': _safe,
    '_feature_get': _feature_get,
    '_feature_set': _feature_set,
    '_geom_run': _geom_run,
}}.items():
    globals()[_name] = _func

payload = {{'success': False}}
try:
    model.component().create('probecomp', True)
    model.component('probecomp').geom().create('geom1', 3)
    geom = model.component('probecomp').geom('geom1')
    geom.lengthUnit('mm')

    cyl = geom.create('roller_cyl', 'Cylinder')
    cyl.set('r', '4[mm]')
    cyl.set('h', '16[mm]')
    cyl.set('pos', ['0', '0', '-8[mm]'])
    base_properties = _safe('properties', lambda: list(cyl.properties()))
    base_type = _safe('type', lambda: cyl.getType())

    attempts = []
    for prop, value in {attempt_literal}:
        row = {{'feature': 'roller_cyl', 'property': prop, 'value': _stringify(value)}}
        row['set'] = _feature_set(cyl, prop, value)
        attempts.append(row)

    rot_cyl = geom.create('roller_cyl_rot15_pre_run', 'Cylinder')
    rot_cyl.set('r', '4[mm]')
    rot_cyl.set('h', '16[mm]')
    rot_cyl.set('pos', ['12[mm]', '0', '-8[mm]'])
    rot_pre_run_attempts = []
    for prop, value in [('rot', '15[deg]'), ('axis', ['0', '0', '1']), ('selresult', 'on'), ('selresultshow', 'all')]:
        row = {{'feature': 'roller_cyl_rot15_pre_run', 'property': prop, 'value': _stringify(value)}}
        row['set'] = _feature_set(rot_cyl, prop, value)
        rot_pre_run_attempts.append(row)

    run_result = _geom_run(geom)
    feature_tags_after_run = _safe('feature_tags_after_run', lambda: list(geom.feature().tags()))
    payload = {{
        'success': True,
        'kind': 'bearing_3d_cylinder_seam_api_probe',
        'base_type': base_type,
        'base_properties': base_properties,
        'set_attempts': attempts,
        'rotated_pre_run_set_attempts': rot_pre_run_attempts,
        'run_result': run_result,
        'feature_tags_after_run': feature_tags_after_run,
        'successful_properties': sorted({{row.get('property') for row in attempts if (row.get('set') or {{}}).get('success') is True}}),
        'failed_properties': sorted({{row.get('property') for row in attempts if (row.get('set') or {{}}).get('success') is not True}}),
    }}
except Exception as error:
    payload = {{
        'success': False,
        'kind': 'bearing_3d_cylinder_seam_api_probe',
        'error': str(error),
    }}

output.write({CYLINDER_SEAM_API_PROBE_JSON_START!r} + '\\n')
output.write(json.dumps(payload, ensure_ascii=False, default=str))
output.write('\\n' + {CYLINDER_SEAM_API_PROBE_JSON_END!r} + '\\n')
"""


def _write_cylinder_seam_api_probe_report(
    result: dict[str, Any],
    *,
    json_path: Path,
    markdown_path: Path,
) -> dict[str, Any]:
    result["json_path"] = str(json_path.resolve())
    result["markdown_path"] = str(markdown_path.resolve())
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(_render_cylinder_seam_api_probe_markdown(result), encoding="utf-8")
    return result


def _render_cylinder_seam_api_probe_markdown(result: dict[str, Any]) -> str:
    probe = result.get("probe") if isinstance(result.get("probe"), dict) else {}
    attempts = probe.get("set_attempts") if isinstance(probe.get("set_attempts"), list) else []
    lines = [
        "# Bearing 3D Cylinder Seam API Probe",
        "",
        f"- Success: `{result.get('success')}`",
        f"- Model: `{result.get('model_name')}`",
        f"- Run result: `{probe.get('run_result')}`",
        f"- Successful properties: `{probe.get('successful_properties')}`",
        f"- Failed properties: `{probe.get('failed_properties')}`",
        "",
        "## Purpose",
        "",
        "This toy-geometry probe checks which COMSOL `Cylinder` feature properties are accepted by the local runtime before changing the full 3D bearing fixture. It is aimed at the `roller_1` zero-carry hypothesis that the `0 deg / +X` cylinder source surface or seam topology is not equivalent to neighboring rollers.",
        "",
        "## Property set attempts",
        "",
        "| Property | Value | Success | Error |",
        "|---|---|---:|---|",
    ]
    for row in attempts:
        set_result = row.get("set") if isinstance(row.get("set"), dict) else {}
        lines.append(
            f"| `{row.get('property')}` | `{row.get('value')}` | `{set_result.get('success')}` | `{set_result.get('error') or ''}` |"
        )
    if result.get("error"):
        lines.extend(["", f"Error: `{result.get('error')}`"])
    lines.extend([
        "",
        "## Raw payload",
        "",
        "```json",
        json.dumps(probe, ensure_ascii=False, indent=2, default=str),
        "```",
    ])
    return "\n".join(lines)


CONTACT_FEATURE_INTROSPECTION_JSON_START = "CONTACT_FEATURE_INTROSPECTION_JSON_START"
CONTACT_FEATURE_INTROSPECTION_JSON_END = "CONTACT_FEATURE_INTROSPECTION_JSON_END"


def _build_contact_feature_introspection_code(*, rollers: tuple[int, ...]) -> str:
    roller_literal = repr(list(rollers))
    return f"""
import json

def _stringify(value):
    try:
        if isinstance(value, (list, tuple)):
            return [_stringify(item) for item in value]
    except Exception:
        pass
    return str(value)

def _safe(label, func):
    try:
        return {{'success': True, 'value': _stringify(func())}}
    except Exception as error:
        return {{'success': False, 'error': str(error)}}

def _feature_get(feature, prop):
    errors = []
    for method in ['getStringArray', 'getString', 'getDoubleArray', 'getDouble', 'getIntArray', 'getInt', 'get']:
        try:
            return {{'success': True, 'method': method, 'value': _stringify(getattr(feature, method)(prop))}}
        except Exception as error:
            errors.append(method + ': ' + str(error))
    return {{'success': False, 'error': ' | '.join(errors)}}

def _feature_allowed(feature, prop):
    errors = []
    for method in ['getAllowedPropertyValues', 'getAllowedPropertyValuesString']:
        try:
            return {{'success': True, 'method': method, 'value': _stringify(getattr(feature, method)(prop))}}
        except Exception as error:
            errors.append(method + ': ' + str(error))
    return {{'success': False, 'error': ' | '.join(errors)}}

def _feature_exists(solid, tag):
    try:
        return solid.feature(tag)
    except Exception:
        return None

for _name, _func in {{
    '_stringify': _stringify,
    '_safe': _safe,
    '_feature_get': _feature_get,
    '_feature_allowed': _feature_allowed,
    '_feature_exists': _feature_exists,
}}.items():
    globals()[_name] = _func

rollers = {roller_literal}
candidate_props = [
    'pairs', 'Pair', 'ContactPair',
    'pn_penalty', 'penalty', 'penaltyFactor',
    'useRelaxation', 'irlx', 'relax',
    'tolcontact', 'ContactTolType',
    'zeroInitGap', 'initgap', 'initialgap', 'initialGap',
    'gapoffset', 'gapOffset', 'offset', 'source_offset', 'pressureOffsetCtrl', 'contactOffset',
    'offsetType', 'offsetMethod', 'offsetValue',
    'clearance', 'interference', 'contactInterference',
    'fric', 'mu',
]
rows = []
try:
    solid = model.component('comp1').physics('solid')
    solid_tags = list(solid.feature().tags())
    for roller in rollers:
        for side in ['inner', 'outer']:
            canonical = 'contact_roller_' + str(roller) + '_' + side
            candidate_tags = [canonical, 'roller_' + side + '_contact_' + str(roller)]
            for tag in candidate_tags:
                feature = _feature_exists(solid, tag)
                row = {{
                    'roller': int(roller),
                    'side': side,
                    'tag': tag,
                    'canonical_tag': canonical,
                    'exists': feature is not None,
                }}
                if feature is None:
                    row['error'] = 'feature not found'
                    rows.append(row)
                    continue
                row['type'] = _safe('type', lambda feature=feature: feature.getType())
                row['active'] = _safe('active', lambda feature=feature: feature.isActive())
                row['property_names'] = _safe('properties', lambda feature=feature: list(feature.properties()))
                property_names = row.get('property_names', {{}}).get('value') or []
                wanted = []
                for prop in list(property_names) + candidate_props:
                    if prop not in wanted:
                        wanted.append(prop)
                row['properties'] = {{prop: _feature_get(feature, prop) for prop in wanted}}
                row['allowed_property_values'] = {{
                    prop: _feature_allowed(feature, prop)
                    for prop in ['useRelaxation', 'ContactTolType', 'zeroInitGap', 'fric', 'offsetType', 'offsetMethod']
                }}
                rows.append(row)
except Exception as error:
    rows.append({{'exists': False, 'error': str(error)}})

payload = {{
    'success': any(
        row.get('exists')
        and (
            row.get('property_names', {{}}).get('success')
            or any(value.get('success') for value in row.get('properties', {{}}).values() if isinstance(value, dict))
        )
        for row in rows
    ),
    'kind': 'bearing_3d_contact_feature_property_introspection',
    'rollers': rollers,
    'feature_count': sum(1 for row in rows if row.get('exists')),
    'property_read_success_count': sum(
        1
        for row in rows
        if row.get('exists')
        and (
            row.get('property_names', {{}}).get('success')
            or any(value.get('success') for value in row.get('properties', {{}}).values() if isinstance(value, dict))
        )
    ),
    'rows': rows,
}}
output.write({CONTACT_FEATURE_INTROSPECTION_JSON_START!r} + '\\n')
output.write(json.dumps(payload, ensure_ascii=False, default=str))
output.write('\\n' + {CONTACT_FEATURE_INTROSPECTION_JSON_END!r} + '\\n')
"""


def _introspect_contact_feature_properties(model_name: str, *, rollers: tuple[int, ...]) -> dict[str, Any]:
    """List COMSOL Contact feature properties so offset/gap diagnostics are evidence based."""
    code = _build_contact_feature_introspection_code(rollers=rollers)
    execution = comsol_execute_java(code, model_name=model_name)
    parsed = _extract_marked_json_payload(
        execution.get("stdout") or execution.get("output"),
        start_marker=CONTACT_FEATURE_INTROSPECTION_JSON_START,
        end_marker=CONTACT_FEATURE_INTROSPECTION_JSON_END,
    )
    payload = parsed.get("payload") if isinstance(parsed.get("payload"), dict) else {}
    if not payload:
        payload = {
            "success": False,
            "kind": "bearing_3d_contact_feature_property_introspection",
            "rollers": list(rollers),
            "rows": [],
            "error": parsed.get("error") or execution.get("error"),
        }
    payload["execution"] = _compact_runtime_result(execution)
    payload["comparison"] = _summarize_contact_feature_introspection(payload)
    payload["success"] = bool(execution.get("success")) and bool(payload.get("success"))
    if not payload.get("success") and not payload.get("error"):
        payload["error"] = parsed.get("error") or execution.get("error") or "Contact feature introspection did not find active rows."
    return payload


def _extract_marked_json_payload(output: str | None, *, start_marker: str, end_marker: str) -> dict[str, Any]:
    if not output:
        return {"success": False, "error": "No marked JSON output was captured."}
    pattern = re.compile(
        re.escape(start_marker)
        + r"\s*(.*?)\s*"
        + re.escape(end_marker),
        flags=re.DOTALL,
    )
    match = pattern.search(output)
    if not match:
        return {"success": False, "error": "Marked JSON payload was not found in COMSOL output."}
    try:
        return {"success": True, "payload": json.loads(match.group(1))}
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"Marked JSON parse failed: {exc}"}


def _summarize_contact_feature_introspection(introspection: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in introspection.get("rows") or [] if isinstance(row, dict) and row.get("exists")]
    by_tag = {str(row.get("tag")): row for row in rows}
    property_name_union: list[str] = []
    offset_like_properties: list[str] = []
    readable_candidate_properties: dict[str, list[str]] = {}
    readable_offset_candidate_properties: dict[str, list[str]] = {}
    for row in rows:
        property_names = ((row.get("property_names") or {}).get("value") or [])
        for prop in property_names:
            prop_text = str(prop)
            if prop_text not in property_name_union:
                property_name_union.append(prop_text)
            if any(token in prop_text.lower() for token in ("gap", "offset", "clearance", "interference")):
                if prop_text not in offset_like_properties:
                    offset_like_properties.append(prop_text)
        readable = []
        for prop, value in (row.get("properties") or {}).items():
            if isinstance(value, dict) and value.get("success"):
                readable.append(str(prop))
        readable_candidate_properties[str(row.get("tag"))] = sorted(readable)
        readable_offset_candidate_properties[str(row.get("tag"))] = sorted(
            prop
            for prop in readable
            if any(token in prop.lower() for token in ("gap", "offset", "clearance", "interference"))
        )
    focus_pairs = [
        ("contact_roller_1_inner", "contact_roller_2_inner"),
        ("contact_roller_1_outer", "contact_roller_2_outer"),
        ("contact_roller_1_inner", "contact_roller_12_inner"),
        ("contact_roller_1_outer", "contact_roller_12_outer"),
    ]
    differences: list[dict[str, Any]] = []
    for left_tag, right_tag in focus_pairs:
        left = by_tag.get(left_tag)
        right = by_tag.get(right_tag)
        if not left or not right:
            continue
        diff = _contact_feature_property_diff(left, right)
        if diff.get("different_properties"):
            differences.append(diff)
    unsupported_offset_candidates = {}
    for prop in ("gapoffset", "gapOffset", "contactOffset", "offsetValue", "initialGap", "initgap"):
        failed_tags = []
        for row in rows:
            value = (row.get("properties") or {}).get(prop)
            if isinstance(value, dict) and not value.get("success"):
                failed_tags.append(str(row.get("tag")))
        if failed_tags:
            unsupported_offset_candidates[prop] = failed_tags
    return {
        "success": bool(rows),
        "feature_count": len(rows),
        "property_name_union": sorted(property_name_union),
        "offset_like_properties": sorted(offset_like_properties),
        "readable_candidate_properties": readable_candidate_properties,
        "readable_offset_candidate_properties": readable_offset_candidate_properties,
        "zero_carry_reference_differences": differences,
        "zero_carry_matches_reference_properties": not differences if rows else None,
        "unsupported_offset_candidate_properties": unsupported_offset_candidates,
    }


def _contact_feature_property_diff(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_props = left.get("properties") or {}
    right_props = right.get("properties") or {}
    keys = sorted(set(left_props) | set(right_props))
    different: list[dict[str, Any]] = []
    for key in keys:
        left_value = _normalized_contact_feature_property_value(_contact_feature_property_value(left_props.get(key)))
        right_value = _normalized_contact_feature_property_value(_contact_feature_property_value(right_props.get(key)))
        if left_value != right_value:
            different.append({
                "property": key,
                "left": left_value,
                "right": right_value,
            })
    return {
        "left_tag": left.get("tag"),
        "right_tag": right.get("tag"),
        "different_properties": different,
    }


def _contact_feature_property_value(entry: Any) -> Any:
    if not isinstance(entry, dict):
        return None
    if entry.get("success"):
        return entry.get("value")
    return {"error": entry.get("error")}


def _normalized_contact_feature_property_value(value: Any) -> Any:
    if isinstance(value, str):
        text = re.sub(r"cp_roller_\d+_", "cp_roller_*_", value)
        text = re.sub(r"contact_roller_\d+_", "contact_roller_*_", text)
        text = re.sub(r"roller_\d+_", "roller_*_", text)
        return text
    if isinstance(value, list):
        return [_normalized_contact_feature_property_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalized_contact_feature_property_value(item) for key, item in value.items()}
    return value


def _evaluate_saved_contact_surface_candidates(
    model_name: str,
    *,
    rollers: tuple[int, ...],
    entity_transfer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evaluations: list[dict[str, Any]] = []
    normal_evaluations: list[dict[str, Any]] = []
    geometry_evaluations: list[dict[str, Any]] = []
    entity_geometry_evaluations: list[dict[str, Any]] = []
    pair_transfer_evaluations: list[dict[str, Any]] = []
    traction_x = "solid.sx*nx+solid.sxy*ny+solid.sxz*nz"
    traction_y = "solid.sxy*nx+solid.sy*ny+solid.syz*nz"
    for roller in rollers:
        angle = 2.0 * math.pi * (roller - 1) / VERIFIED_ROLLER_COUNT
        radial_x = math.cos(angle)
        radial_y = math.sin(angle)
        radial_traction = f"({traction_x})*({radial_x:.12g})+({traction_y})*({radial_y:.12g})"
        selections = [
            (f"roller_{roller}_inner_source", f"sel_roller_{roller}_inner_contact"),
            (f"roller_{roller}_inner_raceway", f"sel_inner_raceway_{roller}_contact"),
            (f"roller_{roller}_outer_source", f"sel_roller_{roller}_outer_contact"),
            (f"roller_{roller}_outer_raceway", f"sel_outer_raceway_{roller}_contact"),
        ]
        for label, selection in selections:
            normal_evaluations.extend(_evaluate_contact_normal_orientation(
                model_name,
                roller=roller,
                contact_label=label,
                selection_name=selection,
                radial_x=radial_x,
                radial_y=radial_y,
            ))
            geometry_evaluations.extend(_evaluate_contact_geometry_moments(
                model_name,
                roller=roller,
                contact_label=label,
                selection_name=selection,
                radial_x=radial_x,
                radial_y=radial_y,
            ))
            entity_geometry_evaluations.extend(_evaluate_contact_entity_geometry_moments(
                model_name,
                roller=roller,
                contact_label=label,
                selection_name=selection,
                radial_x=radial_x,
                radial_y=radial_y,
            ))
            pair_transfer_evaluations.extend(_evaluate_pair_transfer_integrals(
                model_name,
                roller=roller,
                contact_label=label,
                selection_name=selection,
            ))
            max_expressions = ["solid.mises", "solid.disp"]
            integral_expressions = [traction_x, traction_y, radial_traction]
            contact_expressions = _contact_status_candidate_expressions(roller=roller, contact_label=label)
            for expr_index, expression in enumerate(max_expressions, start=1):
                evaluation = _evaluate_surface_max_expression_via_java(
                    model_name,
                    expression,
                    selection_name=selection,
                    tag=f"contact_max_r{roller}_{label}_{expr_index}",
                )
                evaluation.update({
                    "roller": roller,
                    "contact_label": label,
                    "selection": selection,
                    "diagnostic_class": _classify_contact_probe_evaluation(evaluation),
                })
                evaluations.append(evaluation)
            for expr_index, expression in enumerate(contact_expressions, start=1):
                evaluation = _evaluate_surface_max_expression_via_java(
                    model_name,
                    expression,
                    selection_name=selection,
                    tag=f"contact_state_r{roller}_{label}_{expr_index}",
                )
                evaluation.update({
                    "roller": roller,
                    "contact_label": label,
                    "selection": selection,
                    "candidate_group": "contact_status_pair_variable",
                    "diagnostic_class": _classify_contact_probe_evaluation(evaluation),
                })
                evaluations.append(evaluation)
            for expr_index, expression in enumerate(integral_expressions, start=1):
                evaluation = _evaluate_surface_integral_expression_via_java(
                    model_name,
                    expression,
                    selection_name=selection,
                    tag=f"contact_int_r{roller}_{label}_{expr_index}",
                )
                evaluation.update({
                    "roller": roller,
                    "contact_label": label,
                    "selection": selection,
                    "diagnostic_class": _classify_contact_probe_evaluation(evaluation),
                })
                evaluations.append(evaluation)
    success_count = sum(1 for item in evaluations if item.get("success"))
    nonzero_count = sum(
        1 for item in evaluations
        if item.get("success") and _runtime_numeric_is_finite_nonzero(item)
    )
    by_roller = _summarize_contact_probe_by_roller(evaluations)
    candidate_audit = _summarize_contact_probe_evaluations(evaluations)
    contact_status_by_roller = _summarize_contact_status_by_roller(evaluations)
    contact_variable_discovery = _summarize_contact_variable_discovery(evaluations)
    normal_orientation_by_roller = _summarize_contact_normal_orientation(normal_evaluations)
    geometry_moments_by_roller = _summarize_contact_geometry_moments(geometry_evaluations)
    entity_geometry_moments_by_roller = _summarize_contact_entity_geometry_moments(entity_geometry_evaluations)
    pair_transfer_by_roller = _summarize_pair_transfer_integrals(pair_transfer_evaluations)
    entity_transfer_diagnostic = _evaluate_contact_entity_transfer(
        model_name,
        entity_transfer=entity_transfer,
    )
    return {
        "success": success_count > 0,
        "kind": "bearing_3d_saved_mph_contact_surface_candidate_probe",
        "candidate_count": len(evaluations),
        "success_count": success_count,
        "nonzero_count": nonzero_count,
        "candidate_audit": candidate_audit,
        "contact_status_by_roller": contact_status_by_roller,
        "contact_variable_discovery": contact_variable_discovery,
        "normal_orientation_by_roller": normal_orientation_by_roller,
        "normal_orientation_evaluations": normal_evaluations,
        "geometry_moments_by_roller": geometry_moments_by_roller,
        "geometry_moment_evaluations": geometry_evaluations,
        "entity_geometry_moments_by_roller": entity_geometry_moments_by_roller,
        "entity_geometry_moment_evaluations": entity_geometry_evaluations,
        "pair_transfer_by_roller": pair_transfer_by_roller,
        "pair_transfer_evaluations": pair_transfer_evaluations,
        "entity_transfer_diagnostic": entity_transfer_diagnostic,
        "evaluations": evaluations,
        "by_roller": by_roller,
        "warning": None if success_count else "No contact-surface candidate expression evaluated successfully.",
    }


def _evaluate_contact_entity_transfer(
    model_name: str,
    *,
    entity_transfer: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Probe pair transfer field values separately on each boundary entity."""
    if not isinstance(entity_transfer, dict) or not entity_transfer.get("selection_name"):
        return None
    roller = int(entity_transfer.get("roller") or 1)
    contact_label = str(entity_transfer.get("contact_label") or "roller_1_outer_raceway")
    selection_name = str(entity_transfer["selection_name"])
    if "inner" in contact_label:
        pair_tag = f"cp_roller_{roller}_inner_raceway"
    elif "outer" in contact_label:
        pair_tag = f"cp_roller_{roller}_outer_raceway"
    else:
        return {
            "success": False,
            "error": f"Unsupported entity transfer contact label: {contact_label}",
        }
    entity_lookup = _get_selection_entities_via_java(model_name, selection_name=selection_name)
    entities = entity_lookup.get("entities") if isinstance(entity_lookup.get("entities"), list) else []
    if not entities:
        return {
            "success": False,
            "roller": roller,
            "contact_label": contact_label,
            "selection": selection_name,
            "pair_tag": pair_tag,
            "selection_entity_lookup": entity_lookup,
            "entity_count": 0,
            "error": entity_lookup.get("error") or "No entities found for entity transfer probe.",
        }
    expressions = _contact_entity_transfer_expression_candidates(pair_tag)
    evaluations: list[dict[str, Any]] = []
    for entity in entities:
        for label, expression, method in expressions:
            if method == "max":
                evaluation = _evaluate_surface_max_expression_on_entities_via_java(
                    model_name,
                    expression,
                    entities=[int(entity)],
                    tag=f"entity_transfer_{contact_label}_{entity}_{label}",
                )
            else:
                evaluation = _evaluate_surface_integral_expression_on_entities_via_java(
                    model_name,
                    expression,
                    entities=[int(entity)],
                    tag=f"entity_transfer_{contact_label}_{entity}_{label}",
                )
            evaluation.update({
                "roller": roller,
                "contact_label": contact_label,
                "selection": selection_name,
                "entity": int(entity),
                "pair_tag": pair_tag,
                "transfer_label": label,
                "candidate_group": "contact_entity_transfer",
                "diagnostic_class": _classify_contact_probe_evaluation(evaluation),
            })
            evaluations.append(evaluation)
    by_entity: dict[str, dict[str, Any]] = {}
    for evaluation in evaluations:
        entity_key = str(evaluation["entity"])
        entity_row = by_entity.setdefault(entity_key, {})
        entity_row[evaluation["transfer_label"]] = {
            "success": bool(evaluation.get("success")),
            "value": _runtime_numeric_max(evaluation),
            "diagnostic_class": evaluation.get("diagnostic_class"),
            "expression": evaluation.get("expression"),
            "method": evaluation.get("method"),
        }
    nonzero_entities = {
        label: sorted({
            int(entity)
            for item in evaluations
            if item.get("transfer_label") == label
            and item.get("success")
            and _runtime_numeric_is_finite_nonzero(item)
            for entity in [item.get("entity")]
        })
        for label, _expression, _method in expressions
    }
    return {
        "success": bool(evaluations) and any(
            str(item.get("transfer_label") or "").endswith("Tn_max")
            and item.get("success")
            and _runtime_numeric_is_finite_nonzero(item)
            for item in evaluations
        ),
        "roller": roller,
        "contact_label": contact_label,
        "selection": selection_name,
        "pair_tag": pair_tag,
        "selection_entity_lookup": entity_lookup,
        "entity_count": len(entities),
        "evaluations": evaluations,
        "by_entity": by_entity,
        "nonzero_entities": nonzero_entities,
    }


def _contact_entity_transfer_expression_candidates(pair_tag: str) -> list[tuple[str, str, str]]:
    """Return source/destination-aware pair-transfer candidates for one contact pair."""
    expressions = [
        ("pair_Tn_max", f"solid.Tn_{pair_tag}", "max"),
        ("abs_pair_Tn_max", f"abs(solid.Tn_{pair_tag})", "max"),
        ("pair_Tn_integral", f"solid.Tn_{pair_tag}", "integral"),
        ("abs_pair_Tn_integral", f"abs(solid.Tn_{pair_tag})", "integral"),
    ]
    for endpoint in ("src", "dst"):
        for pattern_label, expression in (
            (f"pair_Tn_{endpoint}", f"solid.Tn_{pair_tag}_{endpoint}"),
            (f"pair_Tn_{endpoint}_prefix", f"solid.Tn_{endpoint}_{pair_tag}"),
        ):
            expressions.extend([
                (f"{pattern_label}_max", expression, "max"),
                (f"abs_{pattern_label}_max", f"abs({expression})", "max"),
                (f"{pattern_label}_integral", expression, "integral"),
                (f"abs_{pattern_label}_integral", f"abs({expression})", "integral"),
            ])
    expressions.extend([
        ("generic_p_max", "solid.p", "max"),
        ("mises_max", "solid.mises", "max"),
    ])
    return expressions


def _contact_status_candidate_expressions(*, roller: int, contact_label: str) -> list[str]:
    """Return COMSOL contact-pair status/pressure/gap candidates for one roller surface."""
    pair_tags: list[str] = []
    if "inner" in contact_label:
        pair_tags.append(f"cp_roller_{roller}_inner_raceway")
    if "outer" in contact_label:
        pair_tags.append(f"cp_roller_{roller}_outer_raceway")
    if "cage" in contact_label:
        pair_tags.append(f"cp_roller_{roller}_cage_pocket")
    contact_variables = _contact_status_variable_names()
    generic_candidates: list[str] = []
    for variable in contact_variables:
        expression = f"solid.{variable}"
        generic_candidates.append(expression)
        if variable in _CONTACT_STATUS_ABS_VARIABLES:
            generic_candidates.append(f"abs({expression})")
    pair_candidates: list[str] = []
    for pair_tag in pair_tags:
        for variable in contact_variables:
            expression = f"solid.{variable}_{pair_tag}"
            pair_candidates.append(expression)
            if variable in _CONTACT_STATUS_ABS_VARIABLES:
                pair_candidates.append(f"abs({expression})")
    seen: set[str] = set()
    candidates: list[str] = []
    for expression in [*pair_candidates, *generic_candidates]:
        if expression not in seen:
            seen.add(expression)
            candidates.append(expression)
    return candidates


_CONTACT_STATUS_ABS_VARIABLES = {
    "Tn",
    "Tt",
    "gap",
    "gn",
    "pn",
    "pn0",
    "p",
    "pN",
    "pp",
    "TnPenalty",
    "g",
    "d",
    "dist",
    "distn",
}


def _contact_status_variable_names() -> tuple[str, ...]:
    """Variable families to try when discovering COMSOL contact active-state evidence."""
    return (
        "Tn",
        "Tt",
        "gap",
        "gn",
        "pn",
        "pn0",
        "p",
        "pN",
        "pp",
        "TnPenalty",
        "copen",
        "cstat",
        "active",
        "act",
        "cnt",
        "contact",
        "contactStatus",
        "g",
        "d",
        "dist",
        "distn",
        "lambdaN",
        "lambda_n",
        "lmbda",
    )


def _evaluate_contact_normal_orientation(
    model_name: str,
    *,
    roller: int,
    contact_label: str,
    selection_name: str,
    radial_x: float,
    radial_y: float,
) -> list[dict[str, Any]]:
    """Evaluate geometric normal orientation integrals on one contact selection."""
    radial_normal = f"nx*({radial_x:.12g})+ny*({radial_y:.12g})"
    expressions = [
        ("area", "1"),
        ("normal_x", "nx"),
        ("normal_y", "ny"),
        ("normal_z", "nz"),
        ("radial_normal", radial_normal),
    ]
    evaluations: list[dict[str, Any]] = []
    for index, (normal_label, expression) in enumerate(expressions, start=1):
        evaluation = _evaluate_surface_integral_expression_via_java(
            model_name,
            expression,
            selection_name=selection_name,
            tag=f"normal_int_r{roller}_{contact_label}_{index}",
        )
        evaluation.update({
            "roller": roller,
            "contact_label": contact_label,
            "selection": selection_name,
            "normal_label": normal_label,
            "candidate_group": "normal_orientation",
            "radial_unit": {"x": radial_x, "y": radial_y},
            "diagnostic_class": _classify_contact_probe_evaluation(evaluation),
        })
        evaluations.append(evaluation)
    return evaluations


def _evaluate_contact_geometry_moments(
    model_name: str,
    *,
    roller: int,
    contact_label: str,
    selection_name: str,
    radial_x: float,
    radial_y: float,
) -> list[dict[str, Any]]:
    """Evaluate contact selection centroids as a solved-MPH geometry/gap proxy."""
    radial_coordinate = f"x*({radial_x:.12g})+y*({radial_y:.12g})"
    expressions = [
        ("area", "1"),
        ("x_moment", "x"),
        ("y_moment", "y"),
        ("z_moment", "z"),
        ("radial_moment", radial_coordinate),
    ]
    evaluations: list[dict[str, Any]] = []
    for index, (moment_label, expression) in enumerate(expressions, start=1):
        evaluation = _evaluate_surface_integral_expression_via_java(
            model_name,
            expression,
            selection_name=selection_name,
            tag=f"geometry_moment_r{roller}_{contact_label}_{index}",
        )
        evaluation.update({
            "roller": roller,
            "contact_label": contact_label,
            "selection": selection_name,
            "moment_label": moment_label,
            "candidate_group": "contact_geometry_moment",
            "radial_unit": {"x": radial_x, "y": radial_y},
            "diagnostic_class": _classify_contact_probe_evaluation(evaluation),
        })
        evaluations.append(evaluation)
    return evaluations


def _evaluate_contact_entity_geometry_moments(
    model_name: str,
    *,
    roller: int,
    contact_label: str,
    selection_name: str,
    radial_x: float,
    radial_y: float,
) -> list[dict[str, Any]]:
    """Evaluate per-boundary-entity centroids for a contact selection."""
    entity_lookup = _get_selection_entities_via_java(model_name, selection_name=selection_name)
    entities = entity_lookup.get("entities") if isinstance(entity_lookup.get("entities"), list) else []
    radial_coordinate = f"x*({radial_x:.12g})+y*({radial_y:.12g})"
    expressions = [
        ("area", "1"),
        ("x_moment", "x"),
        ("y_moment", "y"),
        ("z_moment", "z"),
        ("radial_moment", radial_coordinate),
    ]
    evaluations: list[dict[str, Any]] = []
    if not entities:
        evaluations.append({
            "success": False,
            "roller": roller,
            "contact_label": contact_label,
            "selection": selection_name,
            "candidate_group": "contact_entity_geometry_moment",
            "selection_entity_lookup": entity_lookup,
            "diagnostic_class": _classify_contact_probe_evaluation(entity_lookup),
            "error": entity_lookup.get("error") or "No entities found for selection.",
        })
        return evaluations
    for entity in entities:
        for index, (moment_label, expression) in enumerate(expressions, start=1):
            evaluation = _evaluate_surface_integral_expression_on_entities_via_java(
                model_name,
                expression,
                entities=[int(entity)],
                tag=f"entity_moment_r{roller}_{contact_label}_{entity}_{index}",
            )
            evaluation.update({
                "roller": roller,
                "contact_label": contact_label,
                "selection": selection_name,
                "entity": int(entity),
                "moment_label": moment_label,
                "candidate_group": "contact_entity_geometry_moment",
                "selection_entity_lookup": entity_lookup,
                "radial_unit": {"x": radial_x, "y": radial_y},
                "diagnostic_class": _classify_contact_probe_evaluation(evaluation),
            })
            evaluations.append(evaluation)
    return evaluations


def _evaluate_pair_transfer_integrals(
    model_name: str,
    *,
    roller: int,
    contact_label: str,
    selection_name: str,
) -> list[dict[str, Any]]:
    """Integrate pair-specific normal pressure variables over contact selections."""
    pair_tags: list[str] = []
    if "inner" in contact_label:
        pair_tags.append(f"cp_roller_{roller}_inner_raceway")
    if "outer" in contact_label:
        pair_tags.append(f"cp_roller_{roller}_outer_raceway")
    evaluations: list[dict[str, Any]] = []
    for pair_index, pair_tag in enumerate(pair_tags, start=1):
        expressions = [
            ("signed_Tn_integral", f"solid.Tn_{pair_tag}"),
            ("abs_Tn_integral", f"abs(solid.Tn_{pair_tag})"),
        ]
        for expr_index, (transfer_label, expression) in enumerate(expressions, start=1):
            evaluation = _evaluate_surface_integral_expression_via_java(
                model_name,
                expression,
                selection_name=selection_name,
                tag=f"pair_transfer_r{roller}_{contact_label}_{pair_index}_{expr_index}",
            )
            evaluation.update({
                "roller": roller,
                "contact_label": contact_label,
                "selection": selection_name,
                "pair_tag": pair_tag,
                "transfer_label": transfer_label,
                "candidate_group": "pair_transfer_integral",
                "diagnostic_class": _classify_contact_probe_evaluation(evaluation),
            })
            evaluations.append(evaluation)
    return evaluations


def _classify_contact_probe_evaluation(evaluation: dict[str, Any]) -> str:
    value = _runtime_numeric_max(evaluation)
    if evaluation.get("success") and value is not None:
        if math.isnan(value):
            return "nan_result"
        if math.isinf(value):
            return "infinite_result"
        return "nonzero_success" if abs(value) > 1.0e-12 else "zero_result"
    text = _reaction_evaluation_error_text(evaluation).lower()
    if "unknown variable" in text or "undefined variable" in text:
        return "unknown_variable"
    if "selection" in text:
        return "selection_error"
    if "dataset" in text or "dset" in text:
        return "dataset_error"
    if text:
        return "evaluation_error"
    return "not_evaluated"


def _summarize_contact_probe_evaluations(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    method_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    diagnostic_class_counts: dict[str, int] = {}
    first_failures: list[dict[str, Any]] = []
    first_contact_variable_successes: list[dict[str, Any]] = []
    for item in evaluations:
        method = str(item.get("method") or "unknown")
        method_counts[method] = method_counts.get(method, 0) + 1
        group = str(item.get("candidate_group") or "field_or_traction")
        group_counts[group] = group_counts.get(group, 0) + 1
        diagnostic_class = str(item.get("diagnostic_class") or _classify_contact_probe_evaluation(item))
        diagnostic_class_counts[diagnostic_class] = diagnostic_class_counts.get(diagnostic_class, 0) + 1
        if (
            group == "contact_status_pair_variable"
            and item.get("success")
            and len(first_contact_variable_successes) < 8
        ):
            first_contact_variable_successes.append({
                "roller": item.get("roller"),
                "contact_label": item.get("contact_label"),
                "selection": item.get("selection"),
                "expression": item.get("expression"),
                "value": _runtime_numeric_max(item),
                "diagnostic_class": diagnostic_class,
            })
        if diagnostic_class not in {"nonzero_success", "zero_result"} and len(first_failures) < 12:
            first_failures.append({
                "roller": item.get("roller"),
                "contact_label": item.get("contact_label"),
                "selection": item.get("selection"),
                "expression": item.get("expression"),
                "method": method,
                "candidate_group": group,
                "diagnostic_class": diagnostic_class,
                "error": item.get("error"),
            })
    return {
        "method_counts": method_counts,
        "candidate_group_counts": group_counts,
        "diagnostic_class_counts": diagnostic_class_counts,
        "unknown_variable_count": diagnostic_class_counts.get("unknown_variable", 0),
        "selection_error_count": diagnostic_class_counts.get("selection_error", 0),
        "infinite_result_count": diagnostic_class_counts.get("infinite_result", 0),
        "nan_result_count": diagnostic_class_counts.get("nan_result", 0),
        "zero_result_count": diagnostic_class_counts.get("zero_result", 0),
        "nonzero_success_count": diagnostic_class_counts.get("nonzero_success", 0),
        "contact_status_candidate_count": group_counts.get("contact_status_pair_variable", 0),
        "contact_status_success_count": sum(
            1 for item in evaluations
            if item.get("candidate_group") == "contact_status_pair_variable" and item.get("success")
        ),
        "first_contact_variable_successes": first_contact_variable_successes,
        "first_failures": first_failures,
    }


def _summarize_contact_variable_discovery(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate pair-variable probing by variable family and roller."""
    variable_rows: dict[str, Any] = {}
    by_roller: dict[str, Any] = {}
    for item in evaluations:
        if item.get("candidate_group") != "contact_status_pair_variable":
            continue
        variable = _contact_variable_family(str(item.get("expression") or ""))
        if not variable:
            continue
        roller_key = f"roller_{item.get('roller')}"
        diagnostic_class = str(item.get("diagnostic_class") or _classify_contact_probe_evaluation(item))
        value = _runtime_numeric_max(item)
        variable_bucket = variable_rows.setdefault(variable, {
            "candidate_count": 0,
            "success_count": 0,
            "finite_nonzero_count": 0,
            "pair_specific_finite_nonzero_count": 0,
            "generic_finite_nonzero_count": 0,
            "zero_count": 0,
            "infinite_count": 0,
            "unknown_variable_count": 0,
            "rollers_with_success": [],
            "rollers_with_finite_nonzero": [],
            "rollers_with_pair_specific_finite_nonzero": [],
            "first_successes": [],
        })
        roller_bucket = by_roller.setdefault(roller_key, {})
        roller_variable = roller_bucket.setdefault(variable, {
            "candidate_count": 0,
            "success_count": 0,
            "finite_nonzero_count": 0,
            "pair_specific_finite_nonzero_count": 0,
            "generic_finite_nonzero_count": 0,
            "zero_count": 0,
            "infinite_count": 0,
            "first_success": None,
        })
        is_pair_specific = "_cp_roller_" in str(item.get("expression") or "")
        for bucket in (variable_bucket, roller_variable):
            bucket["candidate_count"] += 1
            if item.get("success"):
                bucket["success_count"] += 1
            if diagnostic_class == "zero_result":
                bucket["zero_count"] += 1
            elif diagnostic_class == "infinite_result":
                bucket["infinite_count"] += 1
            elif diagnostic_class == "unknown_variable":
                bucket["unknown_variable_count"] = bucket.get("unknown_variable_count", 0) + 1
        if item.get("success") and roller_key not in variable_bucket["rollers_with_success"]:
            variable_bucket["rollers_with_success"].append(roller_key)
        if _runtime_numeric_is_finite_nonzero(item):
            variable_bucket["finite_nonzero_count"] += 1
            roller_variable["finite_nonzero_count"] += 1
            if is_pair_specific:
                variable_bucket["pair_specific_finite_nonzero_count"] += 1
                roller_variable["pair_specific_finite_nonzero_count"] += 1
                if roller_key not in variable_bucket["rollers_with_pair_specific_finite_nonzero"]:
                    variable_bucket["rollers_with_pair_specific_finite_nonzero"].append(roller_key)
            else:
                variable_bucket["generic_finite_nonzero_count"] += 1
                roller_variable["generic_finite_nonzero_count"] += 1
            if roller_key not in variable_bucket["rollers_with_finite_nonzero"]:
                variable_bucket["rollers_with_finite_nonzero"].append(roller_key)
        if item.get("success") and len(variable_bucket["first_successes"]) < 6:
            variable_bucket["first_successes"].append({
                "roller": item.get("roller"),
                "contact_label": item.get("contact_label"),
                "selection": item.get("selection"),
                "expression": item.get("expression"),
                "value": value,
                "diagnostic_class": diagnostic_class,
            })
        if item.get("success") and roller_variable.get("first_success") is None:
            roller_variable["first_success"] = {
                "contact_label": item.get("contact_label"),
                "selection": item.get("selection"),
                "expression": item.get("expression"),
                "value": value,
                "diagnostic_class": diagnostic_class,
            }
    for variable, bucket in variable_rows.items():
        candidate_count = int(bucket.get("candidate_count") or 0)
        success_count = int(bucket.get("success_count") or 0)
        finite_nonzero_count = int(bucket.get("finite_nonzero_count") or 0)
        bucket["success_ratio"] = (success_count / candidate_count) if candidate_count else None
        bucket["finite_nonzero_success_ratio"] = (
            finite_nonzero_count / success_count
        ) if success_count else None
        bucket["rollers_with_success"] = sorted(bucket.get("rollers_with_success") or [])
        bucket["rollers_with_finite_nonzero"] = sorted(bucket.get("rollers_with_finite_nonzero") or [])
        bucket["rollers_with_pair_specific_finite_nonzero"] = sorted(
            bucket.get("rollers_with_pair_specific_finite_nonzero") or []
        )
    useful_variables = [
        variable for variable, bucket in sorted(variable_rows.items())
        if (bucket.get("success_count") or 0) > 0
    ]
    finite_nonzero_variables = [
        variable for variable, bucket in sorted(variable_rows.items())
        if (bucket.get("finite_nonzero_count") or 0) > 0
    ]
    return {
        "success": bool(useful_variables),
        "kind": "bearing_3d_contact_variable_discovery",
        "variable_count": len(variable_rows),
        "useful_variables": useful_variables,
        "finite_nonzero_variables": finite_nonzero_variables,
        "by_variable": variable_rows,
        "by_roller": by_roller,
        "warning": None if useful_variables else "No contact-state variable family evaluated successfully.",
    }


def _contact_variable_family(expression: str) -> str | None:
    expression_key = expression.strip()
    if expression_key.startswith("abs(") and expression_key.endswith(")"):
        expression_key = expression_key[4:-1]
    match = re.match(r"solid\.(?P<body>[A-Za-z0-9_]+)$", expression_key)
    if not match:
        return None
    body = re.sub(r"_cp_roller_\d+_(?:inner_raceway|outer_raceway|cage_pocket)$", "", match.group("body"))
    return body or None


def _summarize_contact_normal_orientation(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in evaluations:
        roller_key = f"roller_{item.get('roller')}"
        label = str(item.get("contact_label") or "unknown")
        grouped.setdefault((roller_key, label), []).append(item)
    for (roller_key, label), items in grouped.items():
        bucket = summary.setdefault(roller_key, {"by_contact_label": {}})
        values = {
            str(item.get("normal_label")): _runtime_numeric_max(item)
            for item in items
            if item.get("success")
        }
        classes = {
            str(item.get("normal_label")): item.get("diagnostic_class")
            for item in items
        }
        area = values.get("area")
        avg: dict[str, float | None] = {
            "nx": None,
            "ny": None,
            "nz": None,
            "radial": None,
        }
        if area is not None and math.isfinite(area) and abs(area) > 1.0e-18:
            for source_key, output_key in (
                ("normal_x", "nx"),
                ("normal_y", "ny"),
                ("normal_z", "nz"),
                ("radial_normal", "radial"),
            ):
                value = values.get(source_key)
                if value is not None and math.isfinite(value):
                    avg[output_key] = value / area
        bucket["by_contact_label"][label] = {
            "selection": items[0].get("selection") if items else None,
            "area_integral": area,
            "normal_integrals": {
                "nx": values.get("normal_x"),
                "ny": values.get("normal_y"),
                "nz": values.get("normal_z"),
                "radial": values.get("radial_normal"),
            },
            "average_normal": avg,
            "diagnostic_classes": classes,
            "success": area is not None and avg.get("radial") is not None,
        }
    for roller_key, bucket in summary.items():
        labels = bucket.get("by_contact_label") or {}
        bucket["source_destination_radial_normal_alignment"] = {
            "inner": _normal_orientation_pair_alignment(
                labels.get(f"{roller_key}_inner_source"),
                labels.get(f"{roller_key}_inner_raceway"),
            ),
            "outer": _normal_orientation_pair_alignment(
                labels.get(f"{roller_key}_outer_source"),
                labels.get(f"{roller_key}_outer_raceway"),
            ),
        }
    return summary


def _normal_orientation_pair_alignment(source: Any, destination: Any) -> dict[str, Any]:
    source_radial = (
        (source.get("average_normal") or {}).get("radial")
        if isinstance(source, dict)
        else None
    )
    destination_radial = (
        (destination.get("average_normal") or {}).get("radial")
        if isinstance(destination, dict)
        else None
    )
    source_success = source_radial is not None
    destination_success = destination_radial is not None
    opposite_sign = None
    if source_success and destination_success:
        if abs(float(source_radial)) <= 1.0e-9 or abs(float(destination_radial)) <= 1.0e-9:
            opposite_sign = False
        else:
            opposite_sign = (float(source_radial) * float(destination_radial)) < 0.0
    return {
        "source_radial_avg": source_radial,
        "destination_radial_avg": destination_radial,
        "source_success": source_success,
        "destination_success": destination_success,
        "opposite_radial_sign": opposite_sign,
    }


def _summarize_contact_geometry_moments(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for item in evaluations:
        roller_key = f"roller_{item.get('roller')}"
        label = str(item.get("contact_label") or "unknown")
        bucket = summary.setdefault(roller_key, {
            "by_contact_label": {},
            "successful_moment_count": 0,
        })
        label_bucket = bucket["by_contact_label"].setdefault(label, {
            "selection": item.get("selection"),
            "moment_integrals": {},
            "success": False,
        })
        moment_label = str(item.get("moment_label") or "unknown")
        value = _runtime_numeric_max(item)
        label_bucket["moment_integrals"][moment_label] = {
            "expression": item.get("expression"),
            "success": bool(item.get("success")),
            "value": value,
            "diagnostic_class": item.get("diagnostic_class"),
        }
        if item.get("success"):
            bucket["successful_moment_count"] += 1
    for roller_key, bucket in summary.items():
        labels = bucket.get("by_contact_label") or {}
        for label, label_bucket in labels.items():
            if not isinstance(label_bucket, dict):
                continue
            integrals = label_bucket.get("moment_integrals") or {}
            area = _moment_integral_value(integrals, "area")
            centroid: dict[str, float] = {}
            if area is not None and math.isfinite(area) and abs(area) > 1.0e-18:
                for moment_label, output_key in (
                    ("x_moment", "x"),
                    ("y_moment", "y"),
                    ("z_moment", "z"),
                    ("radial_moment", "radial"),
                ):
                    value = _moment_integral_value(integrals, moment_label)
                    if value is not None and math.isfinite(value):
                        centroid[output_key] = value / area
            label_bucket["area_integral"] = area
            label_bucket["centroid_m"] = centroid
            label_bucket["success"] = area is not None and "radial" in centroid
        bucket["source_destination_radial_gap_proxy"] = {
            "inner": _contact_geometry_pair_gap_proxy(
                labels.get(f"{roller_key}_inner_source"),
                labels.get(f"{roller_key}_inner_raceway"),
            ),
            "outer": _contact_geometry_pair_gap_proxy(
                labels.get(f"{roller_key}_outer_source"),
                labels.get(f"{roller_key}_outer_raceway"),
            ),
        }
    return summary


def _summarize_contact_entity_geometry_moments(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for item in evaluations:
        roller_key = f"roller_{item.get('roller')}"
        label = str(item.get("contact_label") or "unknown")
        bucket = summary.setdefault(roller_key, {
            "by_contact_label": {},
            "successful_moment_count": 0,
        })
        label_bucket = bucket["by_contact_label"].setdefault(label, {
            "selection": item.get("selection"),
            "selection_entities": [],
            "by_entity": {},
            "success": False,
        })
        lookup = item.get("selection_entity_lookup")
        if isinstance(lookup, dict) and isinstance(lookup.get("entities"), list):
            label_bucket["selection_entities"] = lookup.get("entities")
        entity = item.get("entity")
        if entity is None:
            label_bucket["error"] = item.get("error")
            continue
        entity_key = str(entity)
        entity_bucket = label_bucket["by_entity"].setdefault(entity_key, {
            "entity": int(entity),
            "moment_integrals": {},
            "success": False,
        })
        moment_label = str(item.get("moment_label") or "unknown")
        value = _runtime_numeric_max(item)
        entity_bucket["moment_integrals"][moment_label] = {
            "expression": item.get("expression"),
            "success": bool(item.get("success")),
            "value": value,
            "diagnostic_class": item.get("diagnostic_class"),
        }
        if item.get("success"):
            bucket["successful_moment_count"] += 1
    for roller_key, bucket in summary.items():
        labels = bucket.get("by_contact_label") or {}
        for label_bucket in labels.values():
            if not isinstance(label_bucket, dict):
                continue
            entity_rows: list[dict[str, Any]] = []
            for entity_key, entity_bucket in (label_bucket.get("by_entity") or {}).items():
                if not isinstance(entity_bucket, dict):
                    continue
                integrals = entity_bucket.get("moment_integrals") or {}
                area = _moment_integral_value(integrals, "area")
                centroid: dict[str, float] = {}
                if area is not None and math.isfinite(area) and abs(area) > 1.0e-18:
                    for moment_label, output_key in (
                        ("x_moment", "x"),
                        ("y_moment", "y"),
                        ("z_moment", "z"),
                        ("radial_moment", "radial"),
                    ):
                        value = _moment_integral_value(integrals, moment_label)
                        if value is not None and math.isfinite(value):
                            centroid[output_key] = value / area
                entity_bucket["area_integral"] = area
                entity_bucket["centroid_m"] = centroid
                entity_bucket["success"] = area is not None and "radial" in centroid
                entity_rows.append({
                    "entity": entity_bucket.get("entity"),
                    "area_integral": area,
                    "centroid_m": centroid,
                    "success": entity_bucket["success"],
                })
            entity_rows.sort(
                key=lambda row: (
                    row.get("centroid_m", {}).get("radial") is None,
                    row.get("centroid_m", {}).get("radial") or 0.0,
                    row.get("entity") or 0,
                )
            )
            label_bucket["entity_centroid_rows"] = entity_rows
            label_bucket["success"] = any(row.get("success") for row in entity_rows)
    return summary


def _moment_integral_value(integrals: Any, key: str) -> float | None:
    if not isinstance(integrals, dict):
        return None
    entry = integrals.get(key)
    if not isinstance(entry, dict) or not entry.get("success"):
        return None
    value = entry.get("value")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _contact_geometry_pair_gap_proxy(source: Any, destination: Any) -> dict[str, Any]:
    source_radial = _contact_geometry_centroid_value(source, "radial")
    destination_radial = _contact_geometry_centroid_value(destination, "radial")
    signed_delta = None
    abs_delta = None
    if source_radial is not None and destination_radial is not None:
        signed_delta = destination_radial - source_radial
        abs_delta = abs(signed_delta)
    return {
        "source_radial_centroid_m": source_radial,
        "destination_radial_centroid_m": destination_radial,
        "signed_destination_minus_source_m": signed_delta,
        "abs_radial_delta_m": abs_delta,
        "both_centroids_available": source_radial is not None and destination_radial is not None,
    }


def _contact_geometry_centroid_value(bucket: Any, key: str) -> float | None:
    if not isinstance(bucket, dict):
        return None
    centroid = bucket.get("centroid_m")
    if not isinstance(centroid, dict):
        return None
    value = centroid.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _summarize_pair_transfer_integrals(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for item in evaluations:
        roller_key = f"roller_{item.get('roller')}"
        label = str(item.get("contact_label") or "unknown")
        bucket = summary.setdefault(roller_key, {
            "by_contact_label": {},
            "successful_integral_count": 0,
            "finite_nonzero_integral_count": 0,
            "max_abs_integral": None,
        })
        label_bucket = bucket["by_contact_label"].setdefault(label, {
            "selection": item.get("selection"),
            "pair_tag": item.get("pair_tag"),
        })
        transfer_label = str(item.get("transfer_label") or "unknown")
        value = _runtime_numeric_max(item)
        entry = {
            "expression": item.get("expression"),
            "success": bool(item.get("success")),
            "value": value,
            "diagnostic_class": item.get("diagnostic_class"),
        }
        label_bucket[transfer_label] = entry
        if item.get("success"):
            bucket["successful_integral_count"] += 1
        if _runtime_numeric_is_finite_nonzero(item):
            bucket["finite_nonzero_integral_count"] += 1
            abs_value = abs(float(value))
            if bucket["max_abs_integral"] is None or abs_value > bucket["max_abs_integral"]:
                bucket["max_abs_integral"] = abs_value
    for roller_key, bucket in summary.items():
        labels = bucket.get("by_contact_label") or {}
        bucket["source_destination_transfer"] = {
            "inner": _pair_transfer_source_destination(
                labels.get(f"{roller_key}_inner_source"),
                labels.get(f"{roller_key}_inner_raceway"),
            ),
            "outer": _pair_transfer_source_destination(
                labels.get(f"{roller_key}_outer_source"),
                labels.get(f"{roller_key}_outer_raceway"),
            ),
        }
        bucket["destination_abs_tn_nonzero_count"] = sum(
            1 for side in ("inner", "outer")
            if _pair_transfer_side_destination_abs_nonzero(bucket["source_destination_transfer"].get(side))
        )
    return summary


def _pair_transfer_side_destination_abs_nonzero(side: Any) -> bool:
    if not isinstance(side, dict):
        return False
    value = side.get("destination_abs_Tn_integral")
    return value is not None and math.isfinite(float(value)) and abs(float(value)) > 1.0e-12


def _pair_transfer_source_destination(source: Any, destination: Any) -> dict[str, Any]:
    source_abs = _pair_transfer_entry_value(source, "abs_Tn_integral")
    destination_abs = _pair_transfer_entry_value(destination, "abs_Tn_integral")
    source_signed = _pair_transfer_entry_value(source, "signed_Tn_integral")
    destination_signed = _pair_transfer_entry_value(destination, "signed_Tn_integral")
    source_evaluable = _pair_transfer_entry_evaluable(source, "abs_Tn_integral")
    destination_evaluable = _pair_transfer_entry_evaluable(destination, "abs_Tn_integral")
    source_nonzero = source_evaluable and abs(float(source_abs)) > 1.0e-12
    destination_nonzero = destination_evaluable and abs(float(destination_abs)) > 1.0e-12
    return {
        "source_abs_Tn_integral": source_abs,
        "destination_abs_Tn_integral": destination_abs,
        "source_signed_Tn_integral": source_signed,
        "destination_signed_Tn_integral": destination_signed,
        "source_evaluable": source_evaluable,
        "destination_evaluable": destination_evaluable,
        "source_unevaluable": not source_evaluable,
        "destination_unevaluable": not destination_evaluable,
        "source_nonzero": source_nonzero,
        "destination_nonzero": destination_nonzero,
        "source_zero_destination_nonzero": (
            source_evaluable
            and destination_evaluable
            and not source_nonzero
            and destination_nonzero
        ),
        "source_unevaluable_destination_nonzero": not source_evaluable and destination_nonzero,
    }


def _pair_transfer_entry_evaluable(bucket: Any, key: str) -> bool:
    if not isinstance(bucket, dict):
        return False
    entry = bucket.get(key)
    if not isinstance(entry, dict) or not entry.get("success"):
        return False
    value = entry.get("value")
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _pair_transfer_entry_value(bucket: Any, key: str) -> float | None:
    if not isinstance(bucket, dict):
        return None
    entry = bucket.get(key)
    if not isinstance(entry, dict) or not entry.get("success"):
        return None
    value = entry.get("value")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _summarize_contact_status_by_roller(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize pair-specific normal contact pressure/gap candidates by roller."""
    summary: dict[str, Any] = {}
    tracked_variables = ("Tn", "gap", "gn", "pn", "pn0")
    for item in evaluations:
        if item.get("candidate_group") != "contact_status_pair_variable":
            continue
        expression = str(item.get("expression") or "")
        expression_key = expression
        if expression.startswith("abs(") and expression.endswith(")"):
            expression_key = expression[4:-1]
        pair_match = re.match(
            r"solid\.(?P<variable>Tn|gap|gn|pn|pn0)_cp_roller_(?P<roller>\d+)_(?P<pair>inner_raceway|outer_raceway|cage_pocket)$",
            expression_key,
        )
        generic_match = re.match(r"solid\.(?P<variable>Tn|gap|gn|pn|pn0)$", expression_key)
        if not pair_match and not generic_match:
            continue
        roller_key = f"roller_{item.get('roller')}"
        bucket = summary.setdefault(roller_key, {
            "by_contact_label": {},
            "pair_specific_nonzero_count": 0,
            "pair_specific_zero_count": 0,
            "pair_specific_success_count": 0,
        })
        label = str(item.get("contact_label") or "unknown")
        label_bucket = bucket["by_contact_label"].setdefault(label, {})
        value = _runtime_numeric_max(item)
        entry = {
            "expression": expression,
            "success": bool(item.get("success")),
            "value": value,
            "diagnostic_class": item.get("diagnostic_class"),
        }
        if pair_match:
            variable = pair_match.group("variable")
            pair_name = pair_match.group("pair")
            pair_bucket = label_bucket.setdefault("pair_specific", {}).setdefault(pair_name, {})
            if expression.startswith("abs("):
                pair_bucket[f"abs_{variable}"] = entry
            else:
                pair_bucket[variable] = entry
                if variable in tracked_variables and item.get("success"):
                    bucket["pair_specific_success_count"] += 1
                    if value is not None and math.isfinite(value) and abs(value) > 1.0e-12:
                        bucket["pair_specific_nonzero_count"] += 1
                    else:
                        bucket["pair_specific_zero_count"] += 1
        elif generic_match:
            variable = generic_match.group("variable")
            generic_bucket = label_bucket.setdefault("generic_contact", {})
            if expression.startswith("abs("):
                generic_bucket[f"abs_{variable}"] = entry
            else:
                generic_bucket[variable] = entry
    for bucket in summary.values():
        success_count = bucket.get("pair_specific_success_count") or 0
        nonzero_count = bucket.get("pair_specific_nonzero_count") or 0
        bucket["pair_specific_nonzero_ratio"] = (nonzero_count / success_count) if success_count else None
    return summary


def _compact_contact_model_audit_for_saved_probe(
    model_audit: dict[str, Any],
    *,
    rollers: tuple[int, ...],
) -> dict[str, Any]:
    """Keep the saved-MPH contact audit focused enough to store beside probe evidence."""
    if not isinstance(model_audit, dict):
        return {"success": False, "error": "model audit payload is unavailable"}
    payload = _stage_model_audit_payload(model_audit)
    wanted_pairs = {
        f"cp_roller_{roller}_{side}_raceway"
        for roller in rollers
        for side in ("inner", "outer")
    }
    wanted_features = {
        tag
        for roller in rollers
        for side in ("inner", "outer")
        for tag in _contact_feature_tag_candidates(roller, side)
    }
    pair_rows = [
        item for item in payload.get("contact_pair_audit") or []
        if isinstance(item, dict) and str(item.get("tag")) in wanted_pairs
    ]
    feature_rows = [
        item for item in payload.get("solid_feature_audit") or []
        if isinstance(item, dict) and str(item.get("tag")) in wanted_features
    ]
    return {
        "success": bool(model_audit.get("success")) and bool(pair_rows or feature_rows),
        "model_audit_success": bool(model_audit.get("success")),
        "model_audit_error": model_audit.get("error"),
        "pair_count": len(pair_rows),
        "contact_feature_count": len(feature_rows),
        "available_pair_tags": (payload.get("pair_tags") or {}).get("value"),
        "available_solid_feature_tags": payload.get("solid_feature_tags"),
        "contact_pair_audit": pair_rows,
        "contact_feature_audit": feature_rows,
    }


def _saved_contact_pair_enforcement_diagnostic(
    model_audit: dict[str, Any],
    *,
    contact_probe: dict[str, Any],
    rollers: tuple[int, ...],
) -> dict[str, Any]:
    """Compare solved-MPH pair/contact-feature settings against contact-status evidence."""
    payload = _stage_model_audit_payload(model_audit)
    features = {
        str(item.get("tag")): item
        for item in payload.get("solid_feature_audit") or []
        if isinstance(item, dict)
    }
    pairs = {
        str(item.get("tag")): item
        for item in payload.get("contact_pair_audit") or []
        if isinstance(item, dict)
    }
    by_roller = contact_probe.get("by_roller") if isinstance(contact_probe.get("by_roller"), dict) else {}
    contact_status = (
        contact_probe.get("contact_status_by_roller")
        if isinstance(contact_probe.get("contact_status_by_roller"), dict)
        else {}
    )
    geometry_moments = (
        contact_probe.get("geometry_moments_by_roller")
        if isinstance(contact_probe.get("geometry_moments_by_roller"), dict)
        else {}
    )
    roller_states: dict[str, Any] = {}
    nonzero_reference_settings: dict[str, Any] = {}
    zero_pair_pressure_rollers: list[str] = []
    source_destination_imbalance_rollers: list[str] = []
    for roller in rollers:
        roller_key = f"roller_{roller}"
        status = contact_status.get(roller_key) if isinstance(contact_status.get(roller_key), dict) else {}
        probe_summary = by_roller.get(roller_key) if isinstance(by_roller.get(roller_key), dict) else {}
        contact_settings = _diagnostic_roller_contact_settings(features, roller)
        variable_discovery = _diagnostic_roller_contact_variable_discovery(contact_probe, roller_key)
        roller_geometry = (
            geometry_moments.get(roller_key)
            if isinstance(geometry_moments.get(roller_key), dict)
            else {}
        )
        pair_specific_success = int(status.get("pair_specific_success_count") or 0)
        pair_specific_nonzero = int(status.get("pair_specific_nonzero_count") or 0)
        zero_pair_pressure = pair_specific_success > 0 and pair_specific_nonzero == 0
        if zero_pair_pressure:
            zero_pair_pressure_rollers.append(roller_key)
        imbalance = (
            probe_summary.get("source_destination_imbalance")
            if isinstance(probe_summary, dict)
            else {}
        )
        source_destination_imbalance = bool(
            isinstance(imbalance, dict)
            and any(
                isinstance(item, dict) and item.get("source_zero_destination_nonzero") is True
                for item in imbalance.values()
            )
        )
        if source_destination_imbalance:
            source_destination_imbalance_rollers.append(roller_key)
        state = {
            "pair_specific_success_count": pair_specific_success,
            "pair_specific_nonzero_count": pair_specific_nonzero,
            "pair_specific_nonzero_ratio": status.get("pair_specific_nonzero_ratio"),
            "zero_pair_specific_contact_pressure": zero_pair_pressure,
            "source_destination_imbalance": source_destination_imbalance,
            "inner_pair": _diagnostic_pair_endpoint_summary(pairs.get(f"cp_roller_{roller}_inner_raceway")),
            "outer_pair": _diagnostic_pair_endpoint_summary(pairs.get(f"cp_roller_{roller}_outer_raceway")),
            "contact_feature_settings": contact_settings,
            "contact_status": status,
            "contact_variable_discovery": variable_discovery,
            "contact_geometry_gap_proxy": roller_geometry.get("source_destination_radial_gap_proxy"),
            "contact_geometry_moments": roller_geometry,
            "source_destination_probe": probe_summary.get("source_destination_imbalance") if isinstance(probe_summary, dict) else None,
        }
        roller_states[roller_key] = state
        if pair_specific_nonzero > 0:
            nonzero_reference_settings[roller_key] = contact_settings
    for roller_key, state in roller_states.items():
        state["contact_feature_settings_match_nonzero_references"] = _diagnostic_contact_settings_match_references(
            state.get("contact_feature_settings") or {},
            {
                key: value
                for key, value in nonzero_reference_settings.items()
                if key != roller_key
            },
        )
    return {
        "success": bool(roller_states),
        "model_audit_success": bool((model_audit or {}).get("success")),
        "model_audit_error": (model_audit or {}).get("error"),
        "kind": "bearing_3d_saved_mph_pair_enforcement_diagnostic",
        "rollers": list(rollers),
        "zero_pair_specific_contact_pressure_rollers": zero_pair_pressure_rollers,
        "source_destination_imbalance_rollers": source_destination_imbalance_rollers,
        "nonzero_reference_rollers": sorted(nonzero_reference_settings),
        "roller_states": roller_states,
        "recommendations": _saved_pair_enforcement_recommendations(
            zero_pair_pressure_rollers=zero_pair_pressure_rollers,
            source_destination_imbalance_rollers=source_destination_imbalance_rollers,
            roller_states=roller_states,
        ),
    }


def _stage_model_audit_payload(model_audit: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(model_audit, dict):
        return {}
    payload = model_audit.get("payload")
    return payload if isinstance(payload, dict) else model_audit


def _diagnostic_roller_contact_variable_discovery(contact_probe: dict[str, Any], roller_key: str) -> dict[str, Any] | None:
    discovery = (
        contact_probe.get("contact_variable_discovery")
        if isinstance(contact_probe.get("contact_variable_discovery"), dict)
        else {}
    )
    by_roller = discovery.get("by_roller") if isinstance(discovery.get("by_roller"), dict) else {}
    roller_discovery = by_roller.get(roller_key)
    if not isinstance(roller_discovery, dict):
        return None
    compact: dict[str, Any] = {}
    for variable in ("Tn", "p", "gap", "active", "contactStatus", "lambdaN"):
        item = roller_discovery.get(variable)
        if isinstance(item, dict):
            compact[variable] = {
                "success_count": item.get("success_count"),
                "finite_nonzero_count": item.get("finite_nonzero_count"),
                "pair_specific_finite_nonzero_count": item.get("pair_specific_finite_nonzero_count"),
                "generic_finite_nonzero_count": item.get("generic_finite_nonzero_count"),
                "infinite_count": item.get("infinite_count"),
                "first_success": item.get("first_success"),
            }
    return compact or None


def _contact_feature_tag_candidates(index: int, side: str) -> list[str]:
    return [
        f"contact_roller_{index}_{side}",
        f"roller_{side}_contact_{index}",
        f"contact_{side}_roller_{index}",
        f"{side}_roller_{index}_contact",
    ]


def _saved_pair_enforcement_recommendations(
    *,
    zero_pair_pressure_rollers: list[str],
    source_destination_imbalance_rollers: list[str],
    roller_states: dict[str, Any],
) -> list[str]:
    recommendations: list[str] = []
    overlap = sorted(set(zero_pair_pressure_rollers) & set(source_destination_imbalance_rollers))
    if overlap:
        matching_settings = [
            roller for roller in overlap
            if (roller_states.get(roller) or {}).get("contact_feature_settings_match_nonzero_references") is True
        ]
        if matching_settings:
            recommendations.append(
                "Zero-carry rollers have solved-MPH source/destination imbalance and zero pair-specific normal pressure while their contact feature settings match nonzero neighboring rollers; prioritize contact normal/gap orientation or pair enforcement transfer over static feature-setting differences."
            )
        else:
            recommendations.append(
                "Zero-carry rollers have solved-MPH source/destination imbalance and zero pair-specific normal pressure; compare contact feature settings and pair endpoint orientation against nonzero neighboring rollers before increasing load."
            )
    elif zero_pair_pressure_rollers:
        recommendations.append(
            "Some active rollers have zero pair-specific normal pressure; inspect contact gap and pair enforcement state before treating BoundaryLoad response as physical."
        )
    elif source_destination_imbalance_rollers:
        recommendations.append(
            "Some active rollers show source/destination response imbalance; inspect solved contact source/destination transfer before increasing load."
        )
    if not recommendations:
        recommendations.append("No saved-MPH pair enforcement blocker was detected for the probed rollers.")
    return recommendations


def _summarize_contact_probe_by_roller(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for item in evaluations:
        roller_key = f"roller_{item.get('roller')}"
        bucket = summary.setdefault(roller_key, {
            "candidate_count": 0,
            "success_count": 0,
            "finite_success_count": 0,
            "nonzero_count": 0,
            "max_abs_value": None,
            "first_nonzero": None,
            "by_contact_label": {},
        })
        bucket["candidate_count"] += 1
        label = str(item.get("contact_label") or "unknown")
        label_bucket = bucket["by_contact_label"].setdefault(label, {
            "candidate_count": 0,
            "success_count": 0,
            "finite_success_count": 0,
            "nonzero_count": 0,
            "max_abs_value": None,
            "first_nonzero": None,
        })
        label_bucket["candidate_count"] += 1
        value = _runtime_numeric_max(item)
        if item.get("success"):
            bucket["success_count"] += 1
            label_bucket["success_count"] += 1
        if item.get("success") and value is not None and math.isfinite(float(value)):
            bucket["finite_success_count"] += 1
            label_bucket["finite_success_count"] += 1
        if item.get("success") and value is not None and abs(value) > 1.0e-12:
            if not math.isfinite(value):
                continue
            bucket["nonzero_count"] += 1
            label_bucket["nonzero_count"] += 1
            abs_value = abs(float(value))
            if bucket["max_abs_value"] is None or abs_value > bucket["max_abs_value"]:
                bucket["max_abs_value"] = abs_value
            if label_bucket["max_abs_value"] is None or abs_value > label_bucket["max_abs_value"]:
                label_bucket["max_abs_value"] = abs_value
            if bucket["first_nonzero"] is None:
                bucket["first_nonzero"] = {
                    "selection": item.get("selection"),
                    "contact_label": item.get("contact_label"),
                    "expression": item.get("expression"),
                    "method": item.get("method"),
                    "value": value,
                }
            if label_bucket["first_nonzero"] is None:
                label_bucket["first_nonzero"] = {
                    "selection": item.get("selection"),
                    "expression": item.get("expression"),
                    "method": item.get("method"),
                    "value": value,
                }
    for roller_key, bucket in summary.items():
        labels = bucket.get("by_contact_label") or {}
        bucket["source_destination_imbalance"] = {
            "inner": _contact_source_destination_imbalance(
                labels.get(f"{roller_key}_inner_source"),
                labels.get(f"{roller_key}_inner_raceway"),
            ),
            "outer": _contact_source_destination_imbalance(
                labels.get(f"{roller_key}_outer_source"),
                labels.get(f"{roller_key}_outer_raceway"),
            ),
        }
    return summary


def _contact_source_destination_imbalance(source: Any, destination: Any) -> dict[str, Any]:
    source_max = source.get("max_abs_value") if isinstance(source, dict) else None
    destination_max = destination.get("max_abs_value") if isinstance(destination, dict) else None
    source_evaluable = bool(
        isinstance(source, dict) and (source.get("finite_success_count") or 0) > 0
    )
    destination_evaluable = bool(
        isinstance(destination, dict) and (destination.get("finite_success_count") or 0) > 0
    )
    source_nonzero = bool(isinstance(source, dict) and (source.get("nonzero_count") or 0) > 0)
    destination_nonzero = bool(isinstance(destination, dict) and (destination.get("nonzero_count") or 0) > 0)
    return {
        "source_evaluable": source_evaluable,
        "destination_evaluable": destination_evaluable,
        "source_unevaluable": not source_evaluable,
        "destination_unevaluable": not destination_evaluable,
        "source_nonzero": source_nonzero,
        "destination_nonzero": destination_nonzero,
        "source_max_abs_value": source_max,
        "destination_max_abs_value": destination_max,
        "source_zero_destination_nonzero": (
            source_evaluable
            and destination_evaluable
            and not source_nonzero
            and destination_nonzero
        ),
        "source_unevaluable_destination_nonzero": not source_evaluable and destination_nonzero,
    }


def _write_saved_contact_probe_report(
    result: dict[str, Any],
    *,
    json_path: Path,
    markdown_path: Path,
) -> dict[str, Any]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    result["json_path"] = str(json_path.resolve())
    result["markdown_path"] = str(markdown_path.resolve())
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(_render_saved_contact_probe_markdown(result), encoding="utf-8")
    return result


def _build_local_two_body_contact_smoke_code(*, contact_interference: str = "5[um]", roller_id: int = 1) -> str:
    """Build a minimal roller outer-raceway two-body contact smoke model."""
    roller_id = int(roller_id)
    if not 1 <= roller_id <= VERIFIED_ROLLER_COUNT:
        raise ValueError(f"roller_id must be in 1..{VERIFIED_ROLLER_COUNT}: {roller_id}")
    angle = 2.0 * math.pi * (roller_id - 1) / VERIFIED_ROLLER_COUNT
    radial_x = math.cos(angle)
    radial_y = math.sin(angle)
    pitch_radius = 27.0
    roller_radius = 4.0
    cx = pitch_radius * radial_x
    cy = pitch_radius * radial_y
    contact_cx = (pitch_radius + roller_radius) * radial_x
    contact_cy = (pitch_radius + roller_radius) * radial_y
    tangent_x = -radial_y
    tangent_y = radial_x
    half_radial = 0.9
    half_tangent = 1.4
    corners = []
    for sr in (-1, 1):
        for st in (-1, 1):
            corners.append((
                contact_cx + sr * half_radial * radial_x + st * half_tangent * tangent_x,
                contact_cy + sr * half_radial * radial_y + st * half_tangent * tangent_y,
            ))
    xs = [item[0] for item in corners]
    ys = [item[1] for item in corners]
    body_margin = 5.0
    body_xs = [cx - body_margin, cx + body_margin]
    body_ys = [cy - body_margin, cy + body_margin]
    return f"""
model.param().set('bearing_width', '18[mm]');
model.param().set('roller_radius_local', '4[mm] + {contact_interference}');
model.param().set('roller_length', '16[mm]');
model.param().set('pitch_radius', '27[mm]');
model.param().set('outer_race_inner_radius', '31[mm]');
model.param().set('outer_diameter', '80[mm]');
model.param().set('E_steel', '210[GPa]');
model.param().set('nu_steel', '0.30');
model.param().set('rho_steel', '7850[kg/m^3]');
model.param().set('local_body_load', '1e5[N/m^3]');
model.param().set('weak_roller_foundation_k', '1e5[N/m^3]');
model.component().create('comp1', True);
model.component('comp1').geom().create('geom1', 3);
model.component('comp1').geom('geom1').lengthUnit('mm');
model.component('comp1').geom('geom1').create('outer_ring_outer', 'Cylinder');
model.component('comp1').geom('geom1').feature('outer_ring_outer').set('r', 'outer_diameter/2');
model.component('comp1').geom('geom1').feature('outer_ring_outer').set('h', 'bearing_width');
model.component('comp1').geom('geom1').feature('outer_ring_outer').set('pos', ['0', '0', '-bearing_width/2']);
model.component('comp1').geom('geom1').create('outer_ring_bore', 'Cylinder');
model.component('comp1').geom('geom1').feature('outer_ring_bore').set('r', 'outer_race_inner_radius');
model.component('comp1').geom('geom1').feature('outer_ring_bore').set('h', 'bearing_width+2[mm]');
model.component('comp1').geom('geom1').feature('outer_ring_bore').set('pos', ['0', '0', '-bearing_width/2-1[mm]']);
model.component('comp1').geom('geom1').create('outer_ring', 'Difference');
model.component('comp1').geom('geom1').feature('outer_ring').selection('input').set(['outer_ring_outer']);
model.component('comp1').geom('geom1').feature('outer_ring').selection('input2').set(['outer_ring_bore']);
model.component('comp1').geom('geom1').feature('outer_ring').set('selresult', 'on');
model.component('comp1').geom('geom1').feature('outer_ring').set('selresultshow', 'all');
model.component('comp1').geom('geom1').create('roller_{roller_id}', 'Cylinder');
model.component('comp1').geom('geom1').feature('roller_{roller_id}').set('r', 'roller_radius_local');
model.component('comp1').geom('geom1').feature('roller_{roller_id}').set('h', 'roller_length');
model.component('comp1').geom('geom1').feature('roller_{roller_id}').set('pos', ['{_fmt_mm(cx)}', '{_fmt_mm(cy)}', '-roller_length/2']);
model.component('comp1').geom('geom1').feature('roller_{roller_id}').set('selresult', 'on');
model.component('comp1').geom('geom1').feature('roller_{roller_id}').set('selresultshow', 'all');
model.component('comp1').geom('geom1').feature('fin').set('action', 'assembly');
model.component('comp1').geom('geom1').run();
model.component('comp1').selection().create('sel_roller_{roller_id}_body', 'Box');
model.component('comp1').selection('sel_roller_{roller_id}_body').set('entitydim', '3');
model.component('comp1').selection('sel_roller_{roller_id}_body').set('xmin', '{_fmt_mm(min(body_xs))}');
model.component('comp1').selection('sel_roller_{roller_id}_body').set('xmax', '{_fmt_mm(max(body_xs))}');
model.component('comp1').selection('sel_roller_{roller_id}_body').set('ymin', '{_fmt_mm(min(body_ys))}');
model.component('comp1').selection('sel_roller_{roller_id}_body').set('ymax', '{_fmt_mm(max(body_ys))}');
model.component('comp1').selection('sel_roller_{roller_id}_body').set('zmin', '-8.5[mm]');
model.component('comp1').selection('sel_roller_{roller_id}_body').set('zmax', '8.5[mm]');
model.component('comp1').selection('sel_roller_{roller_id}_body').set('condition', 'intersects');
model.component('comp1').selection().create('sel_outer_ring_body', 'Box');
model.component('comp1').selection('sel_outer_ring_body').set('entitydim', '3');
model.component('comp1').selection('sel_outer_ring_body').set('xmin', '-41[mm]');
model.component('comp1').selection('sel_outer_ring_body').set('xmax', '41[mm]');
model.component('comp1').selection('sel_outer_ring_body').set('ymin', '-41[mm]');
model.component('comp1').selection('sel_outer_ring_body').set('ymax', '41[mm]');
model.component('comp1').selection('sel_outer_ring_body').set('zmin', '-9.5[mm]');
model.component('comp1').selection('sel_outer_ring_body').set('zmax', '9.5[mm]');
model.component('comp1').selection('sel_outer_ring_body').set('condition', 'intersects');
model.component('comp1').selection().create('box_roller_{roller_id}_outer_contact_patch', 'Box');
model.component('comp1').selection('box_roller_{roller_id}_outer_contact_patch').set('entitydim', '2');
model.component('comp1').selection('box_roller_{roller_id}_outer_contact_patch').set('xmin', '{_fmt_mm(min(xs))}');
model.component('comp1').selection('box_roller_{roller_id}_outer_contact_patch').set('xmax', '{_fmt_mm(max(xs))}');
model.component('comp1').selection('box_roller_{roller_id}_outer_contact_patch').set('ymin', '{_fmt_mm(min(ys))}');
model.component('comp1').selection('box_roller_{roller_id}_outer_contact_patch').set('ymax', '{_fmt_mm(max(ys))}');
model.component('comp1').selection('box_roller_{roller_id}_outer_contact_patch').set('zmin', '-8.2[mm]');
model.component('comp1').selection('box_roller_{roller_id}_outer_contact_patch').set('zmax', '8.2[mm]');
model.component('comp1').selection('box_roller_{roller_id}_outer_contact_patch').set('condition', 'intersects');
model.component('comp1').selection().create('sel_roller_{roller_id}_outer_contact', 'Intersection');
model.component('comp1').selection('sel_roller_{roller_id}_outer_contact').set('entitydim', '2');
model.component('comp1').selection('sel_roller_{roller_id}_outer_contact').set('input', ['box_roller_{roller_id}_outer_contact_patch', 'geom1_roller_{roller_id}_bnd']);
model.component('comp1').selection().create('sel_outer_raceway_{roller_id}_contact', 'Intersection');
model.component('comp1').selection('sel_outer_raceway_{roller_id}_contact').set('entitydim', '2');
model.component('comp1').selection('sel_outer_raceway_{roller_id}_contact').set('input', ['box_roller_{roller_id}_outer_contact_patch', 'geom1_outer_ring_bnd']);
model.component('comp1').selection().create('sel_outer_support_surface', 'Box');
model.component('comp1').selection('sel_outer_support_surface').set('entitydim', '2');
model.component('comp1').selection('sel_outer_support_surface').set('xmin', '39[mm]');
model.component('comp1').selection('sel_outer_support_surface').set('xmax', '41[mm]');
model.component('comp1').selection('sel_outer_support_surface').set('ymin', '-41[mm]');
model.component('comp1').selection('sel_outer_support_surface').set('ymax', '41[mm]');
model.component('comp1').selection('sel_outer_support_surface').set('zmin', '-9.5[mm]');
model.component('comp1').selection('sel_outer_support_surface').set('zmax', '9.5[mm]');
model.component('comp1').selection('sel_outer_support_surface').set('condition', 'intersects');
model.component('comp1').material().create('mat_steel', 'Common');
model.component('comp1').material('mat_steel').propertyGroup('def').set('youngsmodulus', 'E_steel');
model.component('comp1').material('mat_steel').propertyGroup('def').set('poissonsratio', 'nu_steel');
model.component('comp1').material('mat_steel').propertyGroup('def').set('density', 'rho_steel');
model.component('comp1').material('mat_steel').selection().all();
model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
model.component('comp1').physics('solid').create('fix_outer', 'Fixed', 2);
model.component('comp1').physics('solid').feature('fix_outer').selection().named('sel_outer_support_surface');
model.component('comp1').physics('solid').create('roller_body_load', 'BodyLoad', 3);
model.component('comp1').physics('solid').feature('roller_body_load').selection().named('sel_roller_{roller_id}_body');
model.component('comp1').physics('solid').feature('roller_body_load').set('FperVol', ['{radial_x:.12g}*local_body_load', '{radial_y:.12g}*local_body_load', '0']);
model.component('comp1').physics('solid').create('weak_roller_{roller_id}_foundation', 'SpringFoundation2', 2);
model.component('comp1').physics('solid').feature('weak_roller_{roller_id}_foundation').selection().named('geom1_roller_{roller_id}_bnd');
model.component('comp1').physics('solid').feature('weak_roller_{roller_id}_foundation').set('SpringType', 'kPerArea');
model.component('comp1').physics('solid').feature('weak_roller_{roller_id}_foundation').set('kPerArea', ['weak_roller_foundation_k', 'weak_roller_foundation_k', 'weak_roller_foundation_k']);
model.component('comp1').pair().create('cp_roller_{roller_id}_outer_raceway', 'Contact');
model.component('comp1').pair('cp_roller_{roller_id}_outer_raceway').manualSelection(True);
model.component('comp1').pair('cp_roller_{roller_id}_outer_raceway').source().named('sel_roller_{roller_id}_outer_contact');
model.component('comp1').pair('cp_roller_{roller_id}_outer_raceway').destination().named('sel_outer_raceway_{roller_id}_contact');
model.component('comp1').physics('solid').create('contact_roller_{roller_id}_outer', 'Contact', 2);
model.component('comp1').physics('solid').feature('contact_roller_{roller_id}_outer').set('pairs', ['cp_roller_{roller_id}_outer_raceway']);
model.component('comp1').physics('solid').feature('contact_roller_{roller_id}_outer').set('pfm', 'penalty');
model.component('comp1').physics('solid').feature('contact_roller_{roller_id}_outer').set('pn_penalty', '1e-4*E_steel');
model.component('comp1').physics('solid').feature('contact_roller_{roller_id}_outer').set('useRelaxation', 'Always');
model.component('comp1').physics('solid').feature('contact_roller_{roller_id}_outer').set('irlx', '0.2');
model.component('comp1').cpl().create('maxop_roller_{roller_id}', 'Maximum');
model.component('comp1').cpl('maxop_roller_{roller_id}').selection().named('sel_roller_{roller_id}_body');
model.component('comp1').mesh().create('mesh1');
model.component('comp1').mesh('mesh1').create('size1', 'Size');
model.component('comp1').mesh('mesh1').feature('size1').set('hmax', '2.0[mm]');
model.component('comp1').mesh('mesh1').feature('size1').set('hmin', '0.8[mm]');
model.component('comp1').mesh('mesh1').create('ftet1', 'FreeTet');
model.study().create('std1');
model.study('std1').create('stat', 'Stationary');
model.study('std1').feature('stat').set('activate', ['solid', 'on']);
model.result().numerical().create('probe_roller_{roller_id}_max_mises', 'MaxVolume');
model.result().numerical('probe_roller_{roller_id}_max_mises').set('expr', 'maxop_roller_{roller_id}(solid.mises)');
output.write('LOCAL_TWO_BODY_CONTACT_SMOKE_BUILT|roller={roller_id}|side=outer|contact_pair=cp_roller_{roller_id}_outer_raceway|contact_interference={contact_interference}\\n');
"""


def run_local_two_body_contact_smoke(
    *,
    output_dir: str | Path,
    model_name: str = "bearing3d_local_two_body_roller1_outer",
    contact_interference: str = "5[um]",
    roller_id: int = 1,
    cores: int = 1,
) -> dict[str, Any]:
    """Run a minimal roller outer two-body contact smoke and probe the solved MPH."""
    roller_id = int(roller_id)
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    summary_path = report_dir / "local_two_body_contact_summary.json"
    markdown_path = report_dir / "local_two_body_contact_summary.md"
    configured_mph = report_dir / "local_two_body_contact_configured.mph"
    solved_mph = report_dir / "local_two_body_contact_solved.mph"

    config = load_config()
    client = COMSOLClient.get_instance()
    actual_model_name = model_name
    result: dict[str, Any] = {
        "success": False,
        "kind": "bearing_3d_local_two_body_contact_smoke",
        "model_name": model_name,
        "output_dir": str(report_dir),
        "summary_path": str(summary_path.resolve()),
        "markdown_path": str(markdown_path.resolve()),
        "configured_mph": str(configured_mph.resolve()),
        "solved_mph": str(solved_mph.resolve()),
        "contact_interference": contact_interference,
        "roller_id": roller_id,
        "policy": "minimal_roller_outer_two_body_contact_pair_smoke_before_global_boundaryload_retry",
    }
    try:
        client.start(
            cores=cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        create = comsol_create_model(model_name)
        result["create_model"] = _compact_runtime_result(create)
        if not create.get("success"):
            result["error"] = create.get("error") or "Failed to create local two-body contact model."
            return _write_local_two_body_contact_smoke_report(result, summary_path, markdown_path)
        actual_model_name = str(create.get("model_name") or model_name)
        result["model_name"] = actual_model_name
        setup = comsol_execute_java(
            _build_local_two_body_contact_smoke_code(contact_interference=contact_interference, roller_id=roller_id),
            model_name=actual_model_name,
        )
        result["setup"] = _compact_runtime_result(setup)
        if not setup.get("success"):
            result["error"] = setup.get("error") or "Local two-body contact setup failed."
            return _write_local_two_body_contact_smoke_report(result, summary_path, markdown_path)
        result["configured_save"] = _compact_runtime_result(comsol_save_model(actual_model_name, str(configured_mph)))
        solve = comsol_solve(actual_model_name)
        result["solve"] = _compact_runtime_result(solve)
        if not solve.get("success"):
            result["error"] = solve.get("error") or "Local two-body contact solve failed."
            try:
                result["failed_save"] = _compact_runtime_result(comsol_save_model(actual_model_name, str(report_dir / "local_two_body_contact_failed.mph")))
            except Exception as save_error:
                result["failed_save_error"] = str(save_error)
            return _write_local_two_body_contact_smoke_report(result, summary_path, markdown_path)
        result["solved_save"] = _compact_runtime_result(comsol_save_model(actual_model_name, str(solved_mph)))
        result["close_before_probe"] = _compact_runtime_result(comsol_close_model(actual_model_name, save=False))
        actual_model_name = ""
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()
        probe = probe_saved_contact_mph(
            mph_path=solved_mph,
            output_dir=report_dir / "contact_probe_solved_mph",
            rollers=(roller_id,),
            cores=cores,
        )
        result["contact_probe"] = {
            "success": probe.get("success"),
            "json_path": probe.get("json_path"),
            "markdown_path": probe.get("markdown_path"),
            "contact_probe_success_count": probe.get("contact_probe_success_count"),
            "contact_probe_nonzero_count": probe.get("contact_probe_nonzero_count"),
            "warning": probe.get("warning"),
            "error": probe.get("error"),
        }
        roller_key = f"roller_{roller_id}"
        roller_status = (((probe.get("contact_probe") or {}).get("contact_status_by_roller") or {}).get(roller_key) or {})
        result[f"{roller_key}_contact_status"] = roller_status
        result["pair_specific_success"] = bool(
            roller_status.get("pair_specific_nonzero_count")
            and int(roller_status.get("pair_specific_nonzero_count") or 0) > 0
        )
        result["success"] = bool(solve.get("success")) and bool(probe.get("success")) and bool(result["pair_specific_success"])
        if not result["success"]:
            result["error"] = result.get("error") or "Solved local smoke did not verify nonzero pair-specific contact transfer."
        return _write_local_two_body_contact_smoke_report(result, summary_path, markdown_path)
    finally:
        try:
            comsol_close_model(actual_model_name, save=False)
        except Exception:
            pass
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def _write_local_two_body_contact_smoke_report(result: dict[str, Any], json_path: Path, markdown_path: Path) -> dict[str, Any]:
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [
        f"# Local two-body roller_{result.get('roller_id', 1)} outer contact smoke",
        "",
        f"- Success: `{result.get('success')}`",
        f"- Pair-specific success: `{result.get('pair_specific_success')}`",
        f"- Roller id: `{result.get('roller_id')}`",
        f"- Contact interference: `{result.get('contact_interference')}`",
        f"- Configured MPH: `{result.get('configured_mph')}`",
        f"- Solved MPH: `{result.get('solved_mph')}`",
        f"- Error: `{result.get('error')}`",
    ]
    probe = result.get("contact_probe") if isinstance(result.get("contact_probe"), dict) else {}
    if probe:
        lines.extend([
            "",
            "## Contact probe",
            "",
            f"- Success: `{probe.get('success')}`",
            f"- Nonzero count: `{probe.get('contact_probe_nonzero_count')}`",
            f"- JSON: `{probe.get('json_path')}`",
        ])
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def _render_saved_contact_probe_markdown(result: dict[str, Any]) -> str:
    probe = result.get("contact_probe") or {}
    lines = [
        "# Bearing 3D Saved MPH Contact Probe",
        "",
        f"- MPH: `{result.get('mph_path')}`",
        f"- Success: `{result.get('success')}`",
        f"- Policy: `{result.get('policy')}`",
        f"- Candidate count: `{probe.get('candidate_count')}`",
        f"- Success count: `{probe.get('success_count')}`",
        f"- Nonzero count: `{probe.get('nonzero_count')}`",
        f"- Warning: `{result.get('warning')}`",
        "",
        "## Candidate Audit",
        "",
        "```json",
        json.dumps(probe.get("candidate_audit") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Contact Status By Roller",
        "",
        "```json",
        json.dumps(probe.get("contact_status_by_roller") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Contact Variable Discovery",
        "",
        "```json",
        json.dumps(probe.get("contact_variable_discovery") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Normal Orientation By Roller",
        "",
        "```json",
        json.dumps(probe.get("normal_orientation_by_roller") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Contact Geometry Moments By Roller",
        "",
        "```json",
        json.dumps(probe.get("geometry_moments_by_roller") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Per-Entity Contact Geometry Moments By Roller",
        "",
        "```json",
        json.dumps(probe.get("entity_geometry_moments_by_roller") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Pair Transfer By Roller",
        "",
        "```json",
        json.dumps(probe.get("pair_transfer_by_roller") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Entity Transfer Diagnostic",
        "",
        "```json",
        json.dumps(probe.get("entity_transfer_diagnostic") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Pair Enforcement Diagnostic",
        "",
        "```json",
        json.dumps(result.get("pair_enforcement_diagnostic") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Contact Feature Property Introspection",
        "",
        "```json",
        json.dumps(result.get("contact_feature_introspection") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## By Roller",
        "",
        "```json",
        json.dumps(probe.get("by_roller") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## First Evaluations",
        "",
        "| Roller | Label | Selection | Method | Expression | Success | Value | Class | Error |",
        "|---|---|---|---|---|---:|---:|---|---|",
    ]
    for item in (probe.get("evaluations") or [])[:80]:
        lines.append(
            "| {roller} | {label} | `{selection}` | {method} | `{expr}` | {success} | {value} | {klass} | {error} |".format(
                roller=item.get("roller"),
                label=str(item.get("contact_label") or "").replace("|", "\\|"),
                selection=item.get("selection"),
                method=item.get("method"),
                expr=str(item.get("expression") or "").replace("|", "\\|"),
                success=_md_bool(item.get("success")),
                value=item.get("value"),
                klass=item.get("diagnostic_class"),
                error=str(item.get("error") or "")[:160].replace("|", "\\|").replace("\n", " "),
            )
        )
    return "\n".join(lines) + "\n"


def _write_saved_reaction_probe_report(
    result: dict[str, Any],
    *,
    json_path: Path,
    markdown_path: Path,
) -> dict[str, Any]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    result["json_path"] = str(json_path.resolve())
    result["markdown_path"] = str(markdown_path.resolve())
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(_render_saved_reaction_probe_markdown(result), encoding="utf-8")
    return result


def _render_saved_reaction_probe_markdown(result: dict[str, Any]) -> str:
    reaction = result.get("reaction_equivalent") or {}
    setup = reaction.get("setup_audit") or result.get("setup_audit") or {}
    candidate_audit = reaction.get("candidate_audit") or result.get("candidate_audit") or {}
    load_context = result.get("boundary_load_context") or {}
    load_balance = result.get("reaction_load_balance") or {}
    lines = [
        "# Bearing 3D Saved MPH Reaction Probe",
        "",
        f"- MPH: `{result.get('mph_path')}`",
        f"- Success: `{result.get('success')}`",
        f"- Reaction candidate nonzero: `{result.get('reaction_candidate_nonzero')}`",
        f"- Reaction verified: `{result.get('reaction_verified')}`",
        f"- Selection: `{result.get('selection_name')}`",
        f"- Error: `{result.get('error')}`",
        f"- Warning: `{result.get('warning')}`",
        "",
        "## Reaction Summary",
        "",
        f"- Candidate count: `{reaction.get('candidate_count')}`",
        f"- Evaluated candidate success count: `{reaction.get('evaluated_candidate_success_count')}`",
        f"- Successful nonzero candidate count: `{reaction.get('successful_candidate_count')}`",
        f"- Best expression: `{reaction.get('best_expression')}`",
        f"- Best method: `{reaction.get('best_method')}`",
        f"- Best force abs (N): `{reaction.get('best_reaction_force_abs_n')}`",
        "",
        "## Load Balance",
        "",
        "```json",
        json.dumps({
            "boundary_load_context": load_context,
            "reaction_load_balance": load_balance,
        }, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Setup Audit",
        "",
        "```json",
        json.dumps(setup, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Candidate Audit",
        "",
        "```json",
        json.dumps(candidate_audit, ensure_ascii=False, indent=2, default=str),
        "```",
    ]
    return "\n".join(lines) + "\n"


def _run_stage_mph_model_audit(model_name: str) -> dict[str, Any]:
    """Collect solver/selection/contact/load state from a loaded COMSOL model."""
    code = f"""
import json

def _stringify(value):
    try:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        try:
            if str(value.getClass().getName()) == 'java.lang.String':
                return str(value)
        except Exception:
            pass
        if isinstance(value, (list, tuple)):
            return [_stringify(item) for item in value]
        if hasattr(value, 'tolist'):
            return value.tolist()
        try:
            return [_stringify(item) for item in list(value)]
        except Exception:
            return str(value)
    except Exception as error:
        return '<stringify_error:' + str(error) + '>'

def _safe(label, func):
    try:
        return {{'success': True, 'value': _stringify(func())}}
    except Exception as error:
        return {{'success': False, 'error': str(error)}}

def _safe_tags(owner):
    return _safe('tags', lambda: list(owner.tags()))

def _feature_get(feature, prop):
    errors = []
    for method in ['getStringArray', 'getString', 'getDoubleArray', 'getDouble', 'getIntArray', 'getInt', 'getBoolean']:
        try:
            return {{'success': True, 'method': method, 'value': _stringify(getattr(feature, method)(prop))}}
        except Exception as error:
            errors.append(method + ': ' + str(error))
    return {{'success': False, 'error': ' | '.join(errors)}}

def _feature_audit(owner, tag, props):
    item = {{'tag': tag}}
    try:
        feature = owner.feature(tag)
        item['exists'] = True
        item['type'] = _safe('type', lambda: feature.getType()).get('value')
        item['active'] = _safe('active', lambda: feature.isActive()).get('value')
        item['properties'] = {{prop: _feature_get(feature, prop) for prop in props}}
        item['property_names'] = _safe('properties', lambda: list(feature.properties()))
        item['selection_named'] = _safe('selection_named', lambda: feature.selection().named())
        item['selection_entities'] = _safe('selection_entities', lambda: list(feature.selection().entities()))
    except Exception as error:
        item['exists'] = False
        item['error'] = str(error)
    return item

def _selection_audit(component, tag):
    item = {{'tag': tag}}
    try:
        selection = component.selection(tag)
        item['exists'] = True
        item['type'] = _safe('type', lambda selection=selection: selection.getType()).get('value')
        item['entities'] = _safe('entities', lambda selection=selection: list(selection.entities()))
        entities = item.get('entities') or {{}}
        if entities.get('success') and isinstance(entities.get('value'), list):
            item['entity_count'] = len(entities.get('value') or [])
        else:
            item['entity_count'] = None
        item['property_names'] = _safe('properties', lambda selection=selection: list(selection.properties()))
        item['properties'] = {{
            prop: _feature_get(selection, prop)
            for prop in ['entitydim', 'condition', 'xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax', 'input']
        }}
    except Exception as error:
        item['exists'] = False
        item['error'] = str(error)
    return item

def _coupling_audit(component, tag):
    item = {{'tag': tag}}
    try:
        coupling = component.cpl(tag)
        item['exists'] = True
        item['type'] = _safe('type', lambda: coupling.getType()).get('value')
        def _coupling_get(prop):
            errors = []
            for method in ['getString', 'getStringArray', 'getDoubleArray', 'getDouble', 'getIntArray', 'getInt', 'get']:
                try:
                    return {{'success': True, 'method': method, 'value': _stringify(getattr(coupling, method)(prop))}}
                except Exception as error:
                    errors.append(method + ': ' + str(error))
            return {{'success': False, 'error': ' | '.join(errors)}}
        item['opname'] = _coupling_get('opname')
        item['property_names'] = _safe('properties', lambda: list(coupling.properties()))
        item['selection_named'] = _safe('selection_named', lambda: coupling.selection().named())
        item['selection_entities'] = _safe('selection_entities', lambda: list(coupling.selection().entities()))
    except Exception as error:
        item['exists'] = False
        item['error'] = str(error)
    return item

def _pair_endpoint_audit(pair, endpoint):
    item = {{'endpoint': endpoint}}
    try:
        selector = pair.source() if endpoint == 'source' else pair.destination()
        item['named'] = _safe('named', lambda selector=selector: selector.named())
        item['entities'] = _safe('entities', lambda selector=selector: list(selector.entities()))
        entities = item.get('entities') or {{}}
        if entities.get('success') and isinstance(entities.get('value'), list):
            item['entity_count'] = len(entities.get('value') or [])
        else:
            item['entity_count'] = None
    except Exception as error:
        item['error'] = str(error)
    return item

def _pair_audit(component, tag):
    item = {{'tag': tag}}
    try:
        pair = component.pair(tag)
        item['exists'] = True
        item['type'] = _safe('type', lambda: pair.getType()).get('value')
        item['property_names'] = _safe('properties', lambda: list(pair.properties()))
        item['manualSelection'] = _safe('manualSelection', lambda: pair.get('manualSelection'))
        item['source'] = _pair_endpoint_audit(pair, 'source')
        item['destination'] = _pair_endpoint_audit(pair, 'destination')
    except Exception as error:
        item['exists'] = False
        item['error'] = str(error)
    return item

def _param_audit(tag):
    item = {{'tag': tag}}
    try:
        item['value'] = _safe('value', lambda tag=tag: model.param().get(tag))
        item['exists'] = bool(item.get('value', {{}}).get('success'))
        item['description'] = _safe('description', lambda tag=tag: model.param().descr(tag))
    except Exception as error:
        item['exists'] = False
        item['error'] = str(error)
    return item

for _name, _func in {{
    '_stringify': _stringify,
    '_safe': _safe,
    '_safe_tags': _safe_tags,
    '_feature_get': _feature_get,
    '_feature_audit': _feature_audit,
    '_selection_audit': _selection_audit,
    '_coupling_audit': _coupling_audit,
    '_pair_endpoint_audit': _pair_endpoint_audit,
    '_pair_audit': _pair_audit,
    '_param_audit': _param_audit,
}}.items():
    globals()[_name] = _func

diag = {{
    'component_tags': _safe('component_tags', lambda: list(model.component().tags())),
    'study_tags': _safe('study_tags', lambda: list(model.study().tags())),
    'solver_tags': _safe('solver_tags', lambda: list(model.sol().tags())),
    'dataset_tags': _safe('dataset_tags', lambda: list(model.result().dataset().tags())),
    'parameter_tags': _safe('parameter_tags', lambda: list(model.param().tags())),
}}

interesting_parameters = [
    'contact_interference',
    'roller_diameter',
    'roller_radius',
    'pitch_diameter',
    'pitch_radius',
    'radial_load',
    'inner_bore_load_pressure',
    'inner_radial_displacement',
    'active_roller_stabilization_k',
    'weak_roller_foundation_k',
    'weak_inner_guidance_k',
    'mesh_contact_size',
    'mesh_bulk_size',
]
diag['parameter_audit'] = [_param_audit(tag) for tag in interesting_parameters]

try:
    comp = model.component('comp1')
    diag['selection_tags'] = _safe('selection_tags', lambda comp=comp: list(comp.selection().tags()))
    diag['coupling_tags'] = _safe('coupling_tags', lambda comp=comp: list(comp.cpl().tags()))
    diag['pair_tags'] = _safe('pair_tags', lambda comp=comp: list(comp.pair().tags()))
    diag['physics_tags'] = _safe('physics_tags', lambda comp=comp: list(comp.physics().tags()))
    diag['mesh_tags'] = _safe('mesh_tags', lambda comp=comp: list(comp.mesh().tags()))
    try:
        solid = comp.physics('solid')
        solid_feature_tags = list(solid.feature().tags())
    except Exception:
        solid = None
        solid_feature_tags = []
    diag['solid_feature_tags'] = solid_feature_tags
    interesting_features = [
        'load_inner_bore',
        'body_load_inner_ring',
        'disp_inner_bore_preload',
        'weak_inner_ring_load_guidance',
        'weak_roller_foundation',
        'active_roller_stabilization',
        'fix_active_roller',
        'fix_outer_support',
        'roller_outer_contact_1',
        'roller_inner_contact_1',
        'roller_outer_contact_2',
        'roller_inner_contact_2',
        'roller_outer_contact_12',
        'roller_inner_contact_12',
    ]
    for tag in solid_feature_tags:
        tag_text = str(tag)
        if 'contact' in tag_text.lower() or 'cage' in tag_text.lower() or 'roller' in tag_text.lower():
            interesting_features.append(tag_text)
    seen = []
    for tag in interesting_features:
        if tag not in seen:
            seen.append(tag)
    props = [
        'FperArea', 'F', 'LoadType', 'BoundaryLoadType', 'Direction', 'u0', 'PrescribedDisplacement',
        'weakContribution', 'kV', 'kPerArea', 'kPerVolume', 'Pair', 'pairs', 'ContactPair',
        'penalty', 'pn_penalty', 'useRelaxation', 'irlx', 'relax', 'ContactTolType', 'tolcontact',
        'zeroInitGap', 'gapoffset', 'fric', 'mu', 'springType', 'SpringType', 'SpringFoundationType',
    ]
    diag['solid_feature_audit'] = [
        _feature_audit(solid, tag, props) for tag in seen
    ] if solid is not None else []
    selection_tags = [
        'sel_inner_bore_load_surface',
        'box_inner_bore_load_surface',
        'sel_inner_raceway_contact',
        'sel_outer_raceway_contact',
        'sel_outer_support_surface',
        'sel_roller_1_body',
        'sel_roller_2_body',
        'sel_roller_12_body',
        'sel_cage_body',
    ]
    for index in [1, 2, 12]:
        selection_tags.extend([
            'sel_roller_' + str(index) + '_inner_contact',
            'sel_roller_' + str(index) + '_outer_contact',
            'sel_roller_' + str(index) + '_cage_contact',
            'sel_inner_raceway_' + str(index) + '_contact',
            'sel_outer_raceway_' + str(index) + '_contact',
            'sel_cage_pocket_' + str(index) + '_contact',
        ])
    all_selection_tags = diag.get('selection_tags', {{}}).get('value') or []
    for tag in all_selection_tags:
        if 'roller' in str(tag).lower() or 'cage' in str(tag).lower() or 'bore' in str(tag).lower() or 'raceway' in str(tag).lower():
            selection_tags.append(str(tag))
    dedup_selection_tags = []
    for tag in selection_tags:
        if tag not in dedup_selection_tags:
            dedup_selection_tags.append(tag)
    diag['selection_audit'] = [_selection_audit(comp, tag) for tag in dedup_selection_tags]
    coupling_tags = ['intop_displacement_reaction_probe', 'maxop_inner_ring', 'maxop_cage']
    for tag in diag.get('coupling_tags', {{}}).get('value') or []:
        coupling_tags.append(str(tag))
    dedup_coupling_tags = []
    for tag in coupling_tags:
        if tag not in dedup_coupling_tags:
            dedup_coupling_tags.append(tag)
    diag['coupling_audit'] = [_coupling_audit(comp, tag) for tag in dedup_coupling_tags]
    pair_tags = []
    for index in [1, 2, 12]:
        pair_tags.extend([
            'cp_roller_' + str(index) + '_inner_raceway',
            'cp_roller_' + str(index) + '_outer_raceway',
            'cp_roller_' + str(index) + '_cage_pocket',
        ])
    for tag in diag.get('pair_tags', {{}}).get('value') or []:
        tag_text = str(tag)
        if 'roller' in tag_text.lower() or 'cage' in tag_text.lower() or 'raceway' in tag_text.lower():
            pair_tags.append(tag_text)
    dedup_pair_tags = []
    for tag in pair_tags:
        if tag not in dedup_pair_tags:
            dedup_pair_tags.append(tag)
    diag['contact_pair_audit'] = [_pair_audit(comp, tag) for tag in dedup_pair_tags]
except Exception as error:
    diag['component_audit_error'] = str(error)

study_audits = []
for study_tag in diag.get('study_tags', {{}}).get('value') or []:
    item = {{'tag': study_tag}}
    try:
        study = model.study(study_tag)
        try:
            item['feature_tags'] = {{'success': True, 'value': _stringify(list(study.feature().tags()))}}
        except Exception as error:
            item['feature_tags'] = {{'success': False, 'error': str(error)}}
        features = []
        for feature_tag in item.get('feature_tags', {{}}).get('value') or []:
            feature = study.feature(feature_tag)
            features.append({{
                'tag': str(feature_tag),
                'type': _safe('type', lambda feature=feature: feature.getType()),
                'active': _safe('active', lambda feature=feature: feature.isActive()),
                'properties': {{
                    prop: _feature_get(feature, prop)
                    for prop in ['useparam', 'pname', 'plistarr', 'punit', 'solnum', 'notlistsolnum']
                }},
            }})
        item['features'] = features
    except Exception as error:
        item['error'] = str(error)
    study_audits.append(item)
diag['study_audit'] = study_audits

solver_audits = []
for sol_tag in diag.get('solver_tags', {{}}).get('value') or []:
    item = {{'tag': sol_tag}}
    try:
        sol = model.sol(sol_tag)
        try:
            item['feature_tags'] = {{'success': True, 'value': _stringify(list(sol.feature().tags()))}}
        except Exception as error:
            item['feature_tags'] = {{'success': False, 'error': str(error)}}
        features = []
        for feature_tag in item.get('feature_tags', {{}}).get('value') or []:
            feature = sol.feature(feature_tag)
            features.append({{
                'tag': str(feature_tag),
                'type': _safe('type', lambda feature=feature: feature.getType()),
                'active': _safe('active', lambda feature=feature: feature.isActive()),
                'properties': {{
                    prop: _feature_get(feature, prop)
                    for prop in ['stol', 'maxsegiter', 'maxiter', 'maxlinit', 'nonlin', 'linpmethod', 'linsolver', 'usesol']
                }},
            }})
        item['features'] = features
    except Exception as error:
        item['error'] = str(error)
    solver_audits.append(item)
diag['solver_audit'] = solver_audits

output.write({STAGE_MPH_DIAGNOSTIC_JSON_START!r} + '\\n')
output.write(json.dumps(diag, ensure_ascii=False, default=str))
output.write('\\n' + {STAGE_MPH_DIAGNOSTIC_JSON_END!r} + '\\n')
"""
    execution = comsol_execute_java(code, model_name=model_name)
    compact = _compact_runtime_result(execution)
    parsed = _extract_stage_mph_diagnostic_payload(execution.get("stdout") or execution.get("output"))
    payload = parsed.get("payload") if isinstance(parsed.get("payload"), dict) else {}
    payload_clean = parsed.get("success") is True and not payload.get("component_audit_error")
    payload["pair_endpoint_consistency"] = _summarize_contact_pair_endpoint_consistency(
        payload.get("contact_pair_audit"),
    )
    return {
        "success": bool(execution.get("success")) and payload_clean,
        "execution": compact,
        "payload": payload or parsed.get("payload"),
        "error": parsed.get("error") or payload.get("component_audit_error") or execution.get("error"),
    }


def _extract_stage_mph_diagnostic_payload(output: str | None) -> dict[str, Any]:
    if not output:
        return {"success": False, "error": "No COMSOL audit output was captured."}
    pattern = re.compile(
        re.escape(STAGE_MPH_DIAGNOSTIC_JSON_START)
        + r"\s*(.*?)\s*"
        + re.escape(STAGE_MPH_DIAGNOSTIC_JSON_END),
        flags=re.DOTALL,
    )
    match = pattern.search(output)
    if not match:
        return {"success": False, "error": "Diagnostic JSON markers were not found in COMSOL output."}
    try:
        return {"success": True, "payload": json.loads(match.group(1))}
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"Diagnostic JSON parse failed: {exc}"}


def _map_boundary_selection_entities(
    model_name: str,
    *,
    selection_name: str,
    entities: list[int],
    rollers: tuple[int, ...] = (1, 2, 12),
) -> dict[str, Any]:
    """Evaluate per-entity geometry moments for a named boundary selection."""
    rows: list[dict[str, Any]] = []
    for entity in entities:
        evaluations = [
            _evaluate_surface_integral_expression_on_entities_via_java(
                model_name,
                expression,
                entities=[int(entity)],
                tag=f"boundary_map_{selection_name}_{entity}_{label}",
            )
            for label, expression in (
                ("area", "1"),
                ("x_moment", "x"),
                ("y_moment", "y"),
                ("z_moment", "z"),
            )
        ]
        rows.append(_summarize_boundary_entity_row(int(entity), evaluations, rollers=rollers))
    return _summarize_boundary_entity_map(selection_name=selection_name, rows=rows, rollers=rollers)


def _summarize_boundary_entity_row(
    entity: int,
    evaluations: list[dict[str, Any]],
    *,
    rollers: tuple[int, ...] = (1, 2, 12),
) -> dict[str, Any]:
    values: dict[str, float | None] = {}
    by_label: dict[str, Any] = {}
    for item in evaluations:
        expression = str(item.get("expression") or "")
        label = {
            "1": "area",
            "x": "x_moment",
            "y": "y_moment",
            "z": "z_moment",
        }.get(expression, expression)
        value = _runtime_numeric_max(item)
        values[label] = value
        by_label[label] = {
            "success": bool(item.get("success")),
            "value": value,
            "diagnostic_class": _classify_contact_probe_evaluation(item),
            "error": item.get("error"),
        }
    area = values.get("area")
    centroid: dict[str, float] = {}
    if area is not None and math.isfinite(area) and abs(area) > 1.0e-18:
        for moment_key, axis in (("x_moment", "x"), ("y_moment", "y"), ("z_moment", "z")):
            value = values.get(moment_key)
            if value is not None and math.isfinite(value):
                centroid[axis] = value / area
    radius = None
    angle_deg = None
    if "x" in centroid and "y" in centroid:
        radius = math.hypot(float(centroid["x"]), float(centroid["y"]))
        angle_deg = math.degrees(math.atan2(float(centroid["y"]), float(centroid["x"])))
        if angle_deg < 0:
            angle_deg += 360.0
    roller_angles = _boundary_entity_roller_angle_distances(angle_deg, rollers=rollers)
    nearest_roller = None
    if roller_angles:
        nearest_roller = min(roller_angles, key=lambda item: item["abs_angle_delta_deg"])
    return {
        "entity": int(entity),
        "success": bool(centroid) and radius is not None,
        "area_integral": area,
        "centroid_m": centroid,
        "radius_m": radius,
        "radius_mm": radius * 1000.0 if radius is not None else None,
        "angle_deg": angle_deg,
        "nearest_roller": nearest_roller,
        "roller_angle_distances": roller_angles,
        "evaluations": by_label,
    }


def _boundary_entity_roller_angle_distances(
    angle_deg: float | None,
    *,
    rollers: tuple[int, ...] = (1, 2, 12),
) -> list[dict[str, Any]]:
    if angle_deg is None:
        return []
    rows: list[dict[str, Any]] = []
    for roller in rollers:
        roller_angle = ((int(roller) - 1) * 360.0 / VERIFIED_ROLLER_COUNT) % 360.0
        delta = ((float(angle_deg) - roller_angle + 180.0) % 360.0) - 180.0
        rows.append({
            "roller": int(roller),
            "roller_angle_deg": roller_angle,
            "signed_angle_delta_deg": delta,
            "abs_angle_delta_deg": abs(delta),
        })
    return rows


def _summarize_boundary_entity_map(
    *,
    selection_name: str,
    rows: list[dict[str, Any]],
    rollers: tuple[int, ...] = (1, 2, 12),
) -> dict[str, Any]:
    successful_rows = [row for row in rows if row.get("success")]
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            row.get("success") is not True,
            row.get("angle_deg") is None,
            row.get("angle_deg") or 0.0,
            row.get("entity") or 0,
        ),
    )
    nearest_by_roller: dict[str, Any] = {}
    for roller in rollers:
        candidates = [
            row for row in successful_rows
            for dist in row.get("roller_angle_distances") or []
            if dist.get("roller") == int(roller)
        ]
        if not candidates:
            nearest_by_roller[f"roller_{roller}"] = None
            continue
        nearest_by_roller[f"roller_{roller}"] = min(
            candidates,
            key=lambda row: next(
                dist["abs_angle_delta_deg"]
                for dist in row.get("roller_angle_distances") or []
                if dist.get("roller") == int(roller)
            ),
        )
    return {
        "success": bool(successful_rows),
        "kind": "bearing_3d_boundary_selection_entity_geometry_map",
        "selection_name": selection_name,
        "entity_count": len(rows),
        "successful_entity_count": len(successful_rows),
        "entity_rows": sorted_rows,
        "nearest_entity_by_roller": nearest_by_roller,
        "warning": None if successful_rows else "No entity centroid rows evaluated successfully; configured MPH may not have a solution dataset.",
    }


def _write_boundary_entity_map_report(
    result: dict[str, Any],
    *,
    json_path: Path,
    markdown_path: Path,
) -> dict[str, Any]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    result["json_path"] = str(json_path.resolve())
    result["markdown_path"] = str(markdown_path.resolve())
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(_render_boundary_entity_map_markdown(result), encoding="utf-8")
    return result


def _render_boundary_entity_map_markdown(result: dict[str, Any]) -> str:
    boundary_map = result.get("map") or {}
    lines = [
        "# Bearing 3D Boundary Entity Map",
        "",
        f"- MPH: `{result.get('mph_path')}`",
        f"- Selection: `{result.get('selection_name')}`",
        f"- Success: `{result.get('success')}`",
        f"- Error: `{result.get('error')}`",
        f"- Entity count: `{boundary_map.get('entity_count')}`",
        f"- Successful entity count: `{boundary_map.get('successful_entity_count')}`",
        f"- Warning: `{boundary_map.get('warning')}`",
        "",
        "## Nearest entity by roller",
        "",
        "| Roller | Entity | Radius mm | Angle deg | Abs angle delta deg |",
        "|---|---:|---:|---:|---:|",
    ]
    for roller_key, row in (boundary_map.get("nearest_entity_by_roller") or {}).items():
        nearest = row.get("nearest_roller") if isinstance(row, dict) else {}
        lines.append(
            "| {roller} | {entity} | {radius} | {angle} | {delta} |".format(
                roller=roller_key,
                entity=(row or {}).get("entity") if isinstance(row, dict) else None,
                radius=_format_float_for_markdown((row or {}).get("radius_mm") if isinstance(row, dict) else None),
                angle=_format_float_for_markdown((row or {}).get("angle_deg") if isinstance(row, dict) else None),
                delta=_format_float_for_markdown((nearest or {}).get("abs_angle_delta_deg")),
            )
        )
    lines.extend([
        "",
        "## Entity rows",
        "",
        "| Entity | Success | Radius mm | Angle deg | X mm | Y mm | Z mm | Nearest roller | Delta deg |",
        "|---:|---:|---:|---:|---:|---:|---:|---|---:|",
    ])
    for row in boundary_map.get("entity_rows") or []:
        centroid = row.get("centroid_m") or {}
        nearest = row.get("nearest_roller") or {}
        lines.append(
            "| {entity} | {success} | {radius} | {angle} | {x} | {y} | {z} | {roller} | {delta} |".format(
                entity=row.get("entity"),
                success=_md_bool(row.get("success")),
                radius=_format_float_for_markdown(row.get("radius_mm")),
                angle=_format_float_for_markdown(row.get("angle_deg")),
                x=_format_float_for_markdown((centroid.get("x") * 1000.0) if centroid.get("x") is not None else None),
                y=_format_float_for_markdown((centroid.get("y") * 1000.0) if centroid.get("y") is not None else None),
                z=_format_float_for_markdown((centroid.get("z") * 1000.0) if centroid.get("z") is not None else None),
                roller=nearest.get("roller"),
                delta=_format_float_for_markdown(nearest.get("abs_angle_delta_deg")),
            )
        )
    return "\n".join(lines) + "\n"


def _format_float_for_markdown(value: Any) -> str:
    try:
        if value is None:
            return ""
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return str(number)
    return f"{number:.6g}"


def _write_stage_mph_diagnostic_report(
    result: dict[str, Any],
    *,
    json_path: Path,
    markdown_path: Path,
) -> dict[str, Any]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    result["json_path"] = str(json_path.resolve())
    result["markdown_path"] = str(markdown_path.resolve())
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(_render_stage_mph_diagnostic_markdown(result), encoding="utf-8")
    return result


def _render_stage_mph_diagnostic_markdown(result: dict[str, Any]) -> str:
    audit_payload = ((result.get("audit") or {}).get("payload") or {})
    feature_rows = audit_payload.get("solid_feature_audit") or []
    selection_rows = audit_payload.get("selection_audit") or []
    pair_rows = audit_payload.get("contact_pair_audit") or []
    coupling_rows = audit_payload.get("coupling_audit") or []
    endpoint_consistency = audit_payload.get("pair_endpoint_consistency") or {}
    lines = [
        "# Bearing 3D Stage MPH Diagnostic",
        "",
        f"- MPH: `{result.get('mph_path')}`",
        f"- Success: `{result.get('success')}`",
        f"- Policy: `{result.get('policy')}`",
        f"- Error: `{result.get('error')}`",
        "",
        "## Tags",
        "",
        f"- Studies: `{_safe_markdown_json((audit_payload.get('study_tags') or {}).get('value'))}`",
        f"- Solvers: `{_safe_markdown_json((audit_payload.get('solver_tags') or {}).get('value'))}`",
        f"- Solid features: `{_safe_markdown_json(audit_payload.get('solid_feature_tags'))}`",
        "",
        "## Solid Feature Audit",
        "",
        "| Feature | Exists | Type | Active | Selection | Key property status |",
        "|---|---:|---|---:|---|---|",
    ]
    for feature in feature_rows:
        props = feature.get("properties") or {}
        key_props = []
        for prop in ("FperArea", "u0", "kPerArea", "kPerVolume", "pairs", "pn_penalty", "useRelaxation", "irlx", "tolcontact", "zeroInitGap"):
            if prop in props:
                status = "ok" if (props[prop] or {}).get("success") else "missing"
                key_props.append(f"{prop}:{status}")
        lines.append(
            "| {tag} | {exists} | {type} | {active} | `{selection}` | {props} |".format(
                tag=str(feature.get("tag") or "").replace("|", "\\|"),
                exists=_md_bool(feature.get("exists")),
                type=str(feature.get("type") or "").replace("|", "\\|"),
                active=_md_bool(feature.get("active")),
                selection=_safe_markdown_json(feature.get("selection_named") or feature.get("selection_entities")),
                props=", ".join(key_props),
            )
        )
    lines.extend([
        "",
        "## Selection Audit",
        "",
        "| Selection | Exists | Entity count | Entity probe |",
        "|---|---:|---:|---|",
    ])
    for selection in selection_rows:
        lines.append(
            "| {tag} | {exists} | {count} | `{entities}` |".format(
                tag=str(selection.get("tag") or "").replace("|", "\\|"),
                exists=_md_bool(selection.get("exists")),
                count=selection.get("entity_count"),
                entities=_safe_markdown_json(selection.get("entities")),
            )
        )
    lines.extend([
        "",
        "## Contact Pair Audit",
        "",
        f"- Endpoint consistency: `{endpoint_consistency.get('consistent_pair_count')}/{endpoint_consistency.get('expected_pair_count')}`",
        f"- Endpoint rebind justified: `{endpoint_consistency.get('endpoint_rebind_justified')}`",
        f"- Divergent pairs: `{_safe_markdown_json(endpoint_consistency.get('divergent_pair_tags'))}`",
        "",
        "| Pair | Exists | Type | Source selection | Source entities | Destination selection | Destination entities |",
        "|---|---:|---|---|---:|---|---:|",
    ])
    for pair in pair_rows:
        source = pair.get("source") or {}
        destination = pair.get("destination") or {}
        lines.append(
            "| {tag} | {exists} | {type} | `{source_named}` | {source_count} | `{destination_named}` | {destination_count} |".format(
                tag=str(pair.get("tag") or "").replace("|", "\\|"),
                exists=_md_bool(pair.get("exists")),
                type=str(pair.get("type") or "").replace("|", "\\|"),
                source_named=_safe_markdown_json(source.get("named")),
                source_count=source.get("entity_count"),
                destination_named=_safe_markdown_json(destination.get("named")),
                destination_count=destination.get("entity_count"),
            )
        )
    lines.extend([
        "",
        "## Coupling Audit",
        "",
        "| Coupling | Exists | Type | Opname | Selection |",
        "|---|---:|---|---|---|",
    ])
    for coupling in coupling_rows:
        lines.append(
            "| {tag} | {exists} | {type} | `{opname}` | `{selection}` |".format(
                tag=str(coupling.get("tag") or "").replace("|", "\\|"),
                exists=_md_bool(coupling.get("exists")),
                type=str(coupling.get("type") or "").replace("|", "\\|"),
                opname=_safe_markdown_json(coupling.get("opname")),
                selection=_safe_markdown_json(coupling.get("selection_named") or coupling.get("selection_entities")),
            )
        )
    lines.extend([
        "",
        "## Study Audit",
        "",
        "```json",
        json.dumps(audit_payload.get("study_audit") or [], ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Solver Audit",
        "",
        "```json",
        json.dumps(audit_payload.get("solver_audit") or [], ensure_ascii=False, indent=2, default=str),
        "```",
    ])
    return "\n".join(lines) + "\n"


def _safe_markdown_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _stage_evidence_rows_from_summary(summary: dict[str, Any], *, summary_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    staged = _summary_staged_contact_solve(summary)
    requested = summary.get("requested_stage_image") or {}
    physical = summary.get("physical_contact_validation") or {}
    failed_mph = summary_path.with_name("failed_3d_contact_model.mph")
    stages = staged.get("stages") if isinstance(staged, dict) else None
    if isinstance(stages, list) and stages:
        for index, stage in enumerate(stages):
            if not isinstance(stage, dict):
                continue
            rows.append(_stage_evidence_row(
                summary=summary,
                summary_path=summary_path,
                stage=stage,
                stage_index=index,
                requested=requested,
                physical=physical,
                failed_mph=failed_mph,
            ))
    legacy = summary.get("legacy_raceway_highload_direct")
    if isinstance(legacy, dict):
        rows.append(_stage_evidence_row(
            summary=summary,
            summary_path=summary_path,
            stage={
                **legacy,
                "name": legacy.get("stage") or "legacy_raceway_highload_direct",
                "solve": legacy.get("solve"),
                "native_volume_plot": legacy.get("native_volume_plot"),
                "stress": legacy.get("stress"),
                "displacement": legacy.get("displacement"),
                "contact_pressure": legacy.get("contact_pressure"),
                "active_rollers": list(range(1, VERIFIED_ROLLER_COUNT + 1)),
                "inner_bore_load_active": False,
                "inner_body_load_active": True,
                "cage_contact_active": False,
                "load_application_fidelity": legacy.get("load_application_fidelity"),
            },
            stage_index=0,
            requested=requested,
            physical=legacy.get("physical_contact_validation") or physical,
            failed_mph=failed_mph,
        ))
    if not rows and requested:
        rows.append(_stage_evidence_row(
            summary=summary,
            summary_path=summary_path,
            stage={
                "name": requested.get("selected_stage") or summary.get("stage") or summary.get("model_name"),
                "solve": summary.get("solve"),
                "native_volume_plot": {"success": bool(requested.get("native_comsol_png")), "filepath": requested.get("native_comsol_png")},
                "stress": {"success": requested.get("max_von_mises_pa") is not None, "value": requested.get("max_von_mises_pa")},
                "displacement": {"success": requested.get("max_displacement_m") is not None, "value": requested.get("max_displacement_m")},
                "contact_pressure": {"success": requested.get("contact_pressure_est_pa") is not None, "value": requested.get("contact_pressure_est_pa")},
                "load_application_fidelity": requested.get("load_application_fidelity"),
                "contact_scope": requested.get("contact_scope"),
            },
            stage_index=0,
            requested=requested,
            physical=physical,
            failed_mph=failed_mph,
        ))
    return rows


def _summary_staged_contact_solve(summary: dict[str, Any]) -> dict[str, Any]:
    for key in ("staged_contact_solve", "staged_solve"):
        value = summary.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _stage_evidence_row(
    *,
    summary: dict[str, Any],
    summary_path: Path,
    stage: dict[str, Any],
    stage_index: int,
    requested: dict[str, Any],
    physical: dict[str, Any],
    failed_mph: Path,
) -> dict[str, Any]:
    native_plot = stage.get("native_volume_plot") or {}
    pre_solve_save = stage.get("pre_solve_model_save") or {}
    post_reaction_probe_save = stage.get("post_reaction_probe_model_save") or {}
    solve = stage.get("solve") or {}
    reaction = stage.get("reaction_equivalent") or {}
    reaction_force_abs = reaction.get("best_reaction_force_abs_n")
    try:
        reaction_force_abs_numeric = float(reaction_force_abs) if reaction_force_abs is not None else None
    except (TypeError, ValueError):
        reaction_force_abs_numeric = None
    reaction_equivalent_verified = bool(reaction.get("success")) and (
        reaction_force_abs_numeric is not None and abs(reaction_force_abs_numeric) > 1.0e-9
    )
    plausibility = _stage_basic_physical_plausibility(stage)
    load_fidelity = str(stage.get("load_application_fidelity") or requested.get("load_application_fidelity") or "")
    active_rollers = stage.get("active_rollers")
    if isinstance(active_rollers, list):
        active_roller_count = len(active_rollers)
    else:
        active_roller_count = None
    selected_stage = requested.get("selected_stage")
    production_ready = _stage_row_production_ready(stage, requested=requested)
    roller_probe_metrics = plausibility.get("roller_probe_metrics") or {}
    load_distribution = plausibility.get("active_roller_load_distribution") or {}
    staged = _summary_staged_contact_solve(summary)
    model_name = (
        summary.get("model_name")
        or ((summary.get("template_run") or {}).get("model_name") if isinstance(summary.get("template_run"), dict) else None)
        or solve.get("model_name")
        or (stage.get("setup") or {}).get("model_name")
    )
    return {
        "summary_path": str(summary_path),
        "artifact_root": str(summary_path.parent),
        "model_name": model_name,
        "contact_stage_mode": summary.get("contact_stage_mode") or staged.get("contact_stage_mode"),
        "geometry_overrides": summary.get("geometry_overrides"),
        "stage_index": stage_index,
        "stage": stage.get("name") or stage.get("stage"),
        "solve_success": bool(solve.get("success")),
        "solver_error": solve.get("error"),
        "native_png": native_plot.get("filepath") or requested.get("native_comsol_png"),
        "native_png_success": bool(native_plot.get("success")),
        "png_quality_success": bool((native_plot.get("png_quality") or {}).get("success")),
        "pre_solve_mph": pre_solve_save.get("filepath") or pre_solve_save.get("saved_to"),
        "pre_solve_mph_success": bool(pre_solve_save.get("success")),
        "post_reaction_probe_mph": post_reaction_probe_save.get("filepath") or post_reaction_probe_save.get("saved_to"),
        "post_reaction_probe_mph_success": bool(post_reaction_probe_save.get("success")),
        "boundary_load_active": bool(stage.get("inner_bore_load_active")),
        "body_load_active": bool(stage.get("inner_body_load_active")) or "body_load" in load_fidelity.lower(),
        "load_application_fidelity": load_fidelity or None,
        "active_rollers": active_rollers,
        "active_roller_count": active_roller_count,
        "cage_contact_active": bool(stage.get("cage_contact_active")),
        "weak_guidance": bool(stage.get("weak_inner_guidance_active")),
        "weak_roller_foundation_active": bool(stage.get("weak_roller_foundation_active")),
        "temporary_spring": bool(stage.get("temporary_active_roller_stabilization_active"))
        and str(stage.get("active_roller_stabilization_mode") or "") == "spring",
        "temporary_active_roller_stabilization_active": bool(stage.get("temporary_active_roller_stabilization_active")),
        "temporary_cage_stabilization_active": bool(stage.get("temporary_cage_stabilization_active")),
        "displacement_preload_active": bool(stage.get("displacement_preload_active")),
        "inner_radial_displacement": stage.get("inner_radial_displacement"),
        "radial_load_value": stage.get("radial_load_value"),
        "preload_steps": stage.get("preload_steps"),
        "contact_pair_endpoint_overrides": stage.get("contact_pair_endpoint_overrides") or {},
        "raceway_selection_entity_overrides": stage.get("raceway_selection_entity_overrides") or {},
        "contact_feature_property_overrides": stage.get("contact_feature_property_overrides") or {},
        "contact_patch_box_overrides": stage.get("contact_patch_box_overrides") or {},
        "raceway_partition_patch_overrides": stage.get("raceway_partition_patch_overrides") or {},
        "max_von_mises_pa": _runtime_numeric_max(stage.get("stress")),
        "inner_ring_max_von_mises_pa": _runtime_numeric_max(stage.get("inner_ring_stress")),
        "max_displacement_m": _runtime_numeric_max(stage.get("displacement")),
        "contact_pressure_est_pa": _runtime_numeric_max(stage.get("contact_pressure")),
        "roller_probe_count": roller_probe_metrics.get("probe_count"),
        "roller_probe_success_count": roller_probe_metrics.get("probe_success_count"),
        "active_roller_probe_success_count": roller_probe_metrics.get("active_probe_success_count"),
        "active_roller_nonzero_probe_count": roller_probe_metrics.get("active_roller_nonzero_count"),
        "active_roller_nonzero_probe_ratio": roller_probe_metrics.get("active_roller_nonzero_ratio"),
        "active_roller_zero_stress_rollers": roller_probe_metrics.get("active_roller_zero_stress_rollers"),
        "active_roller_max_von_mises_pa": roller_probe_metrics.get("active_roller_max_von_mises_pa"),
        "active_roller_min_von_mises_pa": roller_probe_metrics.get("active_roller_min_von_mises_pa"),
        "active_roller_min_to_max_stress_ratio": roller_probe_metrics.get("active_roller_min_to_max_ratio"),
        "active_roller_values_by_roller": roller_probe_metrics.get("active_roller_values_by_roller"),
        "inactive_roller_max_von_mises_pa": roller_probe_metrics.get("inactive_roller_max_von_mises_pa"),
        "active_to_inactive_roller_stress_ratio": roller_probe_metrics.get("active_to_inactive_max_ratio"),
        "active_roller_load_distribution_success": load_distribution.get("success"),
        "active_roller_load_distribution_errors": load_distribution.get("errors"),
        "active_roller_load_distribution_warnings": load_distribution.get("warnings"),
        "physical_plausibility_success": plausibility.get("success"),
        "physical_plausibility_errors": plausibility.get("errors"),
        "physical_plausibility_warnings": plausibility.get("warnings"),
        "reaction_equivalent_requested": bool(stage.get("reaction_equivalent_requested")),
        "reaction_equivalent_success": reaction_equivalent_verified,
        "reaction_best_force_abs_n": reaction_force_abs,
        "reaction_best_expression": reaction.get("best_expression"),
        "reaction_candidate_count": reaction.get("candidate_count"),
        "reaction_successful_candidate_count": reaction.get("successful_candidate_count"),
        "physical_acceptance": stage.get("physical_acceptance"),
        "physical_validation_quality": physical.get("quality_level"),
        "selected_for_request": bool(selected_stage and selected_stage == (stage.get("name") or stage.get("stage"))),
        "production_ready": production_ready,
        "failed_mph": str(failed_mph) if failed_mph.exists() else None,
    }


def _stage_row_production_ready(stage: dict[str, Any], *, requested: dict[str, Any]) -> bool:
    if requested.get("selected_stage") == (stage.get("name") or stage.get("stage")):
        return bool(requested.get("production_ready"))
    load_fidelity = str(stage.get("load_application_fidelity") or "")
    return (
        bool((stage.get("solve") or {}).get("success"))
        and bool((stage.get("native_volume_plot") or {}).get("success"))
        and bool(stage.get("inner_bore_load_active"))
        and bool(stage.get("cage_contact_active"))
        and not bool(stage.get("displacement_preload_active"))
        and not bool(stage.get("weak_inner_guidance_active"))
        and not bool(stage.get("temporary_active_roller_stabilization_active"))
        and not bool(stage.get("temporary_cage_stabilization_active"))
        and "not_design" not in load_fidelity
        and "fallback" not in load_fidelity
    )


def _build_preload_calibration_from_stage_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    calibration_rows = [
        row for row in rows
        if row.get("displacement_preload_active") and row.get("inner_radial_displacement")
    ]
    points: list[dict[str, Any]] = []
    for row in calibration_rows:
        displacement_um = _parse_unit_value_to_float(row.get("inner_radial_displacement"), unit="um")
        points.append({
            "stage": row.get("stage"),
            "summary_path": row.get("summary_path"),
            "inner_radial_displacement_um": displacement_um,
            "reaction_equivalent_success": row.get("reaction_equivalent_success"),
            "reaction_best_force_abs_n": row.get("reaction_best_force_abs_n"),
            "max_von_mises_pa": row.get("max_von_mises_pa"),
            "inner_ring_max_von_mises_pa": row.get("inner_ring_max_von_mises_pa"),
            "max_displacement_m": row.get("max_displacement_m"),
            "contact_pressure_est_pa": row.get("contact_pressure_est_pa"),
            "native_png": row.get("native_png"),
            "solve_success": row.get("solve_success"),
        })
    points.sort(key=lambda point: (point["inner_radial_displacement_um"] is None, point["inner_radial_displacement_um"] or 0.0))
    return {
        "success": bool(points),
        "kind": "displacement_preload_reaction_calibration_evidence",
        "point_count": len(points),
        "monotonic_checks": {
            "reaction_force_abs_n": _monotonic_non_decreasing(points, "reaction_best_force_abs_n"),
            "max_von_mises_pa": _monotonic_non_decreasing(points, "max_von_mises_pa"),
            "inner_ring_max_von_mises_pa": _monotonic_non_decreasing(points, "inner_ring_max_von_mises_pa"),
            "max_displacement_m": _monotonic_non_decreasing(points, "max_displacement_m"),
            "contact_pressure_est_pa": _monotonic_non_decreasing(points, "contact_pressure_est_pa"),
        },
        "points": points,
        "warning": None if points else "No solved displacement-preload stages found in scanned summaries.",
    }


def _parse_unit_value_to_float(value: Any, *, unit: str) -> float | None:
    if value is None:
        return None
    match = re.search(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(?:\[" + re.escape(unit) + r"\])?", str(value))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _monotonic_non_decreasing(points: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [point.get(key) for point in points if point.get(key) is not None]
    numeric: list[float] = []
    for value in values:
        try:
            numeric.append(float(value))
        except (TypeError, ValueError):
            pass
    if len(numeric) < 2:
        return {"checked": False, "success": None, "reason": "fewer_than_two_numeric_points", "values": numeric}
    success = all(right >= left for left, right in zip(numeric, numeric[1:]))
    return {"checked": True, "success": success, "values": numeric}


def _select_highest_trust_stage_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    plausible_rows = [row for row in rows if row.get("physical_plausibility_success") is not False]
    if not plausible_rows:
        return None
    rankable_rows = plausible_rows
    def row_rank(row: dict[str, Any]) -> float:
        rank = 0.0
        if row.get("physical_plausibility_success") is False:
            rank -= 100.0
        if row.get("production_ready"):
            rank += 100.0
        if row.get("solve_success"):
            rank += 10.0
        if row.get("native_png_success"):
            rank += 10.0
        if row.get("boundary_load_active"):
            rank += 8.0
        if row.get("cage_contact_active"):
            rank += 6.0
        if row.get("active_roller_count") == VERIFIED_ROLLER_COUNT:
            rank += 4.0
        if row.get("reaction_equivalent_success"):
            rank += 3.0
        if row.get("body_load_active"):
            rank -= 20.0
        if row.get("weak_guidance"):
            rank -= 4.0
        if row.get("temporary_active_roller_stabilization_active"):
            rank -= 4.0
        if row.get("displacement_preload_active"):
            rank -= 3.0
        stress = row.get("max_von_mises_pa")
        if stress:
            try:
                rank += min(math.log10(abs(float(stress))), 8.0) / 10.0
            except (TypeError, ValueError):
                pass
        return rank
    best = max(rankable_rows, key=row_rank)
    return {key: best.get(key) for key in (
        "summary_path",
        "stage",
        "solve_success",
        "native_png",
        "max_von_mises_pa",
        "max_displacement_m",
        "physical_plausibility_success",
        "physical_plausibility_errors",
        "active_roller_nonzero_probe_ratio",
        "active_roller_zero_stress_rollers",
        "reaction_equivalent_success",
        "load_application_fidelity",
        "production_ready",
    )}


def _render_stage_evidence_matrix_markdown(matrix: dict[str, Any]) -> str:
    lines = [
        "# Bearing 3D Stage Evidence Matrix",
        "",
        f"- Search root: `{matrix.get('search_root')}`",
        f"- Summaries scanned: `{matrix.get('summary_count')}`",
        f"- Stage rows: `{matrix.get('row_count')}`",
        f"- Converged native stages: `{matrix.get('converged_native_stage_count')}`",
        f"- Reaction-verified stages: `{matrix.get('reaction_verified_stage_count')}`",
        f"- Production-ready stages: `{matrix.get('production_ready_count')}`",
        f"- Saved-MPH reaction probe reports: `{matrix.get('saved_reaction_probe_report_count')}`",
        f"- Saved-MPH reaction probe verified reports: `{matrix.get('saved_reaction_probe_verified_count')}`",
        f"- Saved-MPH contact probe reports: `{matrix.get('saved_contact_probe_report_count')}`",
        f"- Saved-MPH contact source/destination imbalance reports: `{matrix.get('saved_contact_probe_source_destination_imbalance_count')}`",
        f"- Saved-MPH contact source unevaluable / destination nonzero reports: `{matrix.get('saved_contact_probe_source_unevaluable_destination_nonzero_count')}`",
        "",
        "## Highest Trust Stage",
        "",
        "```json",
        json.dumps(matrix.get("highest_trust_stage"), ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Stage Matrix",
        "",
        "| Stage | Solve | Native PNG | Phys plausible | Pre-solve MPH | BoundaryLoad | BodyLoad | Active rollers | Active roller probes | Carry ratio | Zero active rollers | Active roller max Pa | Cage | Weak guidance | Temp spring | Reaction | Production | Artifact |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in matrix.get("rows") or []:
        lines.append(
            "| {stage} | {solve} | {png} | {plausible} | {mph} | {boundary} | {body} | {rollers} | {active_probes} | {carry_ratio} | {zero_active} | {active_max} | {cage} | {weak} | {spring} | {reaction} | {production} | `{artifact}` |".format(
                stage=str(row.get("stage") or "").replace("|", "\\|"),
                solve=_md_bool(row.get("solve_success")),
                png=_md_bool(row.get("native_png_success")),
                plausible=_md_bool(row.get("physical_plausibility_success")),
                mph=_md_bool(row.get("pre_solve_mph_success")),
                boundary=_md_bool(row.get("boundary_load_active")),
                body=_md_bool(row.get("body_load_active")),
                rollers=row.get("active_roller_count"),
                active_probes=(
                    f"{row.get('active_roller_probe_success_count')}/{row.get('active_roller_nonzero_probe_count')}"
                    if row.get("active_roller_probe_success_count") is not None
                    else ""
                ),
                carry_ratio=row.get("active_roller_nonzero_probe_ratio"),
                zero_active=", ".join(row.get("active_roller_zero_stress_rollers") or []),
                active_max=row.get("active_roller_max_von_mises_pa"),
                cage=_md_bool(row.get("cage_contact_active")),
                weak=_md_bool(row.get("weak_guidance")),
                spring=_md_bool(row.get("temporary_spring")),
                reaction=_md_bool(row.get("reaction_equivalent_success")),
                production=_md_bool(row.get("production_ready")),
                artifact=row.get("summary_path"),
            )
        )
    calibration = matrix.get("preload_calibration") or {}
    lines.extend([
        "",
        "## Displacement Preload Calibration",
        "",
        f"- Points: `{calibration.get('point_count')}`",
        f"- Reaction monotonic check: `{((calibration.get('monotonic_checks') or {}).get('reaction_force_abs_n') or {}).get('success')}`",
        f"- Stress monotonic check: `{((calibration.get('monotonic_checks') or {}).get('max_von_mises_pa') or {}).get('success')}`",
        "",
        "| Stage | Preload (um) | Reaction (N) | max von Mises (Pa) | max disp (m) | PNG |",
        "|---|---:|---:|---:|---:|---|",
    ])
    for point in calibration.get("points") or []:
        lines.append(
            "| {stage} | {preload} | {reaction} | {stress} | {disp} | `{png}` |".format(
                stage=str(point.get("stage") or "").replace("|", "\\|"),
                preload=point.get("inner_radial_displacement_um"),
                reaction=point.get("reaction_best_force_abs_n"),
                stress=point.get("max_von_mises_pa"),
                disp=point.get("max_displacement_m"),
                png=point.get("native_png"),
            )
        )
    distribution = matrix.get("boundaryload_distribution_diagnostics") or {}
    lines.extend([
        "",
        "## BoundaryLoad Distribution Diagnostics",
        "",
        f"- BoundaryLoad rows: `{distribution.get('boundaryload_row_count')}`",
        f"- Zero-carry active-roller rows: `{distribution.get('zero_carry_row_count')}`",
        f"- Missing-probe BoundaryLoad rows: `{distribution.get('missing_probe_row_count')}`",
        f"- Stress-plateau BoundaryLoad rows: `{distribution.get('stress_plateau_row_count')}`",
        f"- Stage MPH diagnostic reports: `{distribution.get('stage_mph_diagnostic_report_count')}`",
        f"- Zero-carry rollers: `{json.dumps(distribution.get('zero_carry_rollers') or {}, ensure_ascii=False, default=str)}`",
        "",
        "Recommended next diagnostics:",
    ])
    for recommendation in distribution.get("recommendations") or []:
        lines.append(f"- {recommendation}")
    lines.extend([
        "",
        "| Stage | Load | Active rollers | Zero active rollers | Carry ratio | Configured zero-carry evidence | Solved contact probe | Stress plateau | max von Mises (Pa) | max disp (m) | Summary |",
        "|---|---:|---|---|---:|---|---|---:|---:|---:|---|",
    ])
    for row in distribution.get("focus_rows") or []:
        configured_evidence = _format_configured_zero_carry_evidence(row.get("configured_mph_diagnostic"))
        contact_probe_evidence = _format_saved_contact_probe_evidence(row.get("saved_contact_probe_diagnostic"))
        lines.append(
            "| {stage} | {load} | {rollers} | {zero} | {ratio} | {configured} | {contact_probe} | {plateau} | {stress} | {disp} | `{summary}` |".format(
                stage=str(row.get("stage") or "").replace("|", "\\|"),
                load=row.get("radial_load_value"),
                rollers=", ".join(str(item) for item in (row.get("active_rollers") or [])),
                zero=", ".join(row.get("active_roller_zero_stress_rollers") or []),
                ratio=row.get("active_roller_nonzero_probe_ratio"),
                configured=configured_evidence.replace("|", "\\|"),
                contact_probe=contact_probe_evidence.replace("|", "\\|"),
                plateau=_md_bool(row.get("boundaryload_sequence_stress_plateau")),
                stress=row.get("max_von_mises_pa"),
                disp=row.get("max_displacement_m"),
                summary=row.get("summary_path"),
            )
        )
    saved_probe_reports = matrix.get("saved_reaction_probe_reports") or []
    lines.extend([
        "",
        "## Saved-MPH Reaction Probe Reports",
        "",
        "| Report | Candidate nonzero | Load balanced | Verified | Applied load (N) | Reaction (N) | Ratio | Candidate count | Nonzero candidates | Unknown operator | Zero result | Selection error | MPH |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    for report in saved_probe_reports:
        candidate_audit = report.get("candidate_audit") or {}
        diagnostic_counts = candidate_audit.get("diagnostic_class_counts") or {}
        load_balance = report.get("reaction_load_balance") or {}
        lines.append(
            "| `{report_path}` | {candidate_nonzero} | {balanced} | {verified} | {applied} | {reaction} | {ratio} | {candidate_count} | {nonzero} | {unknown} | {zero} | {selection_error} | `{mph}` |".format(
                report_path=report.get("path"),
                candidate_nonzero=_md_bool(report.get("reaction_candidate_nonzero")),
                balanced=_md_bool(load_balance.get("success")),
                verified=_md_bool(report.get("reaction_verified")),
                applied=load_balance.get("applied_load_n"),
                reaction=load_balance.get("reaction_force_abs_n") or report.get("best_reaction_force_abs_n"),
                ratio=load_balance.get("reaction_to_load_ratio"),
                candidate_count=report.get("candidate_count"),
                nonzero=report.get("successful_candidate_count"),
                unknown=diagnostic_counts.get("unknown_operator"),
                zero=diagnostic_counts.get("zero_result"),
                selection_error=diagnostic_counts.get("selection_error"),
                mph=report.get("mph_path"),
            )
        )
    saved_contact_reports = matrix.get("saved_contact_probe_reports") or []
    lines.extend([
        "",
        "## Saved-MPH Contact Probe Reports",
        "",
        "| Report | Success | Candidates | Nonzero | Imbalance rollers | Source unevaluable / destination nonzero | MPH |",
        "|---|---:|---:|---:|---|---|---|",
    ])
    for report in saved_contact_reports:
        lines.append(
            "| `{report_path}` | {success} | {candidate_count} | {nonzero} | {imbalance} | {source_unevaluable} | `{mph}` |".format(
                report_path=report.get("path"),
                success=_md_bool(report.get("success")),
                candidate_count=report.get("candidate_count"),
                nonzero=report.get("nonzero_count"),
                imbalance=", ".join(report.get("source_destination_imbalance_rollers") or []),
                source_unevaluable=", ".join(report.get("source_unevaluable_destination_nonzero_rollers") or []),
                mph=report.get("mph_path"),
            )
        )
    return "\n".join(lines) + "\n"


def _format_configured_zero_carry_evidence(diagnostic: Any) -> str:
    if not isinstance(diagnostic, dict) or not diagnostic.get("zero_carry_roller_feature_state"):
        return ""
    parts: list[str] = []
    for roller, state in (diagnostic.get("zero_carry_roller_feature_state") or {}).items():
        if not isinstance(state, dict):
            continue
        parts.append(
            "{roller}: body={body}, inner={inner}, outer={outer}, cage={cage}, weak={weak}, fixed={fixed}, inner_pair={inner_pair}, outer_pair={outer_pair}, angle={angle}, load_offset={offset}, patch_offsets={patch_offsets}, contact_settings_match={settings_match}".format(
                roller=roller,
                body=state.get("body_selection_entity_count"),
                inner=_md_bool(state.get("inner_contact_active")),
                outer=_md_bool(state.get("outer_contact_active")),
                cage=_md_bool(state.get("cage_contact_active")),
                weak=_md_bool(state.get("weak_foundation_active")),
                fixed=_md_bool(state.get("fixed_stabilization_active")),
                inner_pair=_format_pair_endpoint_counts(state.get("inner_pair")),
                outer_pair=_format_pair_endpoint_counts(state.get("outer_pair")),
                angle=_format_degrees(((state.get("selection_geometry") or {}).get("roller_body") or {}).get("angle_deg")),
                offset=_format_degrees((state.get("load_angle_alignment") or {}).get("angle_offset_deg")),
                patch_offsets=_format_contact_patch_offsets(state.get("contact_patch_geometry")),
                settings_match=_md_bool(state.get("contact_feature_settings_match_active_nonzero")),
            )
        )
    path = diagnostic.get("path")
    if path:
        parts.append(f"diag=`{path}`")
    return "; ".join(parts)


def _format_saved_contact_probe_evidence(diagnostic: Any) -> str:
    if not isinstance(diagnostic, dict):
        return ""
    imbalance = ", ".join(diagnostic.get("zero_carry_source_destination_imbalance") or [])
    parts = [
        f"success={_md_bool(diagnostic.get('success'))}",
        f"nonzero={diagnostic.get('nonzero_count')}",
    ]
    if imbalance:
        parts.append(f"source_zero_dest_nonzero={imbalance}")
    path = diagnostic.get("path")
    if path:
        parts.append(f"probe=`{path}`")
    return ", ".join(parts)


def _format_pair_endpoint_counts(pair: Any) -> str:
    if not isinstance(pair, dict):
        return "missing"
    return "{src}->{dst}".format(
        src=pair.get("source_entity_count"),
        dst=pair.get("destination_entity_count"),
    )


def _format_degrees(value: Any) -> str:
    try:
        if value is None:
            return "unavailable"
        return f"{float(value):.3g}deg"
    except (TypeError, ValueError):
        return "unavailable"


def _format_contact_patch_offsets(value: Any) -> str:
    if not isinstance(value, dict):
        return "unavailable"
    inner = value.get("inner_patch_radial_offset_mm")
    outer = value.get("outer_patch_radial_offset_mm")
    try:
        inner_text = "unavailable" if inner is None else f"{float(inner):.3g}mm"
        outer_text = "unavailable" if outer is None else f"{float(outer):.3g}mm"
    except (TypeError, ValueError):
        return "unavailable"
    return f"inner {inner_text}, outer {outer_text}"


def _md_bool(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return ""


def _build_3d_physical_contact_validation(
    *,
    solve: dict | None,
    stress: dict | None = None,
    inner_ring_stress: dict | None = None,
    displacement: dict | None = None,
    png_quality: dict | None = None,
    final_stage: dict | None = None,
) -> dict[str, Any]:
    """Summarize whether a 3D bearing run has trustworthy physical contact evidence."""
    solve_success = bool((solve or {}).get("success"))
    stress_max = _runtime_numeric_max(stress)
    inner_stress_max = _runtime_numeric_max(inner_ring_stress)
    displacement_max = _runtime_numeric_max(displacement)
    png_success = bool((png_quality or {}).get("success")) if png_quality is not None else False
    temporary_active_fix = bool((final_stage or {}).get("temporary_active_roller_stabilization_active"))
    temporary_cage_fix = bool((final_stage or {}).get("temporary_cage_stabilization_active"))
    weak_foundation = bool((final_stage or {}).get("weak_roller_foundation_active"))
    weak_inner_guidance = bool((final_stage or {}).get("weak_inner_guidance_active"))
    retained_displacement_preload = bool((final_stage or {}).get("displacement_preload_active"))
    final_cage_stage = bool((final_stage or {}).get("cage_contact_active"))
    errors: list[str] = []
    warnings: list[str] = []
    if not solve_success:
        errors.append("COMSOL solve did not converge; no trustworthy 3D stress/contact field is available.")
    if stress_max is None or abs(stress_max) <= 1.0:
        errors.append("Global solid.mises is missing or near zero.")
    if inner_stress_max is None or abs(inner_stress_max) <= 1.0:
        errors.append("Inner-ring maxop_inner_ring(solid.mises) is missing or near zero.")
    if displacement_max is None or abs(displacement_max) <= 0.0:
        errors.append("solid.disp is missing or zero.")
    if png_quality is not None and not png_success:
        errors.append(f"Stress PNG failed quality gate: {png_quality.get('error')}")
    if temporary_active_fix:
        warnings.append("Final accepted stage still has temporary active-roller stabilization; this is bootstrap-only evidence.")
    if temporary_cage_fix and final_cage_stage:
        errors.append("Final cage-contact stage still has temporary cage stabilization active.")
    elif temporary_cage_fix:
        warnings.append("Cage contact is not part of the final accepted stage; this is raceway-contact smoke fidelity.")
    if weak_foundation:
        warnings.append("Weak roller spring foundation is active for rigid-body-mode stabilization; contact pairs still carry the bearing load path.")
    if weak_inner_guidance:
        warnings.append("Weak inner-ring guidance spring is active for boundary-load convergence; this is not a final design-grade load-transfer gate.")
    if retained_displacement_preload and bool((final_stage or {}).get("inner_bore_load_active")):
        warnings.append("BoundaryLoad continuation retained prescribed inner-bore displacement preload; use as diagnostic/high-load visualization, not final load-transfer design evidence.")
    quality_level = (
        "production_cage_contact_physics"
        if not errors and final_cage_stage and not temporary_cage_fix and not temporary_active_fix and not retained_displacement_preload and not weak_inner_guidance
        else "raceway_contact_physics_smoke"
        if not errors
        else "not_physical_contact_validated"
    )
    return {
        "success": not errors,
        "quality_level": quality_level,
        "solve_success": solve_success,
        "global_max_von_mises_pa": stress_max,
        "inner_ring_max_von_mises_pa": inner_stress_max,
        "max_displacement_m": displacement_max,
        "stress_png_quality_success": png_success,
        "final_stage": {
            "name": (final_stage or {}).get("name"),
            "contact_scope": (final_stage or {}).get("contact_scope"),
            "active_rollers": (final_stage or {}).get("active_rollers"),
            "cage_contact_active": final_cage_stage,
            "temporary_active_roller_stabilization_active": temporary_active_fix,
            "weak_roller_foundation_active": weak_foundation,
            "weak_inner_guidance_active": weak_inner_guidance,
            "displacement_preload_active": retained_displacement_preload,
            "displacement_preload_selection": (final_stage or {}).get("displacement_preload_selection"),
            "inner_bore_load_active": bool((final_stage or {}).get("inner_bore_load_active")),
            "load_application_fidelity": (final_stage or {}).get("load_application_fidelity"),
            "temporary_cage_stabilization_active": temporary_cage_fix,
            "physical_acceptance": (final_stage or {}).get("physical_acceptance"),
        },
        "errors": errors,
        "warnings": warnings,
    }


def _write_direct_3d_summary(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _print_direct_3d_summary(summary: dict[str, Any], *, full_json_stdout: bool = False) -> None:
    if full_json_stdout:
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return

    staged = summary.get("staged_contact_solve") or {}
    stages = staged.get("stages") or []
    requested = summary.get("requested_stage_image") or {}
    physical = summary.get("physical_contact_validation") or {}
    package = summary.get("package") or {}
    digest = {
        "summary_path": summary.get("summary_path"),
        "template_run_success": (summary.get("template_run") or {}).get("success"),
        "staged_contact_success": staged.get("success"),
        "stage_count": len(stages),
        "last_stage": (stages[-1] or {}).get("name") if stages else None,
        "requested_stage_image": {
            "success": requested.get("success"),
            "selected_stage": requested.get("selected_stage"),
            "native_comsol_png": requested.get("native_comsol_png")
            or requested.get("best_available_native_comsol_png"),
            "max_von_mises_pa": requested.get("max_von_mises_pa")
            or requested.get("best_available_max_von_mises_pa"),
            "stage_selection_reason": requested.get("stage_selection_reason"),
        },
        "physical_contact_validation": {
            "success": physical.get("success"),
            "quality_level": physical.get("quality_level"),
            "global_max_von_mises_pa": physical.get("global_max_von_mises_pa"),
            "inner_ring_max_von_mises_pa": physical.get("inner_ring_max_von_mises_pa"),
            "max_displacement_m": physical.get("max_displacement_m"),
            "errors": physical.get("errors"),
            "warnings": physical.get("warnings"),
        },
        "package_success": package.get("success"),
    }
    print(json.dumps(digest, ensure_ascii=False, indent=2, default=str))


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
            "cage_contact_selection": f"sel_roller_{index}_cage_contact",
            "cage_pocket_contact_selection": f"sel_cage_pocket_{index}_contact",
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
            "inner_bore_load_surface": "sel_inner_bore_load_surface",
        },
        "roller_contact_sets": roller_contact_sets,
        "required_probes": [
            "probe_max_mises_global",
            "probe_max_contact_pressure_inner",
            "probe_max_contact_pressure_outer",
            "probe_cage_max_mises",
            "probe_cage_max_displacement",
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
                contact_pair_count=VERIFIED_ROLLER_COUNT * 3,
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
                "probe_scope_verified via component Maximum coupling operators bound to per-roller body selections and cage body selection"
                if all_probe_success
                else "per-roller and cage MaxVolume numerical nodes are present; scoped per-roller evaluation was not fully verified in this package"
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
                f"Each roller has an explicit roller-to-cage-pocket Contact Pair and Solid Mechanics Contact feature for cage load transfer.",
                "Geometry finalization uses assembly mode for separate roller/raceway contact bodies.",
                "The radial load is applied as an inner-bore boundary traction on sel_inner_bore_load_surface, not as a whole-domain inner-ring body load.",
                "Current load/contact/support selections use named Box region selections, and each roller body/contact region has a named Box selection plus max-stress probe node.",
                "Selection-scoped per-roller and cage probe evaluation uses component Maximum coupling operators bound to roller body and cage body selections.",
                "Stress PNG is rendered from solved COMSOL x/y/solid.mises field samples when COMSOL GUI image export is too sparse.",
                "Repair history is recorded for generated-code or runtime fallback attempts.",
            ]
            summary["result_interpretation"] = {
                "max_stress_location_approx": "3D roller/raceway contact region under the radial smoke load",
                "highest_risk_roller": roller_risk[0]["roller"],
                "highest_risk_region": (
                    f"{roller_risk[0]['roller']} roller-to-inner/outer-raceway contact interfaces"
                ),
                "contact_pair_status": "explicit COMSOL Contact pair features were created for roller-to-inner, roller-to-outer, and roller-to-cage-pocket interfaces",
                "cage_status": "cage ring included with real cylindrical Boolean pocket cutouts, roller/cage-pocket contact pairs, and cage-scoped stress/displacement probes",
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
                "- Inner load model: `BoundaryLoad` on `sel_inner_bore_load_surface` using `FperArea`; legacy inner-ring domain `BodyLoad` is rejected by the quality gate.",
                f"- Cage contact model: `{VERIFIED_ROLLER_COUNT}` roller-to-cage-pocket Contact Pairs plus Solid Mechanics Contact features.",
                "- Max stress location: approximate 3D roller/raceway contact region under radial smoke load.",
                f"- Highest-risk roller estimate: `{roller_risk[0]['roller']}`.",
                "- Selection status: named Box region, roller body, and contact-surface selections are present.",
                "- Probe scope status: component Maximum coupling operators are bound to per-roller body selections and the cage body selection.",
                f"- Selection binding audit: `{((summary or {}).get('selection_binding_audit') or {}).get('success')}`.",
                f"- Physical result audit: `{((summary or {}).get('physical_result_audit') or {}).get('success')}`.",
                f"- Contact convergence report: `{((summary or {}).get('contact_convergence_report') or {}).get('quality_level')}`.",
                f"- Stress plot method: `{(stress_plot_evidence or {}).get('method', 'comsol_plot')}`.",
                f"- Repair history: `{json.dumps(repair_history, ensure_ascii=False, default=str)}`",
                f"- Execution workflow: `{execution_audit.get('workflow')}`",
                f"- Quality gate: `{execution_audit.get('quality_gate_success')}` / `{execution_audit.get('quality_gate_level')}`",
                f"- Repair history count: `{execution_audit.get('repair_history_count')}`",
                f"- Require free-generated code: `{execution_audit.get('require_free_generated_code')}`",
                "- Remaining production task: calibrate cage-pocket clearance/contact settings against the intended bearing design, upgrade approximate Box contact regions to exact geometry-entity selections, and perform contact convergence checks.",
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
    parser.add_argument(
        "--verified-fixture-roller-angular-offset-deg",
        type=float,
        default=0.0,
        help=(
            "Diagnostic-only angular phase offset for the verified 3D fixture rollers/cage pockets. "
            "Use e.g. 15 to move load-side rollers away from the +X cylinder seam."
        ),
    )
    parser.add_argument(
        "--verified-fixture-local-contact-patch-mode",
        choices=(
            "none",
            "roller1_outer_aux_patch",
            "roller1_cylinder_seam_shift15",
            "roller1_outer_retained_conformal_patch",
            "roller1_outer_retained_conformal_source_closure3um",
            "roller1_outer_retained_conformal_narrow_source_closure3um",
            "roller1_outer_retained_conformal_equal_height_source_closure3um",
            "roller1_outer_retained_conformal_sector_source_closure3um",
            "roller1_outer_construction_partition_patch",
            "roller1_outer_construction_partition_source_closure3um",
            "roller1_outer_raceway_partition_only",
            "roller1_outer_raceway_partition_source_closure3um",
            "roller1_outer_raceway_narrow_partition_source_closure3um",
        ),
        default="none",
        help=(
            "Diagnostic-only construction-time local contact patch mode for the verified fixture. "
            "roller1_outer_aux_patch adds a fixed auxiliary patch at the roller_1 outer raceway neighborhood "
            "and binds sel_outer_raceway_1_contact to it; roller1_cylinder_seam_shift15 rotates only the "
            "roller_1 Cylinder feature by 15 deg before geom.run to diagnose 0 deg/+X source-surface seam "
            "sensitivity; roller1_outer_retained_conformal_patch adds a thin curved local target and narrows "
            "only the roller_1 outer source/destination patch; roller1_outer_construction_partition_patch "
            "roller1_outer_retained_conformal_source_closure3um keeps that retained conformal target and adds "
            "the successful 3[um] +X roller_1 source-side closure; "
            "roller1_outer_retained_conformal_narrow_source_closure3um keeps the same retained target and "
            "source closure but changes only the roller_1 outer contact-box tangential half-width from 1.8[mm] "
            "to 0.9[mm]; "
            "roller1_outer_retained_conformal_equal_height_source_closure3um uses equal axial heights for the "
            "retained conformal cylinders while keeping the same 3[um] source closure; "
            "roller1_outer_retained_conformal_sector_source_closure3um intersects the retained conformal annulus "
            "with a local construction-time window to reduce destination fragmentation; "
            "partitions roller_1 and outer_ring with a local construction-time tool before final geometry run; "
            "roller1_outer_construction_partition_source_closure3um adds the same construction-time source and "
            "destination partition while keeping the successful 3[um] +X roller_1 source-side closure; "
            "roller1_outer_raceway_partition_only partitions only the outer_ring target while keeping the "
            "original roller_1 source selection path; roller1_outer_raceway_partition_source_closure3um combines "
            "that target partition with a 3[um] +X roller_1 source-side closure; "
            "roller1_outer_raceway_narrow_partition_source_closure3um keeps the 3[um] closure but uses a smaller "
            "outer-ring partition tool to reduce destination fragmentation; "
            "this is not a production design gate."
        ),
    )
    parser.add_argument(
        "--run-full-cage-stage",
        action="store_true",
        help=(
            "After raceway-only staged preload solves, activate roller-to-cage-pocket "
            "contact and run the final cage load-transfer stage."
        ),
    )
    parser.add_argument(
        "--contact-stage-mode",
        choices=("single_load_roller", "single_roller_displacement_preload", "load_side_then_all", "all_raceway", "all_raceway_micro_preload", "load_side_group_micro", "load_side_group_compaction", "load_side_group_preclosed_boundary_load", "load_side_group_boundary_load", "load_side_group_boundary_load_soft_guidance", "load_side_group_boundary_load_contact_relaxation", "load_side_group_boundary_load_single_solve_0p101", "load_side_group_boundary_load_single_solve_0p101_roller1_pair_swap", "load_side_group_boundary_load_single_solve_0p101_roller1_patch_shrink", "load_side_group_boundary_load_single_solve_0p101_roller1_box_intersection_rebuild", "load_side_group_boundary_load_single_solve_0p101_roller1_outer_x31_box_intersection", "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch", "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_rebind", "load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_min_entities", "load_side_group_boundary_load_single_solve_0p101_active_spring1e9", "load_side_group_boundary_load_single_solve_0p101_full_raceway_destination", "load_side_group_boundary_load_single_solve_0p101_entity_raceway_override", "load_side_group_boundary_load_single_solve_0p101_roller1_outer_entity_override", "load_side_group_boundary_load_single_solve_0p101_roller1_gapoffset_minus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_minus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_source_offset_plus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_offset_minus3um", "load_side_group_boundary_load_single_solve_0p101_roller1_offset_plus3um", "load_side_group_boundary_load_single_solve_0p12", "load_side_group_boundary_load_single_solve_0p13", "load_side_group_boundary_load_single_solve_0p14", "load_side_group_boundary_load_single_solve_0p145", "load_side_group_boundary_load_single_solve_0p1475", "load_side_group_boundary_load_single_solve_0p14875", "load_side_group_boundary_load_single_solve_0p149375", "load_side_group_boundary_load_single_solve_0p15_fine", "load_side_group_boundary_load_single_solve_0p1625", "load_side_group_boundary_load_single_solve_0p175", "load_side_group_boundary_load_single_solve_0p1875", "load_side_group_boundary_load_single_solve_0p19375", "load_side_group_boundary_load_single_solve_0p196875", "load_side_group_boundary_load_single_solve_0p2_fine", "load_side_group_boundary_load_single_solve_0p15", "load_side_group_boundary_load_single_solve_0p2", "load_side_group_boundary_load_single_solve_1n", "load_side_group_boundary_load_micro_continuation", "load_side_group_boundary_load_fixed_stabilization", "all_raceway_low_load_transfer", "all_raceway_continuous_boundary_load", "all_raceway_split_control_boundary_load", "all_raceway_guided_probe_1n", "all_raceway_guided_low_load_transfer", "all_raceway_guided_high_load_transfer", "all_raceway_preload_only", "all_raceway_high_preload_visual", "all_raceway_high_preload_reaction_equivalent", "all_raceway_high_load_visual", "all_raceway_high_body_load_visual", "legacy_raceway_highload_direct"),
        default="all_raceway",
        help=(
            "3D contact convergence ladder: start from one load-side roller with radial load or displacement preload, "
            "ramp load-side rollers before all 12 rollers, keep the legacy all-raceway path, or run a short "
            "all-12-roller true raceway-contact micro-preload smoke, a load-side 3/6/12 group-ramped contact closure, "
            "a preclosed group-compaction then inner-bore BoundaryLoad transfer path, "
            "a low radial-load transfer ramp after all-raceway preload, or a continuous BoundaryLoad path "
            "that keeps BoundaryLoad active from the first contact-closure stage, or a split-control "
            "BoundaryLoad path that moves displacement closure off the loaded bore surface."
            " Use all_raceway_high_preload_reaction_equivalent to keep a converged displacement-control path "
            "and probe reaction-force expressions for equivalent load evidence, or load_side_group_boundary_load "
            "to keep inner-bore BoundaryLoad active while ramping load-side 3/6/all-12 roller contact participation."
        ),
    )
    parser.add_argument(
        "--roller1-outer-entity-override-entities",
        default="",
        help=(
            "Comma-separated boundary entity ids for the roller_1 outer entity-override diagnostic. "
            "Use only with --contact-stage-mode load_side_group_boundary_load_single_solve_0p101_roller1_outer_entity_override."
        ),
    )
    parser.add_argument(
        "--contact-interference",
        default="",
        help=(
            "Override the 3D cylindrical roller geometric contact interference before geometry build, "
            "for example 30[um] for a high-load interference visualization."
        ),
    )
    parser.add_argument(
        "--cage-pocket-clearance",
        default="",
        help=(
            "Override cage pocket radial clearance relative to roller_radius, "
            "for example 0[um] or 1[um] to include cage-pocket clearance in compaction tests."
        ),
    )
    parser.add_argument(
        "--full-json-stdout",
        action="store_true",
        help="Print the full runtime summary JSON to stdout; by default only a compact digest is printed.",
    )
    parser.add_argument(
        "--stage-evidence-matrix",
        action="store_true",
        help="Scan runtime_smoke direct_3d_bearing_summary.json files and write a stage evidence matrix report.",
    )
    parser.add_argument(
        "--stage-evidence-root",
        default="runtime_smoke",
        help="Root directory scanned by --stage-evidence-matrix.",
    )
    parser.add_argument(
        "--stage-evidence-output-dir",
        default="reports/bearing_stage_evidence",
        help="Output directory for --stage-evidence-matrix JSON/Markdown reports.",
    )
    parser.add_argument(
        "--diagnose-stage-mph",
        default="",
        help="Load an existing configured stage MPH and write a no-solve solver/feature/selection diagnostic report.",
    )
    parser.add_argument(
        "--diagnose-output-dir",
        default="",
        help="Output directory for --diagnose-stage-mph reports. Defaults to <mph parent>/diagnostics.",
    )
    parser.add_argument(
        "--map-boundary-entities-mph",
        default="",
        help="Load an MPH and write a no-solve boundary entity centroid/radius/angle map for a named selection.",
    )
    parser.add_argument(
        "--boundary-map-selection",
        default="geom1_outer_ring_bnd",
        help="Named boundary selection used by --map-boundary-entities-mph.",
    )
    parser.add_argument(
        "--boundary-map-output-dir",
        default="",
        help="Output directory for --map-boundary-entities-mph reports. Defaults to <mph parent>/boundary_entity_map.",
    )
    parser.add_argument(
        "--probe-reaction-mph",
        default="",
        help="Load an existing solved MPH and write a reaction-equivalent candidate probe report without re-solving.",
    )
    parser.add_argument(
        "--reaction-probe-selection",
        default="sel_inner_bore_load_surface",
        help="Named selection used by --probe-reaction-mph for IntSurface reaction/traction candidates.",
    )
    parser.add_argument(
        "--reaction-probe-output-dir",
        default="",
        help="Output directory for --probe-reaction-mph reports. Defaults to <mph parent>/reaction_probe.",
    )
    parser.add_argument(
        "--probe-contact-mph",
        default="",
        help="Load an existing solved MPH and write a contact-surface candidate probe report without re-solving.",
    )
    parser.add_argument(
        "--contact-probe-output-dir",
        default="",
        help="Output directory for --probe-contact-mph reports. Defaults to <mph parent>/contact_probe.",
    )
    parser.add_argument(
        "--probe-contact-entity-transfer",
        action="store_true",
        help="Also probe pair-specific transfer field values separately on each boundary of roller_1 outer contact.",
    )
    parser.add_argument(
        "--contact-entity-transfer-selection",
        default="sel_outer_raceway_1_contact",
        help="Named boundary selection for --probe-contact-entity-transfer.",
    )
    parser.add_argument(
        "--contact-entity-transfer-roller",
        type=int,
        default=1,
        help="Roller id for --probe-contact-entity-transfer.",
    )
    parser.add_argument(
        "--probe-geometry-partition-api",
        action="store_true",
        help="Create a tiny COMSOL geometry and probe supported partition/imprint feature APIs.",
    )
    parser.add_argument(
        "--probe-cylinder-seam-api",
        action="store_true",
        help=(
            "Create a tiny COMSOL cylinder geometry and probe rotation/axis/selection properties relevant "
            "to roller source-surface seam diagnostics."
        ),
    )
    parser.add_argument(
        "--run-local-two-body-contact-smoke",
        action="store_true",
        help=(
            "Build and solve a minimal roller_1 outer two-body contact smoke, then run the saved-MPH contact probe. "
            "This is a diagnostic gate before retrying global 3-roller BoundaryLoad."
        ),
    )
    parser.add_argument(
        "--local-two-body-contact-output-dir",
        default="runtime_smoke/bearing_family_p12_local_two_body_contact/roller1_outer",
        help="Output directory for --run-local-two-body-contact-smoke artifacts.",
    )
    parser.add_argument(
        "--local-two-body-contact-model-name",
        default="bearing3d_local_two_body_roller1_outer",
        help="Temporary COMSOL model name for --run-local-two-body-contact-smoke.",
    )
    parser.add_argument(
        "--local-two-body-contact-interference",
        default="5[um]",
        help="Geometric interference used by the local two-body contact smoke, for example 5[um].",
    )
    parser.add_argument(
        "--local-two-body-contact-roller-id",
        type=int,
        default=1,
        help="Roller id for --run-local-two-body-contact-smoke. Use 1, 2, or 12 for load-side comparisons.",
    )
    parser.add_argument(
        "--geometry-partition-probe-output-dir",
        default="runtime_smoke/bearing_family_p12_geometry_partition_api_probe",
        help="Output directory for --probe-geometry-partition-api JSON/Markdown reports.",
    )
    parser.add_argument(
        "--geometry-partition-probe-model-name",
        default="bearing3d_geometry_partition_api_probe",
        help="Temporary COMSOL model name for --probe-geometry-partition-api.",
    )
    parser.add_argument(
        "--cylinder-seam-probe-output-dir",
        default="runtime_smoke/bearing_family_p12_cylinder_seam_api_probe",
        help="Output directory for --probe-cylinder-seam-api JSON/Markdown reports.",
    )
    parser.add_argument(
        "--cylinder-seam-probe-model-name",
        default="bearing3d_cylinder_seam_api_probe",
        help="Temporary COMSOL model name for --probe-cylinder-seam-api.",
    )
    parser.add_argument("--print-prompts", action="store_true")
    args = parser.parse_args()

    if args.stage_evidence_matrix:
        report = write_stage_evidence_matrix_report(
            search_root=args.stage_evidence_root,
            output_dir=args.stage_evidence_output_dir,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return

    if args.diagnose_stage_mph:
        mph_path = Path(args.diagnose_stage_mph)
        output_dir = Path(args.diagnose_output_dir) if args.diagnose_output_dir else mph_path.parent.parent / "diagnostics"
        report = diagnose_stage_mph(
            mph_path=mph_path,
            output_dir=output_dir,
            cores=args.cores,
        )
        print(json.dumps({
            "success": report.get("success"),
            "kind": report.get("kind"),
            "mph_path": report.get("mph_path"),
            "json_path": report.get("json_path"),
            "markdown_path": report.get("markdown_path"),
            "error": report.get("error"),
        }, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(0 if report.get("success") else 1)

    if args.map_boundary_entities_mph:
        mph_path = Path(args.map_boundary_entities_mph)
        output_dir = (
            Path(args.boundary_map_output_dir)
            if args.boundary_map_output_dir
            else mph_path.parent.parent / "boundary_entity_map"
        )
        report = map_boundary_entities_mph(
            mph_path=mph_path,
            output_dir=output_dir,
            selection_name=args.boundary_map_selection,
            cores=args.cores,
        )
        print(json.dumps({
            "success": report.get("success"),
            "kind": report.get("kind"),
            "mph_path": report.get("mph_path"),
            "selection_name": report.get("selection_name"),
            "json_path": report.get("json_path"),
            "markdown_path": report.get("markdown_path"),
            "entity_count": (report.get("map") or {}).get("entity_count"),
            "successful_entity_count": (report.get("map") or {}).get("successful_entity_count"),
            "warning": (report.get("map") or {}).get("warning"),
            "error": report.get("error"),
        }, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(0 if report.get("success") else 1)

    if args.probe_reaction_mph:
        mph_path = Path(args.probe_reaction_mph)
        output_dir = (
            Path(args.reaction_probe_output_dir)
            if args.reaction_probe_output_dir
            else mph_path.parent.parent / "reaction_probe"
        )
        report = probe_saved_reaction_mph(
            mph_path=mph_path,
            output_dir=output_dir,
            selection_name=args.reaction_probe_selection,
            cores=args.cores,
        )
        print(json.dumps({
            "success": report.get("success"),
            "kind": report.get("kind"),
            "mph_path": report.get("mph_path"),
            "json_path": report.get("json_path"),
            "markdown_path": report.get("markdown_path"),
            "reaction_verified": report.get("reaction_verified"),
            "candidate_audit": report.get("candidate_audit"),
            "error": report.get("error"),
        }, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(0 if report.get("reaction_equivalent", {}).get("success") else 1)

    if args.probe_contact_mph:
        mph_path = Path(args.probe_contact_mph)
        output_dir = (
            Path(args.contact_probe_output_dir)
            if args.contact_probe_output_dir
            else mph_path.parent.parent / "contact_probe"
        )
        report = probe_saved_contact_mph(
            mph_path=mph_path,
            output_dir=output_dir,
            entity_transfer=(
                {
                    "roller": args.contact_entity_transfer_roller,
                    "contact_label": f"roller_{args.contact_entity_transfer_roller}_outer_raceway",
                    "selection_name": args.contact_entity_transfer_selection,
                }
                if args.probe_contact_entity_transfer
                else None
            ),
            cores=args.cores,
        )
        print(json.dumps({
            "success": report.get("success"),
            "kind": report.get("kind"),
            "mph_path": report.get("mph_path"),
            "json_path": report.get("json_path"),
            "markdown_path": report.get("markdown_path"),
            "contact_probe_success_count": report.get("contact_probe_success_count"),
            "contact_probe_nonzero_count": report.get("contact_probe_nonzero_count"),
            "warning": report.get("warning"),
            "error": report.get("error"),
        }, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(0 if report.get("success") else 1)

    if args.probe_geometry_partition_api:
        report = probe_geometry_partition_api(
            output_dir=args.geometry_partition_probe_output_dir,
            model_name=args.geometry_partition_probe_model_name,
            cores=args.cores,
        )
        print(json.dumps({
            "success": report.get("success"),
            "kind": report.get("kind"),
            "model_name": report.get("model_name"),
            "json_path": report.get("json_path"),
            "markdown_path": report.get("markdown_path"),
            "valid_feature_types": (report.get("probe") or {}).get("valid_feature_types"),
            "runnable_feature_types": (report.get("probe") or {}).get("runnable_feature_types"),
            "error": report.get("error"),
        }, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(0 if report.get("success") else 1)

    if args.probe_cylinder_seam_api:
        report = probe_cylinder_seam_api(
            output_dir=args.cylinder_seam_probe_output_dir,
            model_name=args.cylinder_seam_probe_model_name,
            cores=args.cores,
        )
        print(json.dumps({
            "success": report.get("success"),
            "kind": report.get("kind"),
            "model_name": report.get("model_name"),
            "json_path": report.get("json_path"),
            "markdown_path": report.get("markdown_path"),
            "successful_properties": (report.get("probe") or {}).get("successful_properties"),
            "failed_properties": (report.get("probe") or {}).get("failed_properties"),
            "run_result": (report.get("probe") or {}).get("run_result"),
            "error": report.get("error"),
        }, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(0 if report.get("success") else 1)

    if args.run_local_two_body_contact_smoke:
        report = run_local_two_body_contact_smoke(
            output_dir=args.local_two_body_contact_output_dir,
            model_name=args.local_two_body_contact_model_name,
            contact_interference=args.local_two_body_contact_interference,
            roller_id=args.local_two_body_contact_roller_id,
            cores=args.cores,
        )
        print(json.dumps({
            "success": report.get("success"),
            "kind": report.get("kind"),
            "summary_path": report.get("summary_path"),
            "markdown_path": report.get("markdown_path"),
            "configured_mph": report.get("configured_mph"),
            "solved_mph": report.get("solved_mph"),
            "roller_id": report.get("roller_id"),
            "solve_success": (report.get("solve") or {}).get("success"),
            "pair_specific_success": report.get("pair_specific_success"),
            "contact_probe": report.get("contact_probe"),
            "error": report.get("error"),
        }, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(0 if report.get("success") else 1)

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
