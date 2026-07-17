"""Built-in simulation skills and template helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from comsol_agent.memory.archive_store import ArchiveStore, SimulationTemplate


@dataclass(frozen=True)
class SimulationSkill:
    """Domain-specific guidance bundle for the agent."""

    name: str
    domain: str
    description: str
    keywords: tuple[str, ...]
    physics_interfaces: tuple[str, ...]
    key_parameters: tuple[str, ...]
    common_checks: tuple[str, ...]
    template_name: str
    template_java_code: str
    template_params: dict[str, Any]

    def matches(self, text: str) -> bool:
        return self.match_score(text) > 0

    def match_score(self, text: str) -> int:
        lowered = text.lower()
        return sum(1 for keyword in self.keywords if _keyword_matches(lowered, keyword.lower()))

    def context_text(self) -> str:
        return (
            f"[Simulation skill: {self.name}]\n"
            f"Domain: {self.domain}\n"
            f"Physics interfaces: {', '.join(self.physics_interfaces)}\n"
            f"Key parameters: {', '.join(self.key_parameters)}\n"
            "Common checks:\n"
            + "\n".join(f"- {check}" for check in self.common_checks)
        )


BEARING_CONTACT_TEMPLATE_CODE = """model.param().set('inner_diameter', '25[mm]');
model.param().set('outer_diameter', '52[mm]');
model.param().set('bearing_width', '15[mm]');
model.param().set('ball_count', '8');
model.param().set('ball_diameter', '7.94[mm]');
model.param().set('groove_radius_factor', '0.52');
model.param().set('radial_load', '1000[N]');
model.param().set('tangential_load', '0[N]');
model.param().set('load_share_factor', '0.22');
model.param().set('friction_coefficient', '0.05');
model.param().set('contact_interference', '2[um]');
model.param().set('E_steel', '210[GPa]');
model.param().set('nu_steel', '0.30');
model.param().set('rho_steel', '7850[kg/m^3]');
model.param().set('contact_span', '12[mm]');
model.param().set('raceway_depth', '3[mm]');
model.param().set('raceway_height', '6[mm]');
model.param().set('mesh_contact_size', '0.08[mm]');
model.param().set('mesh_bulk_size', '0.8[mm]');
model.param().set('per_ball_load', 'radial_load*load_share_factor');
model.param().set('contact_pressure_guess', 'per_ball_load/(bearing_width*ball_diameter)');
model.param().set('tangential_pressure_guess', 'tangential_load/(bearing_width*ball_diameter)');
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
model.component('comp1').geom('geom1').run();
model.component('comp1').material().create('mat_steel', 'Common');
model.component('comp1').material('mat_steel').label('Bearing steel');
model.component('comp1').material('mat_steel').propertyGroup('def').set('youngsmodulus', 'E_steel');
model.component('comp1').material('mat_steel').propertyGroup('def').set('poissonsratio', 'nu_steel');
model.component('comp1').material('mat_steel').propertyGroup('def').set('density', 'rho_steel');
model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
model.component('comp1').physics('solid').create('fix_race', 'Fixed', 1);
model.component('comp1').physics('solid').feature('fix_race').selection().set([2]);
model.component('comp1').physics('solid').create('ball_load', 'BoundaryLoad', 1);
model.component('comp1').physics('solid').feature('ball_load').selection().all();
model.component('comp1').physics('solid').feature('ball_load').set('FperArea', ['tangential_pressure_guess', '-contact_pressure_guess', '0']);
model.component('comp1').mesh().create('mesh1');
model.component('comp1').mesh('mesh1').autoMeshSize(3);
model.study().create('std1');
model.study('std1').create('stat', 'Stationary');
model.study('std1').feature('stat').set('activate', ['solid', 'on']);
model.result().numerical().create('max_von_mises', 'MaxVolume');
model.result().numerical('max_von_mises').set('expr', 'solid.mises');
model.result().numerical().create('max_contact_pressure_estimate', 'EvalGlobal');
model.result().numerical('max_contact_pressure_estimate').set('expr', 'contact_pressure_guess');
model.result().create('pg_stress', 'PlotGroup2D');
model.result('pg_stress').label('von Mises stress');
model.result('pg_stress').create('surf_stress', 'Surface');
model.result('pg_stress').feature('surf_stress').set('expr', 'solid.mises');
output.write('Bearing contact seed built: 2D plane-strain Hertz-style ball/raceway contact cell with default deep-groove bearing parameters. Review generated boundary selections before production solves.');
"""


BEARING_CONTACT_DEFAULTS: dict[str, str] = {
    "inner_diameter": "25[mm]",
    "outer_diameter": "52[mm]",
    "bearing_width": "15[mm]",
    "ball_count": "8",
    "ball_diameter": "7.94[mm]",
    "groove_radius_factor": "0.52",
    "radial_load": "1000[N]",
    "tangential_load": "0[N]",
    "load_share_factor": "0.22",
    "friction_coefficient": "0.05",
    "contact_interference": "2[um]",
    "E_steel": "210[GPa]",
    "nu_steel": "0.30",
    "rho_steel": "7850[kg/m^3]",
    "contact_span": "12[mm]",
    "raceway_depth": "3[mm]",
    "raceway_height": "6[mm]",
    "mesh_contact_size": "0.08[mm]",
    "mesh_bulk_size": "0.8[mm]",
    "per_ball_load": "radial_load*load_share_factor",
    "contact_pressure_guess": "per_ball_load/(bearing_width*ball_diameter)",
    "tangential_pressure_guess": "tangential_load/(bearing_width*ball_diameter)",
}


BEARING_CONTACT_PAIR_TEMPLATE_CODE = """model.param().set('inner_diameter', '25[mm]');
model.param().set('outer_diameter', '52[mm]');
model.param().set('bearing_width', '15[mm]');
model.param().set('ball_count', '8');
model.param().set('ball_diameter', '7.94[mm]');
model.param().set('radial_load', '1000[N]');
model.param().set('tangential_load', '0[N]');
model.param().set('load_share_factor', '0.22');
model.param().set('friction_coefficient', '0.05');
model.param().set('contact_interference', '2[um]');
model.param().set('E_steel', '210[GPa]');
model.param().set('nu_steel', '0.30');
model.param().set('rho_steel', '7850[kg/m^3]');
model.param().set('contact_span', '12[mm]');
model.param().set('raceway_height', '6[mm]');
model.param().set('mesh_contact_size', '0.08[mm]');
model.param().set('mesh_bulk_size', '0.8[mm]');
model.param().set('per_ball_load', 'radial_load*load_share_factor');
model.param().set('contact_pressure_guess', 'per_ball_load/(bearing_width*ball_diameter)');
model.param().set('tangential_pressure_guess', 'tangential_load/(bearing_width*ball_diameter)');
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
model.component('comp1').geom('geom1').run();
model.component('comp1').material().create('mat_steel', 'Common');
model.component('comp1').material('mat_steel').label('Bearing steel');
model.component('comp1').material('mat_steel').propertyGroup('def').set('youngsmodulus', 'E_steel');
model.component('comp1').material('mat_steel').propertyGroup('def').set('poissonsratio', 'nu_steel');
model.component('comp1').material('mat_steel').propertyGroup('def').set('density', 'rho_steel');
model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
model.component('comp1').physics('solid').create('fix_race', 'Fixed', 1);
model.component('comp1').physics('solid').feature('fix_race').selection().set([2]);
pair = model.component('comp1').pair().create('cp_ball_race', 'Contact');
pair.manualSelection(True);
pair.source().geom('geom1', 1);
pair.destination().geom('geom1', 1);
pair.source().set([5]);
pair.destination().set([3]);
model.component('comp1').physics('solid').create('contact_ball_race', 'Contact', 1);
model.component('comp1').physics('solid').feature('contact_ball_race').set('pairs', ['cp_ball_race']);
model.component('comp1').physics('solid').feature('contact_ball_race').set('pfm', 'penalty');
model.component('comp1').physics('solid').create('ball_load', 'BoundaryLoad', 1);
model.component('comp1').physics('solid').feature('ball_load').selection().all();
model.component('comp1').physics('solid').feature('ball_load').set('FperArea', ['tangential_pressure_guess', '-contact_pressure_guess', '0']);
model.component('comp1').mesh().create('mesh1');
model.component('comp1').mesh('mesh1').autoMeshSize(3);
model.study().create('std1');
model.study('std1').create('stat', 'Stationary');
model.study('std1').feature('stat').set('activate', ['solid', 'on']);
model.result().numerical().create('max_von_mises', 'MaxVolume');
model.result().numerical('max_von_mises').set('expr', 'solid.mises');
model.result().numerical().create('max_contact_pressure_estimate', 'EvalGlobal');
model.result().numerical('max_contact_pressure_estimate').set('expr', 'contact_pressure_guess');
model.result().create('pg_stress', 'PlotGroup2D');
model.result('pg_stress').label('von Mises stress - contact pair');
model.result('pg_stress').create('surf_stress', 'Surface');
model.result('pg_stress').feature('surf_stress').set('expr', 'solid.mises');
output.write('Bearing contact pair seed built: 2D ball/raceway model with a COMSOL Contact pair cp_ball_race. Boundary IDs are verified for this generated geometry; review selections before production solves.');
"""


BEARING_CONTACT_PAIR_DEFAULTS: dict[str, str] = {
    key: value
    for key, value in BEARING_CONTACT_DEFAULTS.items()
    if key not in {"groove_radius_factor", "raceway_depth"}
}


PCB_THERMAL_PLATE_TEMPLATE_CODE = """model.param().set('board_length', '80[mm]');
model.param().set('board_width', '50[mm]');
model.param().set('board_thickness', '1.6[mm]');
model.param().set('copper_thickness', '35[um]');
model.param().set('chip1_power', '5[W]');
model.param().set('chip2_power', '5[W]');
model.param().set('chip_size', '8[mm]');
model.param().set('chip_spacing', '24[mm]');
model.param().set('T_ambient', '293.15[K]');
model.param().set('convection_h', '10[W/(m^2*K)]');
model.param().set('k_fr4', '0.35[W/(m*K)]');
model.param().set('k_copper', '385[W/(m*K)]');
model.param().set('k_chip', '120[W/(m*K)]');
model.param().set('rho_fr4', '1850[kg/m^3]');
model.param().set('Cp_fr4', '1100[J/(kg*K)]');
model.param().set('chip_thickness', '0.8[mm]');
model.param().set('chip1_x', '-chip_spacing/2');
model.param().set('chip2_x', 'chip_spacing/2');
model.param().set('chip_heat_density_1', 'chip1_power/(chip_size*chip_size*chip_thickness)');
model.param().set('chip_heat_density_2', 'chip2_power/(chip_size*chip_size*chip_thickness)');
model.component().create('comp1', True);
model.component('comp1').geom().create('geom1', 3);
model.component('comp1').geom('geom1').lengthUnit('mm');
model.component('comp1').geom('geom1').create('fr4_board', 'Block');
model.component('comp1').geom('geom1').feature('fr4_board').label('FR4 substrate');
model.component('comp1').geom('geom1').feature('fr4_board').set('size', ['board_length', 'board_width', 'board_thickness']);
model.component('comp1').geom('geom1').feature('fr4_board').set('base', 'center');
model.component('comp1').geom('geom1').create('copper_top', 'Block');
model.component('comp1').geom('geom1').feature('copper_top').label('Equivalent top copper layer');
model.component('comp1').geom('geom1').feature('copper_top').set('size', ['board_length', 'board_width', 'copper_thickness']);
model.component('comp1').geom('geom1').feature('copper_top').set('base', 'center');
model.component('comp1').geom('geom1').feature('copper_top').set('pos', ['0', '0', 'board_thickness/2+copper_thickness/2']);
model.component('comp1').geom('geom1').create('copper_bottom', 'Block');
model.component('comp1').geom('geom1').feature('copper_bottom').label('Equivalent bottom copper layer');
model.component('comp1').geom('geom1').feature('copper_bottom').set('size', ['board_length', 'board_width', 'copper_thickness']);
model.component('comp1').geom('geom1').feature('copper_bottom').set('base', 'center');
model.component('comp1').geom('geom1').feature('copper_bottom').set('pos', ['0', '0', '-board_thickness/2-copper_thickness/2']);
model.component('comp1').geom('geom1').create('chip1_pkg', 'Block');
model.component('comp1').geom('geom1').feature('chip1_pkg').label('Chip package 1 heat source');
model.component('comp1').geom('geom1').feature('chip1_pkg').set('size', ['chip_size', 'chip_size', 'chip_thickness']);
model.component('comp1').geom('geom1').feature('chip1_pkg').set('base', 'center');
model.component('comp1').geom('geom1').feature('chip1_pkg').set('pos', ['chip1_x', '0', 'board_thickness/2+copper_thickness+chip_thickness/2']);
model.component('comp1').geom('geom1').create('chip2_pkg', 'Block');
model.component('comp1').geom('geom1').feature('chip2_pkg').label('Chip package 2 heat source');
model.component('comp1').geom('geom1').feature('chip2_pkg').set('size', ['chip_size', 'chip_size', 'chip_thickness']);
model.component('comp1').geom('geom1').feature('chip2_pkg').set('base', 'center');
model.component('comp1').geom('geom1').feature('chip2_pkg').set('pos', ['chip2_x', '0', 'board_thickness/2+copper_thickness+chip_thickness/2']);
model.component('comp1').geom('geom1').run();
model.component('comp1').selection().create('sel_fr4_board', 'Box');
model.component('comp1').selection('sel_fr4_board').set('entitydim', '3');
model.component('comp1').selection('sel_fr4_board').set('xmin', '-board_length/2-0.01[mm]');
model.component('comp1').selection('sel_fr4_board').set('xmax', 'board_length/2+0.01[mm]');
model.component('comp1').selection('sel_fr4_board').set('ymin', '-board_width/2-0.01[mm]');
model.component('comp1').selection('sel_fr4_board').set('ymax', 'board_width/2+0.01[mm]');
model.component('comp1').selection('sel_fr4_board').set('zmin', '-board_thickness/2-0.01[mm]');
model.component('comp1').selection('sel_fr4_board').set('zmax', 'board_thickness/2+0.01[mm]');
model.component('comp1').selection('sel_fr4_board').set('condition', 'inside');
model.component('comp1').selection().create('sel_copper_top', 'Box');
model.component('comp1').selection('sel_copper_top').set('entitydim', '3');
model.component('comp1').selection('sel_copper_top').set('xmin', '-board_length/2-0.01[mm]');
model.component('comp1').selection('sel_copper_top').set('xmax', 'board_length/2+0.01[mm]');
model.component('comp1').selection('sel_copper_top').set('ymin', '-board_width/2-0.01[mm]');
model.component('comp1').selection('sel_copper_top').set('ymax', 'board_width/2+0.01[mm]');
model.component('comp1').selection('sel_copper_top').set('zmin', 'board_thickness/2-0.001[mm]');
model.component('comp1').selection('sel_copper_top').set('zmax', 'board_thickness/2+copper_thickness+0.001[mm]');
model.component('comp1').selection('sel_copper_top').set('condition', 'inside');
model.component('comp1').selection().create('sel_copper_bottom', 'Box');
model.component('comp1').selection('sel_copper_bottom').set('entitydim', '3');
model.component('comp1').selection('sel_copper_bottom').set('xmin', '-board_length/2-0.01[mm]');
model.component('comp1').selection('sel_copper_bottom').set('xmax', 'board_length/2+0.01[mm]');
model.component('comp1').selection('sel_copper_bottom').set('ymin', '-board_width/2-0.01[mm]');
model.component('comp1').selection('sel_copper_bottom').set('ymax', 'board_width/2+0.01[mm]');
model.component('comp1').selection('sel_copper_bottom').set('zmin', '-board_thickness/2-copper_thickness-0.001[mm]');
model.component('comp1').selection('sel_copper_bottom').set('zmax', '-board_thickness/2+0.001[mm]');
model.component('comp1').selection('sel_copper_bottom').set('condition', 'inside');
model.component('comp1').selection().create('sel_chip1_pkg', 'Box');
model.component('comp1').selection('sel_chip1_pkg').set('entitydim', '3');
model.component('comp1').selection('sel_chip1_pkg').set('xmin', 'chip1_x-chip_size/2-0.001[mm]');
model.component('comp1').selection('sel_chip1_pkg').set('xmax', 'chip1_x+chip_size/2+0.001[mm]');
model.component('comp1').selection('sel_chip1_pkg').set('ymin', '-chip_size/2-0.001[mm]');
model.component('comp1').selection('sel_chip1_pkg').set('ymax', 'chip_size/2+0.001[mm]');
model.component('comp1').selection('sel_chip1_pkg').set('zmin', 'board_thickness/2+copper_thickness-0.001[mm]');
model.component('comp1').selection('sel_chip1_pkg').set('zmax', 'board_thickness/2+copper_thickness+chip_thickness+0.001[mm]');
model.component('comp1').selection('sel_chip1_pkg').set('condition', 'inside');
model.component('comp1').selection().create('sel_chip2_pkg', 'Box');
model.component('comp1').selection('sel_chip2_pkg').set('entitydim', '3');
model.component('comp1').selection('sel_chip2_pkg').set('xmin', 'chip2_x-chip_size/2-0.001[mm]');
model.component('comp1').selection('sel_chip2_pkg').set('xmax', 'chip2_x+chip_size/2+0.001[mm]');
model.component('comp1').selection('sel_chip2_pkg').set('ymin', '-chip_size/2-0.001[mm]');
model.component('comp1').selection('sel_chip2_pkg').set('ymax', 'chip_size/2+0.001[mm]');
model.component('comp1').selection('sel_chip2_pkg').set('zmin', 'board_thickness/2+copper_thickness-0.001[mm]');
model.component('comp1').selection('sel_chip2_pkg').set('zmax', 'board_thickness/2+copper_thickness+chip_thickness+0.001[mm]');
model.component('comp1').selection('sel_chip2_pkg').set('condition', 'inside');
model.component('comp1').selection().create('sel_copper_layers', 'Union');
model.component('comp1').selection('sel_copper_layers').set('entitydim', '3');
model.component('comp1').selection('sel_copper_layers').set('input', ['sel_copper_top', 'sel_copper_bottom']);
model.component('comp1').selection().create('sel_chip_packages', 'Union');
model.component('comp1').selection('sel_chip_packages').set('entitydim', '3');
model.component('comp1').selection('sel_chip_packages').set('input', ['sel_chip1_pkg', 'sel_chip2_pkg']);
model.component('comp1').selection().create('sel_conv_bottom', 'Box');
model.component('comp1').selection('sel_conv_bottom').set('entitydim', '2');
model.component('comp1').selection('sel_conv_bottom').set('xmin', '-board_length/2-0.01[mm]');
model.component('comp1').selection('sel_conv_bottom').set('xmax', 'board_length/2+0.01[mm]');
model.component('comp1').selection('sel_conv_bottom').set('ymin', '-board_width/2-0.01[mm]');
model.component('comp1').selection('sel_conv_bottom').set('ymax', 'board_width/2+0.01[mm]');
model.component('comp1').selection('sel_conv_bottom').set('zmin', '-board_thickness/2-copper_thickness-0.002[mm]');
model.component('comp1').selection('sel_conv_bottom').set('zmax', '-board_thickness/2-copper_thickness+0.002[mm]');
model.component('comp1').selection('sel_conv_bottom').set('condition', 'intersects');
model.component('comp1').selection().create('sel_conv_sides', 'Box');
model.component('comp1').selection('sel_conv_sides').set('entitydim', '2');
model.component('comp1').selection('sel_conv_sides').set('xmin', '-board_length/2-0.01[mm]');
model.component('comp1').selection('sel_conv_sides').set('xmax', 'board_length/2+0.01[mm]');
model.component('comp1').selection('sel_conv_sides').set('ymin', '-board_width/2-0.01[mm]');
model.component('comp1').selection('sel_conv_sides').set('ymax', 'board_width/2+0.01[mm]');
model.component('comp1').selection('sel_conv_sides').set('zmin', '-board_thickness/2-copper_thickness-0.001[mm]');
model.component('comp1').selection('sel_conv_sides').set('zmax', 'board_thickness/2+copper_thickness+chip_thickness+0.001[mm]');
model.component('comp1').selection('sel_conv_sides').set('condition', 'intersects');
model.component('comp1').selection().create('sel_conv_chip_tops', 'Box');
model.component('comp1').selection('sel_conv_chip_tops').set('entitydim', '2');
model.component('comp1').selection('sel_conv_chip_tops').set('xmin', '-board_length/2-0.01[mm]');
model.component('comp1').selection('sel_conv_chip_tops').set('xmax', 'board_length/2+0.01[mm]');
model.component('comp1').selection('sel_conv_chip_tops').set('ymin', '-board_width/2-0.01[mm]');
model.component('comp1').selection('sel_conv_chip_tops').set('ymax', 'board_width/2+0.01[mm]');
model.component('comp1').selection('sel_conv_chip_tops').set('zmin', 'board_thickness/2+copper_thickness+chip_thickness-0.002[mm]');
model.component('comp1').selection('sel_conv_chip_tops').set('zmax', 'board_thickness/2+copper_thickness+chip_thickness+0.002[mm]');
model.component('comp1').selection('sel_conv_chip_tops').set('condition', 'intersects');
model.component('comp1').cpl().create('maxop1', 'Maximum');
model.component('comp1').cpl('maxop1').selection().all();
model.component('comp1').material().create('mat_fr4', 'Common');
model.component('comp1').material('mat_fr4').label('FR4 substrate engineering thermal material');
model.component('comp1').material('mat_fr4').selection().named('sel_fr4_board');
model.component('comp1').material('mat_fr4').propertyGroup('def').set('thermalconductivity', ['k_fr4', '0', '0', '0', 'k_fr4', '0', '0', '0', 'k_fr4']);
model.component('comp1').material('mat_fr4').propertyGroup('def').set('density', 'rho_fr4');
model.component('comp1').material('mat_fr4').propertyGroup('def').set('heatcapacity', 'Cp_fr4');
model.component('comp1').material().create('mat_copper', 'Common');
model.component('comp1').material('mat_copper').label('Equivalent high-conductivity copper layers');
model.component('comp1').material('mat_copper').selection().named('sel_copper_layers');
model.component('comp1').material('mat_copper').propertyGroup('def').set('thermalconductivity', ['k_copper', '0', '0', '0', 'k_copper', '0', '0', '0', 'k_copper']);
model.component('comp1').material().create('mat_chip', 'Common');
model.component('comp1').material('mat_chip').label('Simplified chip package thermal path');
model.component('comp1').material('mat_chip').selection().named('sel_chip_packages');
model.component('comp1').material('mat_chip').propertyGroup('def').set('thermalconductivity', ['k_chip', '0', '0', '0', 'k_chip', '0', '0', '0', 'k_chip']);
model.component('comp1').physics().create('ht', 'HeatTransfer', 'geom1');
model.component('comp1').physics('ht').create('chip1_heat', 'HeatSource', 3);
model.component('comp1').physics('ht').feature('chip1_heat').label('Chip 1 volumetric package heat source');
model.component('comp1').physics('ht').feature('chip1_heat').selection().named('sel_chip1_pkg');
model.component('comp1').physics('ht').feature('chip1_heat').set('Q0', 'chip_heat_density_1');
model.component('comp1').physics('ht').create('chip2_heat', 'HeatSource', 3);
model.component('comp1').physics('ht').feature('chip2_heat').label('Chip 2 volumetric package heat source');
model.component('comp1').physics('ht').feature('chip2_heat').selection().named('sel_chip2_pkg');
model.component('comp1').physics('ht').feature('chip2_heat').set('Q0', 'chip_heat_density_2');
model.component('comp1').physics('ht').create('conv_bottom', 'HeatFluxBoundary', 2);
model.component('comp1').physics('ht').feature('conv_bottom').label('Bottom copper convection cooling');
model.component('comp1').physics('ht').feature('conv_bottom').selection().named('sel_conv_bottom');
model.component('comp1').physics('ht').feature('conv_bottom').set('HeatFluxType', 'ConvectiveHeatFlux');
model.component('comp1').physics('ht').feature('conv_bottom').set('h', 'convection_h');
model.component('comp1').physics('ht').feature('conv_bottom').set('Text', 'T_ambient');
model.component('comp1').physics('ht').create('conv_sides', 'HeatFluxBoundary', 2);
model.component('comp1').physics('ht').feature('conv_sides').label('Board edge and package side convection cooling');
model.component('comp1').physics('ht').feature('conv_sides').selection().named('sel_conv_sides');
model.component('comp1').physics('ht').feature('conv_sides').set('HeatFluxType', 'ConvectiveHeatFlux');
model.component('comp1').physics('ht').feature('conv_sides').set('h', 'convection_h');
model.component('comp1').physics('ht').feature('conv_sides').set('Text', 'T_ambient');
model.component('comp1').physics('ht').create('conv_chip_tops', 'HeatFluxBoundary', 2);
model.component('comp1').physics('ht').feature('conv_chip_tops').label('Chip package top convection cooling');
model.component('comp1').physics('ht').feature('conv_chip_tops').selection().named('sel_conv_chip_tops');
model.component('comp1').physics('ht').feature('conv_chip_tops').set('HeatFluxType', 'ConvectiveHeatFlux');
model.component('comp1').physics('ht').feature('conv_chip_tops').set('h', 'convection_h');
model.component('comp1').physics('ht').feature('conv_chip_tops').set('Text', 'T_ambient');
model.component('comp1').mesh().create('mesh1');
model.component('comp1').mesh('mesh1').autoMeshSize(3);
model.study().create('std1');
model.study('std1').create('stat', 'Stationary');
model.study('std1').feature('stat').set('activate', ['ht', 'on']);
model.result().numerical().create('max_board_temperature', 'MaxVolume');
model.result().numerical('max_board_temperature').set('expr', 'T');
model.result().numerical().create('chip_hotspot_indicator', 'EvalGlobal');
model.result().numerical('chip_hotspot_indicator').set('expr', 'maxop1(T)');
model.result().create('pg_temperature', 'PlotGroup3D');
model.result('pg_temperature').label('PCB temperature field');
model.result('pg_temperature').create('surf_temperature', 'Surface');
model.result('pg_temperature').feature('surf_temperature').set('expr', 'T');
output.write('PCB engineering pure-thermal seed built: FR4 substrate, equivalent copper layers, two chip package heat sources, simplified chip-to-board thermal path, convection cooling, Heat Transfer in Solids, stationary study, and temperature outputs. This is a pure thermal starter template; electric currents and Joule heating are follow-up extensions.');
"""


PCB_THERMAL_PLATE_DEFAULTS: dict[str, str] = {
    "board_length": "80[mm]",
    "board_width": "50[mm]",
    "board_thickness": "1.6[mm]",
    "copper_thickness": "35[um]",
    "chip1_power": "5[W]",
    "chip2_power": "5[W]",
    "chip_size": "8[mm]",
    "chip_spacing": "24[mm]",
    "T_ambient": "293.15[K]",
    "convection_h": "10[W/(m^2*K)]",
    "k_fr4": "0.35[W/(m*K)]",
    "k_copper": "385[W/(m*K)]",
    "k_chip": "120[W/(m*K)]",
    "rho_fr4": "1850[kg/m^3]",
    "Cp_fr4": "1100[J/(kg*K)]",
}


BUILTIN_SKILLS: tuple[SimulationSkill, ...] = (
    SimulationSkill(
        name="thermal",
        domain="thermal",
        description="Heat transfer simulations in solids and fluids.",
        keywords=("thermal", "heat", "temperature", "cooling", "conduction", "convection"),
        physics_interfaces=("Heat Transfer in Solids (ht)", "Heat Transfer in Fluids"),
        key_parameters=("thermal conductivity", "heat capacity", "density", "heat flux"),
        common_checks=(
            "Validate units for heat power, heat flux, and temperature.",
            "Inspect mesh density near heat sources and material interfaces.",
            "Check boundary conditions for insulation, convection, and fixed temperature.",
        ),
        template_name="thermal_heat_transfer_seed",
        template_java_code=(
            "model.param().set('power', '10[W]');\n"
            "model.param().set('T_ambient', '293.15[K]');\n"
            "// Add geometry, material, Heat Transfer physics, mesh, and study before solve."
        ),
        template_params={"power": "10[W]", "T_ambient": "293.15[K]"},
    ),
    SimulationSkill(
        name="pcb_thermal",
        domain="thermal",
        description=(
            "Engineering pure-thermal PCB starter model with FR4 substrate, equivalent copper layers, "
            "two chip package heat sources, convection cooling, and temperature postprocessing."
        ),
        keywords=(
            "pcb",
            "circuit board",
            "fr4",
            "chip",
            "copper layer",
            "convection",
            "thermal pcb",
            "电路板",
            "线路板",
            "芯片",
            "铜层",
            "热仿真",
            "对流",
        ),
        physics_interfaces=("Heat Transfer in Solids (ht)", "Stationary study"),
        key_parameters=(
            "board_length",
            "board_width",
            "board_thickness",
            "copper_thickness",
            "chip1_power",
            "chip2_power",
            "chip_size",
            "chip_spacing",
            "T_ambient",
            "convection_h",
            "k_fr4",
            "k_copper",
            "k_chip",
        ),
        common_checks=(
            "Use pcb_thermal_plate_seed as a pure-thermal engineering starter for FR4 PCB hotspot studies.",
            "Keep Electric Currents and Joule Heating out of this starter; add them in a later coupled model.",
            "Check chip power, convection coefficient, copper layer assumptions, and hotspot temperature outputs.",
            "Treat chip-to-board thermal contact as an equivalent package/conduction path until detailed stackup data is available.",
        ),
        template_name="pcb_thermal_plate_seed",
        template_java_code=PCB_THERMAL_PLATE_TEMPLATE_CODE,
        template_params=PCB_THERMAL_PLATE_DEFAULTS,
    ),
    SimulationSkill(
        name="structural",
        domain="structural",
        description="Solid mechanics simulations for stress, strain, and displacement.",
        keywords=("structural", "stress", "strain", "solid mechanics", "deformation", "load"),
        physics_interfaces=("Solid Mechanics (solid)", "Shell", "Beam"),
        key_parameters=("Young's modulus", "Poisson's ratio", "density", "load"),
        common_checks=(
            "Validate constraints and load directions.",
            "Watch for stress singularities near sharp corners and point loads.",
            "Check whether geometric nonlinearity is needed for large deformation.",
        ),
        template_name="structural_solid_mechanics_seed",
        template_java_code=(
            "model.param().set('E', '210[GPa]');\n"
            "model.param().set('nu', '0.3');\n"
            "// Add geometry, material, Solid Mechanics physics, mesh, and study before solve."
        ),
        template_params={"E": "210[GPa]", "nu": "0.3"},
    ),
    SimulationSkill(
        name="bearing_contact",
        domain="structural",
        description=(
            "Deep-groove ball bearing contact simulations using Solid Mechanics, "
            "Hertz/contact assumptions, and stress/contact-pressure postprocessing."
        ),
        keywords=(
            "bearing",
            "ball bearing",
            "deep groove",
            "raceway",
            "rolling element",
            "hertz",
            "hertzian",
            "contact",
            "轴承",
            "滚珠",
            "接触",
            "赫兹",
        ),
        physics_interfaces=("Solid Mechanics (solid)", "Contact pair/contact feature", "Stationary study"),
        key_parameters=(
            "inner_diameter",
            "outer_diameter",
            "bearing_width",
            "ball_count",
            "ball_diameter",
            "radial_load",
            "friction_coefficient",
            "contact_interference",
            "mesh_contact_size",
        ),
        common_checks=(
            "If the user omits bearing parameters, ask for bearing type, dimensions, load, and material; if they want a quick demo, use the template defaults and state the assumptions.",
            "Start from the built-in bearing_contact_hertz_seed template before drafting new contact code.",
            "For tractable first runs, use a 2D plane-strain single-ball/raceway contact cell; full 3D multi-ball contact is a heavier follow-up model.",
            "Refine mesh near contact boundaries and check convergence/contact pressure before trusting peak stress values.",
            "Report von Mises stress, displacement, estimated/contact pressure, and exported stress plot paths when available.",
            "For generated bearing models, bind load/support/contact physics to named selections and verify those selections at runtime before packaging results.",
            "Reject a result as physically validated if the expected bearing body has near-zero stress, even when a global stress field or plot exists.",
        ),
        template_name="bearing_contact_hertz_seed",
        template_java_code=BEARING_CONTACT_TEMPLATE_CODE,
        template_params=BEARING_CONTACT_DEFAULTS,
    ),
    SimulationSkill(
        name="bearing_contact_pair",
        domain="structural",
        description=(
            "More realistic 2D ball-bearing contact setup using an explicit COMSOL "
            "Contact pair between the rolling element and raceway."
        ),
        keywords=(
            "bearing",
            "ball bearing",
            "raceway",
            "contact pair",
            "realistic",
            "production",
            "接触对",
            "真实",
            "更真实",
            "生产级",
            "轴承",
        ),
        physics_interfaces=("Solid Mechanics (solid)", "Contact pair cp_ball_race", "Stationary study"),
        key_parameters=(
            "inner_diameter",
            "outer_diameter",
            "bearing_width",
            "ball_count",
            "ball_diameter",
            "radial_load",
            "friction_coefficient",
            "contact_interference",
            "mesh_contact_size",
        ),
        common_checks=(
            "Use bearing_contact_pair_seed when the user asks for a more realistic COMSOL contact-pair bearing model.",
            "The current contact-pair seed is a 2D single-ball/raceway cell; inspect and refine generated boundary IDs before production use.",
            "Check nonlinear contact convergence, mesh sensitivity near the ball/raceway interface, and whether frictional contact is needed.",
            "For full bearing load sharing, extend to a 3D multi-ball sector or complete bearing model after this 2D contact path is stable.",
            "For 3D roller-bearing generated code, use mutually exclusive roller contact source selections and intersect load/support regions with the intended object boundary or domain selections.",
            "Package only solved stages with nonzero expected-body stress/displacement and nonblank stress images; archive later-stage cage/radial-load failures as failures, not success.",
        ),
        template_name="bearing_contact_pair_seed",
        template_java_code=BEARING_CONTACT_PAIR_TEMPLATE_CODE,
        template_params=BEARING_CONTACT_PAIR_DEFAULTS,
    ),
    SimulationSkill(
        name="electromagnetic",
        domain="electromagnetic",
        description="Electric, magnetic, and current-field simulations.",
        keywords=("electromagnetic", "electric", "magnetic", "voltage", "current", "field"),
        physics_interfaces=("Electrostatics (es)", "Magnetic Fields (mf)", "Electric Currents (ec)"),
        key_parameters=("permittivity", "permeability", "conductivity", "frequency"),
        common_checks=(
            "Confirm excitation and ground/reference conditions.",
            "Check mesh quality in narrow gaps and high-gradient regions.",
            "Verify material properties for frequency-dependent studies.",
        ),
        template_name="electromagnetic_field_seed",
        template_java_code=(
            "model.param().set('V0', '1[V]');\n"
            "model.param().set('freq', '1[kHz]');\n"
            "// Add geometry, materials, EM physics, mesh, and study before solve."
        ),
        template_params={"V0": "1[V]", "freq": "1[kHz]"},
    ),
    SimulationSkill(
        name="fluid",
        domain="fluid",
        description="Laminar or turbulent flow simulations.",
        keywords=("fluid", "flow", "velocity", "pressure", "laminar", "turbulent", "reynolds"),
        physics_interfaces=("Laminar Flow (spf)", "Turbulent Flow"),
        key_parameters=("viscosity", "density", "inlet velocity", "pressure"),
        common_checks=(
            "Estimate Reynolds number before choosing laminar or turbulent physics.",
            "Use boundary-layer mesh near walls when needed.",
            "Check inlet, outlet, wall, and symmetry boundary conditions.",
        ),
        template_name="fluid_flow_seed",
        template_java_code=(
            "model.param().set('U_in', '1[m/s]');\n"
            "model.param().set('rho', '1000[kg/m^3]');\n"
            "model.param().set('mu', '1e-3[Pa*s]');\n"
            "// Add geometry, material, flow physics, mesh, and study before solve."
        ),
        template_params={"U_in": "1[m/s]", "rho": "1000[kg/m^3]", "mu": "1e-3[Pa*s]"},
    ),
)


def list_skills() -> list[SimulationSkill]:
    """Return built-in simulation skills."""
    return list(BUILTIN_SKILLS)


def _keyword_matches(text: str, keyword: str) -> bool:
    escaped = re.escape(keyword)
    return re.search(rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])", text) is not None


def get_skill(name: str) -> SimulationSkill:
    """Return a skill by name or domain."""
    normalized = name.lower()
    for skill in BUILTIN_SKILLS:
        if skill.name == normalized or skill.domain == normalized:
            return skill
    raise KeyError(f"Unknown simulation skill: {name}")


def match_skills(text: str, limit: int = 2) -> list[SimulationSkill]:
    """Match skills by domain keywords."""
    matches = [
        skill
        for _, skill in sorted(
            ((skill.match_score(text), skill) for skill in BUILTIN_SKILLS),
            key=lambda item: item[0],
            reverse=True,
        )
        if skill.matches(text)
    ]
    return matches[:limit]


def build_skill_context_message(skills: list[SimulationSkill]) -> dict[str, str] | None:
    """Build an OpenAI-style context message for matched skills."""
    if not skills:
        return None
    return {
        "role": "user",
        "content": "\n\n".join(skill.context_text() for skill in skills),
    }


def seed_builtin_templates(archive_store: ArchiveStore) -> list[SimulationTemplate]:
    """Upsert built-in skill templates into the archive template table."""
    templates = []
    for skill in BUILTIN_SKILLS:
        templates.append(
            archive_store.add_template(
                name=skill.template_name,
                domain=skill.domain,
                java_code=skill.template_java_code,
                params=skill.template_params,
            )
        )
    return templates
