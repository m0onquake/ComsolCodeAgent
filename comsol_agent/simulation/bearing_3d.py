"""Reusable 3D bearing generation contracts and offline quality gates."""

from __future__ import annotations

import json
import math
import re
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


VERIFIED_ROLLER_COUNT = 12
SEGMENT_MARKER_MANIFEST_START = "SEGMENT_MANIFEST_START"
SEGMENT_MARKER_MANIFEST_END = "SEGMENT_MANIFEST_END"
SELECTION_BINDING_PROBE_START = "SELECTION_BINDING_PROBE_START"
SELECTION_BINDING_PROBE_END = "SELECTION_BINDING_PROBE_END"


def _variant_terminal_tag(tag: str, *, roller_count: int) -> str:
    return re.sub(r"(?<!\d)12(?!\d)", str(roller_count), tag)


def _required_creates_for_variant(spec: "Segmented3DCodeSpec", *, roller_count: int) -> tuple[str, ...]:
    if int(roller_count) == VERIFIED_ROLLER_COUNT:
        return spec.required_creates
    if spec.segment_id not in {"B_cage_pockets_and_rollers", "C_selections_contacts_physics", "D_mesh_study_results"}:
        return spec.required_creates
    return tuple(_variant_terminal_tag(tag, roller_count=int(roller_count)) for tag in spec.required_creates)


def _format_mm_bound(value: float) -> str:
    text = f"{float(value):.12g}".lower()
    if "e" not in text and "." not in text:
        text += ".0"
    return f"{text}[mm]"


def _geometry_feature_radii(java_code: str) -> dict[str, str]:
    radii: dict[str, str] = {}
    for tag, radius in re.findall(
        r"\.feature\(\s*['\"]([^'\"]+)['\"]\s*\)\.set\(\s*['\"]r['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)",
        java_code,
        flags=re.IGNORECASE,
    ):
        radii[tag.lower()] = re.sub(r"\s+", "", radius.lower())
    return radii


def _difference_input_tags(java_code: str, feature_tag: str, slot: str) -> list[str]:
    match = re.search(
        rf"\.feature\(\s*['\"]{re.escape(feature_tag)}['\"]\s*\)"
        rf"\.selection\(\s*['\"]{re.escape(slot)}['\"]\s*\)\.set\(\s*\[([^\]]*)\]\s*\)",
        java_code,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    return [tag.lower() for tag in re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))]


def _difference_slot_contains_radius(java_code: str, feature_tag: str, slot: str, radius_expr: str) -> bool:
    radii = _geometry_feature_radii(java_code)
    expected = re.sub(r"\s+", "", radius_expr.lower())
    return any(radii.get(tag) == expected for tag in _difference_input_tags(java_code, feature_tag, slot))


def _has_contact_selection_angular_offset(java_code: str, expected_deg: float) -> bool:
    """Accept an offset local or an explicit phase-aware roller-angle list."""
    lowered = java_code.lower()
    local_match = re.search(
        r"\b(?:roller_angular_offset_deg|offset_deg)\s*=\s*([-+]?\d+(?:\.\d+)?)\b",
        lowered,
    )
    local_is_expected = bool(
        local_match
        and math.isclose(float(local_match.group(1)), float(expected_deg), abs_tol=1.0e-12)
    )
    local_used = bool(
        re.search(r"\bangle\s*=\s*offset_rad\s*\+", lowered)
        or re.search(r"\boffset_rad\s*=\s*math\.radians\([^\n]+\)", lowered)
    )
    explicit_angle_list = bool(
        re.search(
            rf"\broller_angles_deg\s*=\s*\[\s*{re.escape(f'{float(expected_deg):g}')}"
            r"(?:\.0+)?\s*\+",
            lowered,
        )
    )
    return (local_is_expected and local_used) or explicit_angle_list


def _model_parameter_numeric_value(java_code: str, name: str) -> float | None:
    match = re.search(
        rf"model\.param\(\)\.set\(\s*['\"]{re.escape(name)}['\"]\s*,\s*"
        r"['\"]\s*([-+]?\d+(?:\.\d+)?)",
        java_code,
        flags=re.IGNORECASE,
    )
    return float(match.group(1)) if match else None


def _contact_feature_variable_names(java_code: str) -> set[str]:
    return {
        variable
        for variable in re.findall(
            r"(?m)^\s*(\w+)\s*=\s*(?:model\.component\(\s*['\"]comp1['\"]\s*\)\.physics\(\s*['\"]solid['\"]\s*\)|solid)"
            r"(?:\.feature\(\))?\.create\(\s*['\"]contact[^'\"]*['\"]\s*,\s*['\"]contact['\"]",
            java_code,
            flags=re.IGNORECASE,
        )
    }


def _has_pair_bound_contact_selection_edit(java_code: str) -> bool:
    if re.search(
        r"feature\(\s*['\"]contact[^'\"]*['\"]\s*\)\.selection\(\)\.(?:named|set)\(",
        java_code,
        flags=re.IGNORECASE,
    ):
        return True
    return any(
        re.search(
            rf"(?m)^\s*{re.escape(variable)}\.selection\(\)\.(?:named|set)\(",
            java_code,
            flags=re.IGNORECASE,
        )
        for variable in _contact_feature_variable_names(java_code)
    )


@dataclass(frozen=True)
class Segmented3DCodeSpec:
    """Local contract for one generated 3D bearing code segment."""

    segment_id: str
    title: str
    goal: str
    depends_on: tuple[str, ...]
    required_creates: tuple[str, ...]
    allowed_prefixes: tuple[str, ...]
    forbidden_snippets: tuple[str, ...]


SEGMENTED_3D_CODE_SPECS: tuple[Segmented3DCodeSpec, ...] = (
    Segmented3DCodeSpec(
        segment_id="A_base_geometry",
        title="parameters, component, base ring and cage annulus geometry",
        goal=(
            "Create parameters, comp1, geom1, and Boolean Difference outputs tagged exactly inner_ring, "
            "outer_ring, and cage_annulus; enable selresult and set selresultshow='all' on each of those three "
            "outputs so geom1_inner_ring_bnd, geom1_outer_ring_bnd, and geom1_cage_dom are created. Use a zero-clearance reference "
            "with inner_diameter=40[mm], inner_race_outer_radius=27[mm], pitch_radius=31[mm], "
            "outer_race_inner_radius=35[mm], outer_diameter=80[mm], bearing_width=18[mm], "
            "roller_diameter=8[mm], roller_length=16[mm], cage_width=16[mm], "
            "cage_inner_radius=27.2[mm], and cage_outer_radius=34.8[mm]. Build cage_annulus from those explicit "
            "cage radii with height cage_width and z position -cage_width/2; never derive cage radii from "
            "pitch_radius +/- cage_width/2. "
            "Define radial_load=10.099982438539563[N], inner_radial_displacement=0[um], "
            "cage_pocket_clearance=0.2[mm], mesh_bulk_size=5[mm], and mesh_contact_size=2.4[mm]. "
            "The ring Boolean order is mandatory: inner_ring must subtract the inner bore cylinder "
            "with radius inner_diameter/2 from the larger inner race cylinder with radius inner_race_outer_radius; "
            "outer_ring must subtract the raceway void cylinder with radius outer_race_inner_radius from the "
            "larger outer cylinder with radius outer_diameter/2. Never subtract a larger race cylinder from "
            "the smaller inner-bore cylinder. "
            "Immediately after creating geom1 call model.component('comp1').geom('geom1').lengthUnit('mm'). "
            "All dimensional expressions passed to COMSOL must be unit-aware strings. "
            "Do not create rollers, cage pockets, physics, mesh, study, result, or geom.run()."
        ),
        depends_on=(),
        required_creates=("comp1", "geom1", "inner_ring", "outer_ring", "cage_annulus"),
        allowed_prefixes=("comp", "geom", "inner", "outer", "cage_annulus", "param", "mat"),
        forbidden_snippets=(
            "import mph",
            "model = mph.Model",
            "model.parameter(",
            "model.component.create",
            "model.component('comp1').geom.create",
            'model.component("comp1").geom.create',
            "geom('geom1').run",
            "study()",
            "result()",
            "physics()",
            "mesh()",
            ".create('cage_pocket_",
            '.create("cage_pocket_',
            ".create('roller_",
            '.create("roller_',
            "pair().create",
            ".set('name'",
            '.set("name"',
            ".set('resulting'",
            '.set("resulting"',
            "model.param().evaluate(",
        ),
    ),
    Segmented3DCodeSpec(
        segment_id="B_cage_pockets_and_rollers",
        title="cage Boolean pocket cutters, cage Difference, and twelve rollers",
        goal=(
            "Continue from segment A. Create cage_pocket_1..cage_pocket_12, cage Difference, "
            "and roller_1..roller_12 only. Place every roller and pocket from Python numeric millimetre constants "
            "computed with pitch_radius_mm=31.0 and angle=2*pi*i/12; pass positions as homogeneous string lists "
            "such as [f'{cx:.12g}[mm]', f'{cy:.12g}[mm]', '-roller_length/2']. Use r='roller_diameter/2' "
            "for rollers and r='roller_diameter/2+cage_pocket_clearance' for pockets. "
            "Use h='roller_length' and pos z='-roller_length/2' for both rollers and pocket cutters; do not call "
            "model.param().get/evaluate and do not convert COMSOL parameter strings with float(). "
            "Enable selresult on each roller and on the final cage Difference output; set selresultshow='all' "
            "wherever selresult is enabled. "
            "After all geometry objects exist, set the existing geom1 finalization feature with "
            "model.component('comp1').geom('geom1').feature('fin').set('action','assembly') and call geom1.run() "
            "so automatic geom1_*_dom/bnd selections exist before segment C. Do not create a new fin/FormAssembly "
            "feature. Do not recreate comp1/geom1 or create physics/mesh/study/result."
        ),
        depends_on=("A_base_geometry",),
        required_creates=(
            "cage_pocket_1", "cage_pocket_12", "cage", "roller_1", "roller_12",
            "roller_split_tool_1", "roller_split_tool_12", "roller_partition_1", "roller_partition_12",
        ),
        allowed_prefixes=("cage_pocket_", "cage", "roller_", "roller_split_tool_", "roller_partition_"),
        forbidden_snippets=(
            "model.parameter(",
            "model = mph.Model",
            "component().create('comp1'",
            'component().create("comp1"',
            "model.component.create",
            "geom().create('geom1'",
            'geom().create("geom1"',
            "study()",
            "result()",
            "physics()",
            "mesh()",
            "pair().create",
            "model.param().evaluate(",
            "model.param().get(",
            ".set('name'",
            '.set("name"',
            ".set('resulting'",
            '.set("resulting"',
        ),
    ),
    Segmented3DCodeSpec(
        segment_id="C_selections_contacts_physics",
        title="named selections, materials, Solid Mechanics, load, stabilization, and two global Contact Pairs",
        goal=(
            "Continue from segments A and B. Create named Box/Intersection selections, materials, "
            "SolidMechanics, fixed support, inner-bore BoundaryLoad audit plus displacement-controlled preload, exactly two global roller/raceway Contact Pair features, "
            "two Contact physics features, per-roller Maximum and Integration coupling operators, "
            "and a cage Maximum coupling operator using component cpl() API. "
            "Do not create mesh/study/result."
        ),
        depends_on=("A_base_geometry", "B_cage_pockets_and_rollers"),
        required_creates=(
            "sel_inner_raceway_contact",
            "sel_outer_raceway_contact",
            "sel_outer_support_surface",
            "sel_inner_bore_load_surface",
            "sel_cage_body",
            "sel_cage_boundary",
            "sel_roller_1_body",
            "sel_roller_12_body",
            "sel_roller_1_boundary",
            "sel_roller_12_boundary",
            "sel_roller_1_inner_contact",
            "sel_roller_12_inner_contact",
            "sel_roller_1_outer_contact",
            "sel_roller_12_outer_contact",
            "sel_all_roller_inner_contacts",
            "sel_all_roller_outer_contacts",
            "sel_all_roller_boundaries",
            "cp_all_rollers_inner",
            "cp_all_rollers_outer",
            "contact_all_rollers_inner",
            "contact_all_rollers_outer",
            "fix_outer",
            "load_inner_bore",
            "preload_inner_radial",
            "spring_inner_ring_guidance",
            "maxop_roller_1",
            "maxop_roller_12",
            "intop_roller_1",
            "intop_roller_12",
            "maxop_cage",
            "fix_cage_stabilization",
        ),
        allowed_prefixes=("sel_", "box_", "cp_", "contact_", "solid", "mat_", "maxop_", "intop_", "load_", "fix_", "spring_"),
        forbidden_snippets=(
            "model.parameter(",
            "model = mph.Model",
            "component().create('comp1'",
            'component().create("comp1"',
            "model.component.create",
            "geom().create('geom1'",
            'geom().create("geom1"',
            "geom('geom1').run",
            "study()",
            "result()",
            "mesh()",
            ".set('include'",
            '.set("include"',
            ".set('rmin'",
            '.set("rmin"',
            ".set('rmax'",
            '.set("rmax"',
            "model.param().evaluate(",
            "model.param().get(",
            "geom.create(",
            "geom.feature(",
            "'Explicit'",
            '"Explicit"',
            ".selection('input').set(",
            '.selection("input").set(',
        ),
    ),
    Segmented3DCodeSpec(
        segment_id="D_mesh_study_results",
        title="assembly finalization, mesh, stationary study, 3D result, and probes",
        goal=(
            "Continue from segments A-C. Geometry is already finalized and run as an assembly. Create mesh, stationary study, "
            "PlotGroup3D solid.mises, global max/contact pressure numerical outputs, and "
            "probe_roller_1_max_mises..probe_roller_12_max_mises. Do not create or replace the fin feature."
        ),
        depends_on=("A_base_geometry", "B_cage_pockets_and_rollers", "C_selections_contacts_physics"),
        required_creates=(
            "mesh1",
            "std1",
            "pg_stress3d",
            "max_von_mises",
            "probe_cage_max_mises",
            "probe_cage_max_displacement",
            "probe_roller_1_max_mises",
            "probe_roller_12_max_mises",
            "probe_scope_verified",
        ),
        allowed_prefixes=("mesh", "std", "pg_", "surf_", "max_", "probe_", "fin"),
        forbidden_snippets=(
            "model.parameter(",
            "model = mph.Model",
            "component().create('comp1'",
            'component().create("comp1"',
            "model.component.create",
            "geom().create('geom1'",
            'geom().create("geom1"',
            "physics()",
            "pair().create",
            "geom.node(",
            "FormAssembly",
            "feature().create('fin'",
            'feature().create("fin"',
        ),
    ),
)


def build_segmented_3d_generation_prompt(
    spec: Segmented3DCodeSpec,
    *,
    completed_manifests: list[dict[str, Any]],
    previous_code_tail: str,
) -> str:
    """Build the interface-driven prompt for one 3D code segment."""
    manifest_context = json.dumps(completed_manifests, ensure_ascii=False, indent=2)
    required_creates = ", ".join(spec.required_creates)
    allowed_prefixes = ", ".join(spec.allowed_prefixes)
    forbidden = "\n".join(f"- {item}" for item in spec.forbidden_snippets)
    depends_on = ", ".join(spec.depends_on) or "none"
    segment_extra_contract = ""
    if spec.segment_id == "B_cage_pockets_and_rollers":
        segment_extra_contract = (
            "\nSEGMENT_EXTRA_CONTRACT:\n"
            "- Do not import comsol, mph, or any COMSOL Python module. The existing model object is the only API entry point.\n"
            "- Do not introduce roller_diameter_mm, roller_length_mm, roller_diameter_str, roller_length_str, "
            "cage_pocket_clearance_mm, cage_pocket_clearance_str, roller_radius, or pocket_radius. The parameters "
            "already exist in COMSOL from segment A.\n"
            "- For every pocket Cylinder use the exact literal call .set('r', 'roller_diameter/2+cage_pocket_clearance') "
            "and .set('h', 'roller_length'). For every roller Cylinder use the exact literal call "
            ".set('r', 'roller_diameter/2') and .set('h', 'roller_length'). Do not build these expressions with "
            "Python f-strings or helper variables.\n"
            "- Use pitch_radius_mm=31.0 only for computing the twelve x/y center coordinates in Python. Use "
            "z position '-roller_length/2'.\n"
            "- In the loop create exact tags cage_pocket_{i+1} and roller_{i+1}; set selresult=True and "
            "selresultshow='all' on every roller inside the loop.\n"
            "- Also split every roller radially into inner-facing and outer-facing boundary entities before finalization. "
            "For roller n create Block tool roller_split_tool_n covering only its outward half (one block face passes "
            "through the roller axis, other block faces stay outside the cylinder), then create Partition feature "
            "roller_partition_n with selection('input').set([roller_n]) and selection('tool').set([roller_split_tool_n]). "
            "Set keepinput='off', keeptool='off', selresult=True, selresultshow='all'. Compute the block center and z-axis "
            "rotation from the same roller angle. The partition must leave two bonded subdomains in one partition output "
            "and two distinct cylindrical half-boundary entities; do not create overlapping duplicate roller solids.\n"
            "- Use exact split-tool dimensions ['6[mm]','12[mm]','18[mm]'], base='center', scalar rot equal to the "
            "roller angle in degrees, and position [cx+3*cos(angle), cy+3*sin(angle), 0] mm. Do not pass rot as a "
            "three-element list. This makes the local-x minus face pass through the roller axis and encloses only the "
            "outward half.\n"
            "- Create cage exactly as Difference tag 'cage' after the loop, subtract all pocket tags from "
            "cage_annulus, and set selresult=True and selresultshow='all'. Configure existing fin action='assembly', "
            "createpairs=True, pairtype='contact', then call geom.run().\n"
        )
    elif spec.segment_id == "C_selections_contacts_physics":
        segment_extra_contract = (
            "\nSEGMENT_EXTRA_CONTRACT:\n"
            "- Create global named selections exactly: sel_inner_raceway_contact, sel_outer_raceway_contact, "
            "sel_outer_support_surface, sel_inner_bore_load_surface, sel_cage_body.\n"
            "- Never create Explicit selections and never call selection('input').set on a component selection. "
            "For a pure alias of an automatic geometry selection, create a Union and call "
            "comp.selection(tag).set('input', ['geom1_object_dom_or_bnd']). For Intersection/Union inputs always "
            "call comp.selection(tag).set('input', [...]).\n"
            "- Never set include, rmin, or rmax on a component Box selection. To bind a spatial box to one "
            "geometry object, create box_<final_tag> as a Box and create <final_tag> as an Intersection whose "
            "input is [box_<final_tag>, geom1_<object_tag>_bnd] for boundaries or "
            "[box_<final_tag>, geom1_<object_tag>_dom] for domains. The automatic geometry selections are "
            "available because segments A-B enable selresult on final objects.\n"
            "- Every selection in this segment must be created through comp.selection().create(...) or "
            "model.component('comp1').selection().create(...). Never use geom.create/geom.feature for Box, "
            "Intersection, Union, or Difference selections; those are component selections, not geometry features.\n"
            "- Immediately set entitydim='2' on every boundary Union, Box, and Intersection selection, including "
            "sel_inner_raceway_contact, sel_outer_raceway_contact, sel_outer_support_surface, box_inner_bore, "
            "sel_inner_bore_load_surface, sel_roller_<n>_boundary, sel_roller_<n>_inner_contact, "
            "sel_roller_<n>_outer_contact, sel_all_roller_inner_contacts, sel_all_roller_outer_contacts, and "
            "sel_all_roller_boundaries. Set entitydim='3' "
            "on sel_cage_body and every sel_roller_<n>_body. Also create boundary Union sel_cage_boundary with "
            "entitydim='2' as an alias of geom1_cage_bnd. Use selection.set('entitydim', '2' or '3') before set('input', ...). "
            "The value MUST be a Python string because passing integer 2/3 is ambiguous with COMSOL's boolean Java overload.\n"
            "- Build sel_inner_bore_load_surface exactly as an Intersection of an inside-condition Box bounded "
            "by x/y = +/-20.1[mm], z = +/-9.1[mm], and geom1_inner_ring_bnd. This excludes the annular end faces.\n"
            "- The automatic geom1_inner_ring_bnd and geom1_outer_ring_bnd selections contain every boundary of "
            "their Boolean ring, so NEVER alias either one directly as a raceway or support selection. Build three "
            "object-bound Box+Intersection selections at interior points of the desired continuous cylinders: "
            "sel_inner_raceway_contact at x=26.9..27.1 mm, y=-0.1..0.1 mm; sel_outer_raceway_contact at "
            "x=34.9..35.1 mm, y=-0.1..0.1 mm; and sel_outer_support_surface at x=39.9..40.1 mm, "
            "y=-0.1..0.1 mm. Use z=-8.9..8.9 mm and condition='intersects' for each Box, then intersect with "
            "geom1_inner_ring_bnd or geom1_outer_ring_bnd as appropriate. These three final selections must be "
            "distinct; the fixed support must contain only the outer-diameter cylinder and must never include the "
            "outer raceway, ring end faces, or the whole geom1_outer_ring_bnd selection. Do not reference undefined "
            "outer_radius or evaluate/get COMSOL parameters in Python.\n"
            "- Never localize a continuous cylindrical raceway boundary with Box selections: COMSOL returns the "
            "whole connected raceway entity. The roller lateral surfaces were physically split by roller_partition_n. "
            "For each roller create tight contact-point Box selections intersected with geom1_roller_partition_n_bnd: "
            "sel_roller_n_inner_contact selects only the inner-facing cylindrical half and "
            "sel_roller_n_outer_contact only the outer-facing cylindrical half. The tight box is centered at radius "
            "pitch_radius-roller_diameter/2 or pitch_radius+roller_diameter/2 along that roller angle, spans full roller "
            "length, and must not touch the axial end faces or internal partition plane. Create sel_all_roller_boundaries "
            "from geom1_roller_partition_1_bnd..geom1_roller_partition_12_bnd, plus separate Unions "
            "sel_all_roller_inner_contacts and sel_all_roller_outer_contacts. Create exactly two global searches: "
            "cp_all_rollers_inner from sel_all_roller_inner_contacts to sel_inner_raceway_contact and "
            "cp_all_rollers_outer from sel_all_roller_outer_contacts to sel_outer_raceway_contact. Never use the same "
            "full roller boundary selection as source for both pairs. Immediately call manualSelection(True) on each "
            "ContactPair before source().named(...) and destination().named(...); otherwise COMSOL can ignore the named "
            "pair selections during contact search. Do not create per-roller raceway pairs.\n"
            "- In Python use only pitch_radius_mm=31.0, roller_diameter_mm=8.0, roller_length_mm=16.0 for spatial "
            "contact-point Box coordinates. Each contact-point Box must use condition='intersects', x/y bounds only "
            "+/-0.15 mm around the exact contact point, and z bounds -7.9..+7.9 mm so it intersects the split lateral "
            "half but neither axial end face nor the internal radial partition plane. Never use 15/4/8 mm locals.\n"
            "- Apply loading on sel_inner_bore_load_surface, not as a domain BodyLoad/FperVol on the whole inner ring. "
            "Create exact Solid Mechanics feature tags fix_outer (Fixed), load_inner_bore (BoundaryLoad), "
            "preload_inner_radial (Displacement2), and spring_inner_ring_guidance (SpringFoundation2). "
            "Do not invent aliases such as preload_inner_bore or spring_inner_ring because the inherited initialization "
            "and audit stages address these exact tags. The preload feature must define U0. "
            "The Displacement2 feature is initialization-only and must be inactive in the final force-control stage.\n"
            "- Construct sel_inner_bore_load_surface from cylindrical bore faces only. Do not leave a broad Box "
            "condition='intersects' that also captures ring end faces. Use an object-bound Intersection plus an "
            "inside radial box or explicit runtime-verified bore entities; verify area against "
            "pi*inner_diameter*bearing_width before normalizing FperArea.\n"
            "- Final radial-load constraints: fixed outer support, no prescribed X displacement on the bore, "
            "weak inner guidance with 1e4[N/m^3] on the load axis and 1[N/m^3] transversely, all roller/raceway contacts active, and "
            "negligible roller regularization only.\n"
            "- Set BoundaryLoad FperArea to "
            "['radial_load/(pi*inner_diameter*bearing_width)', '0', '0']. Set preload U0 to "
            "['inner_radial_displacement', '0', '0'], explicitly set Direction=['1','0','0'], and disable it with feature(...).active(False), never by "
            "setting an 'active' property.\n"
            "- Stabilize each roller only with a SpringFoundation2 on geom1_roller_<n>_bnd using "
            "kPerArea=['1e6[N/m^3]','1e6[N/m^3]','1e6[N/m^3]']; add weak inner-ring guidance "
            "on geom1_inner_ring_bnd using ['1e4[N/m^3]','1[N/m^3]','1[N/m^3]'] for the baseline +X case. "
            "The signed-axis variant contract may rotate this vector but must keep 1e4 on the load axis. Cage contact is disabled: "
            "create no cage ContactPair and no cage Contact physics feature; fix the unloaded cage only for stabilization. "
            "The boundary Fixed feature fix_cage_stabilization MUST select sel_cage_boundary, never the domain selection sel_cage_body.\n"
            "- In a 12-iteration loop, create/use literal f-string families exactly: "
            "sel_roller_{i+1}_body and sel_roller_{i+1}_boundary as aliases of "
            "geom1_roller_partition_<n>_dom/bnd. Create maxop_roller_{i+1} on the body and intop_roller_{i+1} on the "
            "full boundary, plus intop_roller_{i+1}_inner and intop_roller_{i+1}_outer on the two contact selections "
            "for independent contact-force audits.\n"
            "- Create Solid Mechanics boundary-dimension-2 features contact_all_rollers_inner and "
            "contact_all_rollers_outer, bind each to its global pair with set('pairs', [pair_tag]), and set "
            "zeroInitGap='1' on both. The split source patches are created on zero-clearance reference cylinders, and "
            "the initialization search must zero the discretization-level initial gap before displacement preload.\n"
            "- Create mat_steel with material type 'Common', select all domains, and set properties through exactly "
            "model.component('comp1').material('mat_steel').selection().all(). Never call the material selection's "
            "set(...) with geometry object-name strings because SelectionClient.set accepts integer entity IDs only. "
            "model.component('comp1').material('mat_steel').propertyGroup('def').set(...): "
            "youngsmodulus=210[GPa], poissonsratio=0.30, and density=7850[kg/m^3]. Never call mat_steel.set(...) "
            "for these properties and never create material type 'Steel'.\n"
            "The creation line must literally be comp.material().create('mat_steel', 'Common') (or the equivalent "
            "full model.component call); create('mat_steel') without 'Common' is invalid.\n"
            "- Create maxop_cage as a component Maximum coupling operator scoped to sel_cage_body.\n"
            "- Use Solid Mechanics fixed support feature type 'Fixed', not 'FixedConstraint'.\n"
            "- Every Fixed, BoundaryLoad, Displacement2, SpringFoundation2, and Contact feature is a 3D boundary "
            "feature and must be created with entity dimension 2. Do not set solid.prop('d').\n"
            "Any emitted line containing solid.prop('d') or solid.prop(\"d\") is a fatal validation error; "
            "SolidMechanics already derives the 3D space dimension from geom1.\n"
        )
    elif spec.segment_id == "D_mesh_study_results":
        segment_extra_contract = (
            "\nSEGMENT_EXTRA_CONTRACT:\n"
            "- First create mesh1 on the existing geometry with the exact API call "
            "model.component('comp1').mesh().create('mesh1', 'geom1') or comp.mesh().create('mesh1', 'geom1'). "
            "The second argument MUST be the existing geometry tag geom1, never mesh1. Do not retrieve "
            "comp.mesh('mesh1') before this create call. Then use comp.mesh('mesh1').autoMeshSize(4) for the bulk. "
            "Then create an explicit global Size feature size_bulk with custom='on', hmax='5[mm]', hmin='0.5[mm]'. "
            "Then create "
            "four mesh Size features size_roller_inner_contacts, size_roller_outer_contacts, size_inner_raceway, and "
            "size_outer_raceway, bind them respectively to sel_all_roller_inner_contacts, "
            "sel_all_roller_outer_contacts, sel_inner_raceway_contact, and sel_outer_raceway_contact with "
            "feature.selection().geom('geom1', 2) followed by feature.selection().named(...). The explicit geometry "
            "and boundary dimension are mandatory; named(...) alone raises 'No entity dimension specified'. On "
            "every local Size set custom='on', hmax='1.5[mm]', and "
            "hmin='0.15[mm]'. After all Size features create ftet1 as type 'FreeTet', then call mesh1.run(). "
            "Creating Size features switches the mesh to user-controlled mode, so omitting FreeTet produces no valid "
            "volume mesh and is forbidden. This contact-local refinement is required for the twelve-roller traction audit; "
            "global autoMeshSize(3) is forbidden because it made the nonlinear force continuation impractically "
            "large and failed to return all parameter steps.\n"
            "- Use model.component('comp1').cpl().create(maxop_tag, 'Maximum') for Maximum operators; do not use coupling().\n"
            "- After creating std1/stat, call model.study('std1').feature('stat').set('activate', ['solid', 'on']).\n"
            "- Configure radial_load as an AUXILIARY continuation sweep directly on the Stationary feature stat; "
            "do not create a separate study Parametric Sweep feature. Set useparam='on', pname=['radial_load'], "
            "plistarr=['1e-6 1e-4 0.01 0.02 0.05 0.08 0.1 0.1001 0.1005 0.101 0.2 0.5 1 2 4 8 "
            "10.099982438539563'], punit=['N'], pcontinuationmode='manual', pcontinuation='radial_load', and "
            "preusesol='yes' on model.study('std1').feature('stat'). These exact Stationary Study Extensions "
            "properties make COMSOL reuse the preceding converged load state and allow automatic intermediate "
            "continuation steps. pname/plistarr/punit require one-element string arrays.\n"
            "- Geometry was already finalized and run as an assembly in segment B. Do not create FormAssembly, "
            "do not call geom.node(), and do not create a new fin feature; a plain geom.run() is sufficient if needed.\n"
            "- Create probe_roller_{i+1}_max_mises in a 12-iteration loop and scope it through "
            "maxop_roller_{i+1}(solid.mises).\n"
            "- Create probe_cage_max_mises and probe_cage_max_displacement scoped through maxop_cage.\n"
            "- Add model.param().set('probe_scope_verified', 'true') or equivalent model parameter evidence.\n"
            "- Setup code must not solve: do not call std1.run(), model.study(...).run(), result.run(), or numerical.run(). "
            "The downstream strict runner owns the solve and native plot export. Use EvalGlobal, not EvalPoint, "
            "for expressions containing maxop_*. Create the surface using "
            "model.result('pg_stress3d').feature().create('surf_stress', 'Surface').\n"
        )
    return (
        "Generate only one bounded COMSOL Python/MPh setup-code segment for a 12-roller 3D "
        "cylindrical-roller bearing. This is a segmented code-agent workflow: do not assume memory "
        "of prior code beyond the manifest below. The local assembler will reject duplicate tags, "
        "missing dependencies, forbidden operations, and invalid final code.\n\n"
        f"SEGMENT_ID: {spec.segment_id}\n"
        f"TITLE: {spec.title}\n"
        f"GOAL: {spec.goal}\n"
        f"DEPENDS_ON: {depends_on}\n"
        f"REQUIRED_CREATED_TAG_EVIDENCE: {required_creates}\n"
        f"ALLOWED_CREATED_TAG_PREFIXES: {allowed_prefixes}\n"
        "FORBIDDEN_SNIPPETS:\n"
        f"{forbidden}\n\n"
        f"{segment_extra_contract}\n"
        "GLOBAL CONTRACT:\n"
        "- Use an existing variable named `model`.\n"
        "- Never import mph, never create or replace `model`, and never use `model.parameter(...)`.\n"
        "- Use verified MPh style: `model.param().set(...)`, `model.component().create('comp1', True)`, "
        "and `model.component('comp1').geom().create('geom1', 3)`.\n"
        "- Use Python/MPh-compatible syntax: True/False and Python lists; no Java typed variables, "
        "new int[], new String[], or new double[].\n"
        "- Use component `comp1` and geometry `geom1` exactly.\n"
        "- Every REQUIRED_CREATED_TAG_EVIDENCE item must appear literally in the code body, even if loops are used.\n"
        "- Use Difference inputs via selection('input').set([...]) and selection('input2').set([...]).\n"
        "- Contact pairs must use component pair().create(tag, 'Contact'), manualSelection(True), "
        "source().named(...), and destination().named(...).\n"
        "- Do not include prose outside the requested markers.\n\n"
        "COMPLETED_MANIFESTS_JSON:\n"
        f"{manifest_context}\n\n"
        "PREVIOUS_CODE_TAIL_FOR_STYLE_ONLY:\n"
        f"{previous_code_tail[-2500:]}\n\n"
        "Return exactly this format:\n"
        f"{SEGMENT_MARKER_MANIFEST_START}\n"
        "{\n"
        f"  \"segment_id\": \"{spec.segment_id}\",\n"
        f"  \"depends_on\": {json.dumps(list(spec.depends_on))},\n"
        "  \"creates\": [\"tag_1\", \"tag_2\"],\n"
        "  \"uses\": [\"existing_tag_1\"],\n"
        "  \"notes\": \"short audit note\"\n"
        "}\n"
        f"{SEGMENT_MARKER_MANIFEST_END}\n"
        "GENERATED_CODE_START\n"
        "# executable setup lines for this segment only\n"
        "GENERATED_CODE_END\n"
    )


def extract_generated_code(response: str) -> str | None:
    """Extract generated COMSOL setup code from a model response."""
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


def extract_segment_manifest(response: str) -> dict[str, Any] | None:
    """Extract the JSON manifest emitted by one segmented generation call."""
    match = re.search(
        rf"{SEGMENT_MARKER_MANIFEST_START}\s*(.*?)\s*{SEGMENT_MARKER_MANIFEST_END}",
        response,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None
    try:
        manifest = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return manifest if isinstance(manifest, dict) else None


def extract_segment_generated_code(response: str) -> str | None:
    """Extract the full code body for manifest-bounded segmented generation."""
    marker_match = re.search(
        r"GENERATED_CODE_START\s*(.*?)\s*GENERATED_CODE_END",
        response,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not marker_match:
        return extract_generated_code(response)
    segment = marker_match.group(1)
    fenced = _extract_first_model_code_fence(segment)
    return (fenced or _strip_code_fence(segment)).strip()


def normalize_generated_mph_code(java_code: str) -> str:
    """Normalize common Java-ish snippets into Python/MPh executable syntax."""
    normalized = _strip_block_comments(_strip_code_fence(java_code))
    normalized = re.sub(r"(?m)^\s*import\s+(?:comtypes(?:\.client)?|Python|numpy(?:\s+as\s+\w+)?)\s*$\n?", "", normalized)
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
    normalized = re.sub(
        r"(?m)^(\s*)(\w+)\s*=\s*(\w+)\.plot\(\s*(['\"])([^'\"]+)\4\s*\)\s*$",
        r"\1\2 = model.result(\4\5\4)",
        normalized,
    )
    normalized = re.sub(
        r"(?m)^(\s*)(\w+)\.create\(\s*(['\"])([^'\"]+)\3\s*,\s*(['\"])(Surface|Volume|Slice|LineGraph|ArrowSurface)\5\s*\)",
        r"\1\2.feature().create(\3\4\3, \5\6\5)",
        normalized,
    )
    return normalized.strip()


def validate_segmented_3d_segment(
    spec: Segmented3DCodeSpec,
    manifest: dict[str, Any] | None,
    java_code: str,
    *,
    completed_manifests: list[dict[str, Any]],
    existing_tags: set[str],
    load_axis: str = "x",
    load_sign: int = 1,
    cage_pocket_clearance_mm: float = 0.2,
    roller_count: int = VERIFIED_ROLLER_COUNT,
    inner_diameter_mm: float = 40.0,
    outer_diameter_mm: float = 80.0,
    bearing_width_mm: float = 18.0,
    roller_diameter_mm: float = 8.0,
    roller_length_mm: float = 16.0,
    pitch_radius_mm: float = 31.0,
    roller_angular_offset_deg: float = 0.0,
    inner_race_outer_radius_mm: float = 27.0,
    outer_race_inner_radius_mm: float = 35.0,
    cage_inner_radius_mm: float = 27.2,
    cage_outer_radius_mm: float = 34.8,
) -> dict[str, Any]:
    """Validate one segmented generation result before local assembly."""
    errors: list[str] = []
    warnings: list[str] = []
    if manifest is None:
        errors.append(f"{spec.segment_id}: missing or invalid JSON segment manifest.")
        manifest = {}
    if manifest.get("segment_id") != spec.segment_id:
        errors.append(f"{spec.segment_id}: manifest segment_id mismatch: {manifest.get('segment_id')!r}.")
    completed_ids = {item.get("segment_id") for item in completed_manifests}
    missing_deps = [dep for dep in spec.depends_on if dep not in completed_ids]
    if missing_deps:
        errors.append(f"{spec.segment_id}: missing completed dependencies: {missing_deps}.")
    manifest_deps = manifest.get("depends_on") or []
    if sorted(manifest_deps) != sorted(spec.depends_on):
        errors.append(f"{spec.segment_id}: manifest depends_on must be {list(spec.depends_on)}, got {manifest_deps}.")
    normalized = normalize_generated_mph_code(java_code)
    if not normalized.strip():
        errors.append(f"{spec.segment_id}: generated code is empty.")
    lowered = normalized.lower()
    for forbidden in spec.forbidden_snippets:
        if forbidden.lower() in lowered:
            errors.append(f"{spec.segment_id}: segment contains forbidden snippet: {forbidden}")
    created_tags = _created_tags_from_code(normalized)
    duplicate_tags = sorted(tag for tag in created_tags if tag in existing_tags)
    if duplicate_tags:
        errors.append(f"{spec.segment_id}: duplicate created tags from previous segments: {duplicate_tags}.")
    creates = set(str(item) for item in (manifest.get("creates") or []))
    for tag in _required_creates_for_variant(spec, roller_count=roller_count):
        if tag not in creates:
            errors.append(f"{spec.segment_id}: manifest is missing required create tag: {tag}.")
        if tag not in created_tags and tag not in normalized and not _has_required_tag_loop_evidence(normalized, tag):
            errors.append(f"{spec.segment_id}: missing required tag evidence: {tag}.")
    suspicious = sorted(
        tag
        for tag in created_tags
        if tag not in spec.required_creates
        and not any(tag.startswith(prefix) for prefix in spec.allowed_prefixes)
        and tag not in {"comp1", "geom1"}
    )
    if suspicious:
        warnings.append(f"{spec.segment_id}: created tags outside preferred namespace: {suspicious}.")
    if spec.segment_id == "A_base_geometry" and lowered.count("selresultshow") < 3:
        errors.append(
            f"{spec.segment_id}: inner_ring, outer_ring, and cage_annulus must each set selresultshow='all'."
        )
    if spec.segment_id == "A_base_geometry":
        expected_parameters = {
            "inner_diameter": inner_diameter_mm,
            "inner_race_outer_radius": inner_race_outer_radius_mm,
            "pitch_radius": pitch_radius_mm,
            "outer_race_inner_radius": outer_race_inner_radius_mm,
            "outer_diameter": outer_diameter_mm,
            "bearing_width": bearing_width_mm,
            "roller_diameter": roller_diameter_mm,
            "roller_length": roller_length_mm,
            "cage_inner_radius": cage_inner_radius_mm,
            "cage_outer_radius": cage_outer_radius_mm,
            "cage_pocket_clearance": cage_pocket_clearance_mm,
            "roller_angular_offset_deg": roller_angular_offset_deg,
        }
        for name, expected in expected_parameters.items():
            actual = _model_parameter_numeric_value(normalized, name)
            if actual is None or not math.isclose(actual, float(expected), abs_tol=1.0e-12):
                errors.append(
                    f"{spec.segment_id}: model parameter {name} must be {float(expected):g}."
                )
        for tag in ("inner_ring", "outer_ring", "cage_annulus"):
            if not re.search(rf"\.create\(\s*['\"]{tag}['\"]\s*,\s*['\"]difference['\"]\s*\)", lowered):
                errors.append(f"{spec.segment_id}: Boolean output must be created with exact feature tag {tag}.")
        if not (
            _difference_slot_contains_radius(normalized, "inner_ring", "input", "inner_race_outer_radius")
            and _difference_slot_contains_radius(normalized, "inner_ring", "input2", "inner_diameter/2")
        ):
            errors.append(
                f"{spec.segment_id}: inner_ring Difference must use the larger inner race cylinder "
                "as input and subtract only the inner_diameter/2 bore as input2."
            )
        if not (
            _difference_slot_contains_radius(normalized, "outer_ring", "input", "outer_diameter/2")
            and _difference_slot_contains_radius(normalized, "outer_ring", "input2", "outer_race_inner_radius")
        ):
            errors.append(
                f"{spec.segment_id}: outer_ring Difference must use the outer_diameter/2 cylinder "
                "as input and subtract outer_race_inner_radius as input2."
            )
        if not (
            _difference_slot_contains_radius(normalized, "cage_annulus", "input", "cage_outer_radius")
            and _difference_slot_contains_radius(normalized, "cage_annulus", "input2", "cage_inner_radius")
        ):
            errors.append(
                f"{spec.segment_id}: cage_annulus Difference must use cage_outer_radius as input "
                "and subtract cage_inner_radius as input2."
            )
    if spec.segment_id == "B_cage_pockets_and_rollers":
        expected_numeric_locals = {
            "roller_diameter": float(roller_diameter_mm),
            "roller_length": float(roller_length_mm),
            "cage_pocket_clearance": float(cage_pocket_clearance_mm),
        }
        for name, expected in expected_numeric_locals.items():
            match = re.search(rf"\b{name}\s*=\s*([-+]?\d+(?:\.\d+)?)\b", lowered)
            if match and abs(float(match.group(1)) - expected) > 1.0e-12:
                errors.append(
                    f"{spec.segment_id}: local {name}={match.group(1)} contradicts required {expected:g} mm."
                )
        for expression in ("roller_diameter/2", "roller_diameter/2+cage_pocket_clearance", "roller_length"):
            if expression not in re.sub(r"\s+", "", lowered):
                errors.append(f"{spec.segment_id}: geometry must retain COMSOL parameter expression {expression}.")
        compact_segment = re.sub(r"\s+", "", lowered)
        for required_create in (
            ".create(pocket_tag,'cylinder')",
            ".create(roller_tag,'cylinder')",
            ".create('cage','difference')",
        ):
            if required_create not in compact_segment:
                errors.append(
                    f"{spec.segment_id}: geometry must create exact pocket/roller/cage feature tags; missing {required_create}."
                )
        for token in ("roller_split_tool_", "roller_partition_", "'partition'", "selection('tool').set"):
            if token not in lowered:
                errors.append(f"{spec.segment_id}: missing radial roller partition evidence: {token}.")
        if re.search(r"\.set\(\s*['\"]rot['\"]\s*,\s*\[", lowered):
            errors.append(f"{spec.segment_id}: split-tool Block rot must be a scalar angle, not an array.")
    if spec.segment_id == "C_selections_contacts_physics":
        if re.search(
            r"\.create\([^,\n]+,\s*['\"](?:contact|fixed|boundaryload|displacement2|springfoundation2)['\"]\s*,\s*1\s*\)",
            lowered,
        ):
            errors.append(f"{spec.segment_id}: 3D boundary physics feature uses entity dimension 1; use 2.")
        if ".prop('d')" in lowered or '.prop("d")' in lowered:
            errors.append(f"{spec.segment_id}: do not set the Solid Mechanics d property.")
        for required_token in ("common", "youngsmodulus", "poissonsratio", "density"):
            if required_token not in lowered:
                errors.append(f"{spec.segment_id}: missing Common steel material evidence: {required_token}.")
        if "propertygroup('def')" not in lowered and 'propertygroup("def")' not in lowered:
            errors.append(f"{spec.segment_id}: steel properties must be assigned through propertyGroup('def').")
        if not re.search(r"material\([^\n]+\)\.selection\(\)\.all\(\)", lowered) and not re.search(r"mat_steel[^\n]*selection\(\)\.all\(\)", lowered):
            errors.append(f"{spec.segment_id}: mat_steel must select all domains with selection().all().")
        if re.search(r"mat_steel[^\n]*selection\(\)\.set\(", lowered):
            errors.append(f"{spec.segment_id}: material SelectionClient.set cannot receive geometry object-name strings.")
        if "outer_radius" in lowered:
            errors.append(f"{spec.segment_id}: undefined outer_radius is forbidden; use literal audited support-box bounds.")
        for tag in ("sel_inner_raceway_contact", "sel_outer_raceway_contact", "sel_outer_support_surface"):
            if not re.search(rf"create\(\s*['\"]{tag}['\"]\s*,\s*['\"]intersection['\"]\s*\)", lowered):
                errors.append(f"{spec.segment_id}: {tag} must be an object-bound Box Intersection, not a whole-ring alias.")
        inner_bore_uses_inside = bool(
            re.search(
                r"(?:selection\(\s*['\"]box_inner_bore['\"]\s*\)|\bbox_inner_bore)"
                r"[\s\S]{0,300}?set\(\s*['\"]condition['\"]\s*,\s*['\"]inside['\"]\s*\)",
                lowered,
            )
        )
        if not inner_bore_uses_inside:
            errors.append(
                f"{spec.segment_id}: box_inner_bore must use condition='inside' so the load selection excludes ring end faces."
            )
        if re.search(
            r"sel_outer_support_surface[^\n]*\n(?:[^\n]*\n){0,4}[^\n]*set\(\s*['\"]input['\"]\s*,\s*\[\s*['\"]geom1_outer_ring_bnd['\"]\s*\]",
            lowered,
        ):
            errors.append(f"{spec.segment_id}: outer support cannot alias the complete outer-ring boundary selection.")
        for bound in (
            _format_mm_bound(inner_race_outer_radius_mm - 0.1),
            _format_mm_bound(inner_race_outer_radius_mm + 0.1),
            _format_mm_bound(outer_race_inner_radius_mm - 0.1),
            _format_mm_bound(outer_race_inner_radius_mm + 0.1),
            _format_mm_bound(outer_diameter_mm / 2.0 - 0.1),
            _format_mm_bound(outer_diameter_mm / 2.0 + 0.1),
        ):
            if bound not in lowered:
                errors.append(f"{spec.segment_id}: missing audited raceway/support cylinder locator bound {bound}.")
        if lowered.count("entitydim") < 9:
            errors.append(
                f"{spec.segment_id}: every component selection family must declare boundary/domain entitydim."
            )
        if re.search(r"set\(\s*['\"]entitydim['\"]\s*,\s*[23]\s*\)", lowered):
            errors.append(
                f"{spec.segment_id}: entitydim 2/3 must be passed as strings to avoid the Python-Java boolean/int overload ambiguity."
            )
        if not re.search(r"create\(\s*['\"]fix_cage_stabilization['\"]\s*,\s*['\"]fixed['\"]\s*,\s*2\s*\)", lowered):
            errors.append(f"{spec.segment_id}: unloaded cage must use a boundary Fixed stabilization feature.")
        if re.search(
            r"fix_cage_stabilization[^\n]*\n(?:[^\n]*\n){0,3}[^\n]*named\(\s*['\"]sel_cage_body['\"]",
            lowered,
        ):
            errors.append(f"{spec.segment_id}: cage boundary Fixed cannot select domain-level sel_cage_body.")
        if "sel_cage_boundary" not in lowered:
            errors.append(f"{spec.segment_id}: missing boundary-level sel_cage_boundary for cage stabilization.")
        for source_tag in ("sel_all_roller_inner_contacts", "sel_all_roller_outer_contacts"):
            if source_tag not in lowered:
                errors.append(f"{spec.segment_id}: missing split global contact source {source_tag}.")
        if len(re.findall(r"manualselection\(\s*true\s*\)", lowered)) < 2:
            errors.append(
                f"{spec.segment_id}: both global ContactPair features must call manualSelection(True) before named binding."
            )
        if not all(token in lowered for token in ("geom1_roller_partition_", "_inner_contact", "_outer_contact")):
            errors.append(f"{spec.segment_id}: per-roller selections must use physically partitioned inner/outer source faces.")
        if re.search(r"cp_all_rollers_(?:inner|outer)[\s\S]{0,500}source\(\)\.named\(\s*['\"]sel_all_roller_boundaries", lowered):
            errors.append(f"{spec.segment_id}: global pairs cannot both source the unsplit full roller boundary union.")
        for name, expected in (
            ("pitch_radius_mm", float(pitch_radius_mm)),
            ("roller_diameter_mm", float(roller_diameter_mm)),
            ("roller_length_mm", float(roller_length_mm)),
        ):
            match = re.search(rf"\b{name}\s*=\s*([-+]?\d+(?:\.\d+)?)\b", lowered)
            if not match or abs(float(match.group(1)) - expected) > 1.0e-12:
                errors.append(f"{spec.segment_id}: {name} must be the literal {expected:g} for spatial selection boxes.")
        if (
            abs(float(roller_angular_offset_deg)) > 1.0e-12
            and not _has_contact_selection_angular_offset(
                normalized,
                float(roller_angular_offset_deg),
            )
        ):
            errors.append(
                f"{spec.segment_id}: every per-roller contact selection must apply "
                f"the requested {float(roller_angular_offset_deg):g} degree angular offset."
            )
        for forbidden_local in ("pitch_radius =", "roller_diameter =", "roller_length ="):
            if forbidden_local in lowered:
                errors.append(f"{spec.segment_id}: ambiguous/wrong local is forbidden; use *_mm exact locals: {forbidden_local}")
        if "condition', 'intersects" not in lowered and 'condition", "intersects' not in lowered:
            errors.append(f"{spec.segment_id}: split contact-point boxes must use condition='intersects'.")
        if "1e6[n/m^3]" not in lowered:
            errors.append(f"{spec.segment_id}: roller stabilization must use the audited 1e6 N/m^3 surface stiffness.")
        if not re.search(r"set\(\s*['\"]zeroinitgap['\"]\s*,\s*['\"]1['\"]\s*\)", lowered):
            errors.append(f"{spec.segment_id}: split global contacts must enable zeroInitGap='1'.")
        if _has_pair_bound_contact_selection_edit(normalized):
            errors.append(
                f"{spec.segment_id}: pair-bound Solid Mechanics Contact features must bind only with set('pairs', ...); "
                "their selection is not editable in this COMSOL runtime."
            )
        expected_direction = ["0", "0", "0"]
        expected_direction[0 if load_axis.lower() == "x" else 1] = "1"
        direction_pattern = r"set\(\s*['\"]direction['\"]\s*,\s*\[\s*" + r"\s*,\s*".join(
            rf"['\"]{value}['\"]" for value in expected_direction
        ) + r"\s*\]"
        if not re.search(direction_pattern, lowered):
            errors.append(
                f"{spec.segment_id}: displacement preload Direction must be {expected_direction} for the {load_axis.upper()}-axis variant."
            )
        signed_displacement = "inner_radial_displacement"
        if int(load_sign) < 0:
            signed_displacement = "-" + signed_displacement
        expected_preload_vector = ["0", "0", "0"]
        expected_preload_vector[0 if load_axis.lower() == "x" else 1] = signed_displacement
        compact_expected_preload = "[" + ",".join(f"'{value}'" for value in expected_preload_vector) + "]"
        if compact_expected_preload not in re.sub(r"\s+", "", lowered).replace('"', "'"):
            errors.append(
                f"{spec.segment_id}: Displacement2 U0 must use the signed {load_axis.upper()}-axis vector {expected_preload_vector}."
            )
        expected_guidance = ["1[n/m^3]", "1[n/m^3]", "1[n/m^3]"]
        expected_guidance[0 if load_axis.lower() == "x" else 1] = "1e4[n/m^3]"
        compact_guidance = "[" + ",".join(f"'{value}'" for value in expected_guidance) + "]"
        if compact_guidance not in re.sub(r"\s+", "", lowered).replace('"', "'"):
            errors.append(
                f"{spec.segment_id}: spring_inner_ring_guidance kPerArea must be {expected_guidance}."
            )
        signed_pressure = "radial_load/(pi*inner_diameter*bearing_width)"
        if int(load_sign) < 0:
            signed_pressure = "-" + signed_pressure
        expected_load_vector = ["0", "0", "0"]
        expected_load_vector[0 if load_axis.lower() == "x" else 1] = signed_pressure
        compact_expected_vector = "[" + ",".join(f"'{value}'" for value in expected_load_vector) + "]"
        if compact_expected_vector not in re.sub(r"\s+", "", lowered).replace('"', "'"):
            errors.append(
                f"{spec.segment_id}: BoundaryLoad FperArea must use the signed {load_axis.upper()}-axis vector {expected_load_vector}."
            )
        if re.search(r"cpl\([^\n]+\)\.selection\(\)\.set\(", lowered):
            errors.append(f"{spec.segment_id}: coupling operators must bind named component selections with selection().named(...).")
    if spec.segment_id == "D_mesh_study_results":
        compact_segment = re.sub(r"\s+", "", lowered)
        if "mesh().create('mesh1','geom1')" not in compact_segment and 'mesh().create("mesh1","geom1")' not in compact_segment:
            errors.append(f"{spec.segment_id}: mesh1 must be created on existing geometry geom1.")
        if ".automeshsize(4)" not in compact_segment:
            errors.append(f"{spec.segment_id}: contact-local mesh strategy requires bulk mesh1.autoMeshSize(4).")
        if ".automeshsize(3)" in compact_segment:
            errors.append(f"{spec.segment_id}: global autoMeshSize(3) is forbidden; refine only the audited contact surfaces.")
        if not re.search(r"create\(\s*['\"]size_bulk['\"]\s*,\s*['\"]size['\"]\s*\)", lowered):
            errors.append(f"{spec.segment_id}: user-controlled mesh requires explicit global size_bulk.")
        if not re.search(r"create\(\s*['\"]ftet1['\"]\s*,\s*['\"]freetet['\"]\s*\)", lowered):
            errors.append(f"{spec.segment_id}: user-controlled local Size features require an explicit FreeTet volume mesh.")
        for size_tag, selection_tag in (
            ("size_roller_inner_contacts", "sel_all_roller_inner_contacts"),
            ("size_roller_outer_contacts", "sel_all_roller_outer_contacts"),
            ("size_inner_raceway", "sel_inner_raceway_contact"),
            ("size_outer_raceway", "sel_outer_raceway_contact"),
        ):
            if size_tag not in lowered or selection_tag not in lowered:
                errors.append(f"{spec.segment_id}: missing local mesh Size {size_tag} on {selection_tag}.")
        explicit_geom_bind_count = lowered.count("selection().geom('geom1', 2)") + lowered.count('selection().geom("geom1", 2)')
        loop_binds_all_local_sizes = bool(
            re.search(r"for\s+\w+\s*,\s*\w+\s+in\s+(?:\w+|\[|\()", lowered)
            and all(tag in lowered for tag in (
                "size_roller_inner_contacts",
                "size_roller_outer_contacts",
                "size_inner_raceway",
                "size_outer_raceway",
            ))
            and re.search(r"\w+\.selection\(\)\.geom\(\s*['\"]geom1['\"]\s*,\s*2\s*\)", lowered)
            and re.search(r"\w+\.selection\(\)\.named\(", lowered)
        )
        if explicit_geom_bind_count < 4 and not loop_binds_all_local_sizes:
            errors.append(f"{spec.segment_id}: every local boundary Size must declare selection().geom('geom1', 2) before named selection binding.")
        for mesh_bound in ("5[mm]", "0.5[mm]", "1.5[mm]", "0.15[mm]"):
            if mesh_bound not in lowered:
                errors.append(f"{spec.segment_id}: local contact mesh is missing required bound {mesh_bound}.")
        if re.search(r"(?m)^\s*(?:import\s+comsol|from\s+comsol)", lowered):
            errors.append(f"{spec.segment_id}: unsupported comsol Python import is forbidden.")
        if re.search(r"\bstd\w*\.run\s*\(", lowered) or re.search(r"model\.study\([^)]*\)\.run\s*\(", lowered):
            errors.append(f"{spec.segment_id}: setup segment must not run the study.")
        if "'evalpoint'" in lowered or '"evalpoint"' in lowered:
            errors.append(f"{spec.segment_id}: maxop result probes must use EvalGlobal, not EvalPoint.")
        if re.search(r"\.set\(\s*['\"]method['\"]\s*,\s*['\"](?:max|maximum)['\"]\s*\)", lowered):
            errors.append(f"{spec.segment_id}: EvalGlobal does not support method='max' or method='maximum'.")
        for key in ("pname", "plistarr", "punit"):
            if not re.search(rf"set\(\s*['\"]{key}['\"]\s*,\s*\[", lowered):
                errors.append(f"{spec.segment_id}: auxiliary continuation {key} must use a one-element string array.")
        if re.search(r"study\(\s*['\"]std1['\"]\s*\)\.create\([^\n]+['\"]parametric['\"]", lowered):
            errors.append(f"{spec.segment_id}: use Stationary auxiliary continuation, not a separate Parametric Sweep study feature.")
        for key, value in (
            ("useparam", "on"),
            ("pcontinuationmode", "manual"),
            ("pcontinuation", "radial_load"),
            ("preusesol", "yes"),
        ):
            if not re.search(rf"set\(\s*['\"]{key}['\"]\s*,\s*['\"]{value}['\"]\s*\)", lowered):
                errors.append(f"{spec.segment_id}: Stationary auxiliary continuation must set {key}={value!r}.")
        assigned_plot_group_surface = bool(
            re.search(
                r"(?P<var>\w+)\s*=\s*model\.result\(\)\.create\(\s*['\"]pg_stress3d['\"]\s*,\s*['\"]plotgroup3d['\"]\s*\)"
                r"[\s\S]{0,500}?(?P=var)\.feature\(\)\.create\(\s*['\"]surf_stress['\"]\s*,\s*['\"]surface['\"]\s*\)",
                lowered,
            )
            or re.search(
                r"(?P<var>\w+)\s*=\s*model\.result\(\s*['\"]pg_stress3d['\"]\s*\)"
                r"[\s\S]{0,500}?(?P=var)\.feature\(\)\.create\(\s*['\"]surf_stress['\"]\s*,\s*['\"]surface['\"]\s*\)",
                lowered,
            )
        )
        if not (
            re.search(r"result\(\s*['\"]pg_stress3d['\"]\s*\)\.feature\(\)\.create", lowered)
            or assigned_plot_group_surface
            or (
                re.search(r"\bpg_stress3d\s*=\s*model\.result\(\)\.create\(", lowered)
                and "pg_stress3d.feature().create(" in re.sub(r"\s+", "", lowered)
            )
        ):
            errors.append(f"{spec.segment_id}: stress Surface must be created through PlotGroup.feature().create().")
    syntax_error = _python_syntax_error(normalized)
    if syntax_error:
        errors.append(f"{spec.segment_id}: generated code is not Python/MPh executable syntax: {syntax_error}")
    return {
        "success": not errors,
        "errors": errors,
        "warnings": warnings,
        "created_tags": sorted(created_tags),
        "manifest": manifest,
        "code": normalized,
    }


def assemble_segmented_3d_code(
    segment_results: list[dict[str, Any]],
    *,
    cage_pocket_clearance_mm: float = 0.2,
    load_axis: str = "x",
    load_sign: int = 1,
    roller_count: int = VERIFIED_ROLLER_COUNT,
    inner_diameter_mm: float = 40.0,
    outer_diameter_mm: float = 80.0,
    bearing_width_mm: float = 18.0,
    roller_diameter_mm: float = 8.0,
    roller_length_mm: float = 16.0,
    pitch_radius_mm: float = 31.0,
    roller_angular_offset_deg: float = 0.0,
    inner_race_outer_radius_mm: float = 27.0,
    outer_race_inner_radius_mm: float = 35.0,
    cage_inner_radius_mm: float = 27.2,
    cage_outer_radius_mm: float = 34.8,
) -> tuple[str, dict[str, Any]]:
    """Assemble validated segment code and run final full-bearing quality gates."""
    code = "\n\n".join(str(item.get("code") or "").strip() for item in segment_results if item.get("code"))
    quality = validate_3d_bearing_code_draft(
        code,
        require_named_selections=True,
        cage_pocket_clearance_mm=cage_pocket_clearance_mm,
        load_axis=load_axis,
        load_sign=load_sign,
        roller_count=roller_count,
        inner_diameter_mm=inner_diameter_mm,
        outer_diameter_mm=outer_diameter_mm,
        bearing_width_mm=bearing_width_mm,
        roller_diameter_mm=roller_diameter_mm,
        roller_length_mm=roller_length_mm,
        pitch_radius_mm=pitch_radius_mm,
        roller_angular_offset_deg=roller_angular_offset_deg,
        inner_race_outer_radius_mm=inner_race_outer_radius_mm,
        outer_race_inner_radius_mm=outer_race_inner_radius_mm,
        cage_inner_radius_mm=cage_inner_radius_mm,
        cage_outer_radius_mm=cage_outer_radius_mm,
    )
    manifest = {
        "segment_count": len(segment_results),
        "segments": [
            {
                "segment_id": item.get("manifest", {}).get("segment_id"),
                "created_tags": item.get("created_tags", []),
                "warnings": item.get("warnings", []),
            }
            for item in segment_results
        ],
        "final_quality": quality,
    }
    return code, manifest


def validate_3d_bearing_code_draft(
    java_code: str,
    *,
    require_named_selections: bool = False,
    cage_pocket_clearance_mm: float = 0.2,
    load_axis: str = "x",
    load_sign: int = 1,
    roller_count: int = VERIFIED_ROLLER_COUNT,
    inner_diameter_mm: float = 40.0,
    outer_diameter_mm: float = 80.0,
    bearing_width_mm: float = 18.0,
    roller_diameter_mm: float = 8.0,
    roller_length_mm: float = 16.0,
    pitch_radius_mm: float = 31.0,
    roller_angular_offset_deg: float = 0.0,
    inner_race_outer_radius_mm: float = 27.0,
    outer_race_inner_radius_mm: float = 35.0,
    cage_inner_radius_mm: float = 27.2,
    cage_outer_radius_mm: float = 34.8,
) -> dict[str, Any]:
    """Apply 3D full-bearing gates before launching COMSOL."""
    code_for_validation = _strip_hash_comments(_strip_line_comments(_strip_code_fence(textwrap.dedent(java_code))))
    compact = re.sub(r"\s+", "", code_for_validation).lower()
    lowered = code_for_validation.lower()
    errors: list[str] = []
    warnings: list[str] = []
    for pattern in ("plate", "beam", "cantilever", "2d plane-strain", "plane strain"):
        if pattern in lowered:
            errors.append(f"3D full-bearing code must not degrade to unrelated/2D model: {pattern}")
    if "geom().create('geom1',2)" in compact or 'geom().create("geom1",2)' in compact:
        errors.append("3D full-bearing code must create geom1 with dimension 3, not 2.")
    required_patterns = {
        "solidmechanics": "Solid Mechanics physics",
        "contact": "Contact Pair/Contact setup",
        "pair().create": "COMSOL pair creation",
        "inner": "inner ring/raceway naming",
        "outer": "outer ring/raceway naming",
        "roller": "roller geometry",
        "cage": "cage geometry or cage constraints",
        "pocket": "cage pocket representation",
        "cylinder": "3D cylinder geometry",
        "solid.mises": "von Mises stress output",
        "plotgroup3d": "3D stress plot group",
        "stationary": "stationary study",
        "model.param().set": "unit-aware parameters",
    }
    if "geom().create('geom1',3)" not in compact and 'geom().create("geom1",3)' not in compact:
        errors.append("Generated code is missing expected 3D geometry creation: geom().create('geom1',3)")
    roller_features = _count_3d_roller_feature_tags(compact)
    pocket_features = _count_3d_cage_pocket_feature_tags(compact)
    if _has_segmented_loop_tag_evidence(code_for_validation, "roller_"):
        roller_features = max(roller_features, roller_count)
    if _has_segmented_loop_tag_evidence(code_for_validation, "cage_pocket_"):
        pocket_features = max(pocket_features, roller_count)
    terminal_roller_tokens = (
        f"roller_{roller_count}",
        f"cyl_r{roller_count}",
        f"roller{roller_count}",
        f"rol{roller_count}",
        f"rol_{roller_count - 1}",
    )
    terminal_pocket_tokens = (
        f"pocket_{roller_count}",
        f"pocket{roller_count}",
        f"cage_pocket_{roller_count}",
        f"pkt{roller_count}",
        f"pkt_{roller_count - 1}",
    )
    if roller_features < roller_count and not any(token in compact for token in terminal_roller_tokens):
        if roller_count == VERIFIED_ROLLER_COUNT:
            errors.append("Generated code is missing expected twelfth roller geometry for full demo scale: roller_12/cyl_r12/roller12/rol12/rol_11")
        else:
            errors.append(
                f"Generated code is missing expected terminal roller geometry for {roller_count}-roller demo scale: "
                + "/".join(terminal_roller_tokens)
            )
    if pocket_features < roller_count and not any(token in compact for token in terminal_pocket_tokens):
        if roller_count == VERIFIED_ROLLER_COUNT:
            errors.append("Generated code is missing expected twelfth cage pocket representation: pocket_12/pocket12/cage_pocket_12/pkt12/pkt_11")
        else:
            errors.append(
                f"Generated code is missing expected terminal cage pocket representation for {roller_count}-roller demo scale: "
                + "/".join(terminal_pocket_tokens)
            )
    for pattern, label in required_patterns.items():
        if pattern == "pocket" and pocket_features >= roller_count:
            continue
        if pattern not in compact:
            errors.append(f"Generated code is missing expected {label}: {pattern}")
    if roller_features < roller_count:
        errors.append(f"3D full-bearing demo must create or reference at least {roller_count} rollers.")
    if pocket_features < roller_count:
        errors.append(f"3D full-bearing demo must create or reference at least {roller_count} cage pockets/constraints.")
    cage_boolean_direct = re.search(r"feature\(['\"]cage['\"]\).*selection\(['\"]input2['\"]\).*cage_pocket_", compact)
    cage_boolean_via_list = bool(
        re.search(r"(?:pocket_list|pocket_tags|cage_pockets)=?\[?f?['\"]cage_pocket_", compact)
        and re.search(r"feature\(['\"]cage['\"]\).*selection\(['\"]input2['\"]\)\.set\((?:pocket_list|pocket_tags|cage_pockets)\)", compact)
    )
    cage_boolean_via_variable = bool(
        re.search(r"create\(['\"]cage['\"],['\"]difference['\"]\)", compact)
        and re.search(r"(?:cage\.)?selection\(['\"]input2['\"]\)\.set\((?:pocket_list|pocket_tags|cage_pockets)\)", compact)
    )
    if "cage" in compact and not (cage_boolean_direct or cage_boolean_via_list or cage_boolean_via_variable):
        errors.append("Cage must use Boolean pocket cutouts via cage Difference input2 selections, not only point/constraint markers.")
    if "cage is omitted" in lowered or "cage geometry is omitted" in lowered:
        errors.append("Cage must be included in the 3D main demo, not omitted.")
    if any(pattern in compact for pattern in ("model.sol(", "study().run", "result().run", ".solve(")) or re.search(r"\bstd\w*\.run\(", compact):
        errors.append("Generated setup code must not solve or run plot/solver nodes; downstream tools own solving.")
    for pattern in ("new int", "new string", "string ", "model.output()", "getinfo", "getboundaries", "getndobjects"):
        if pattern in lowered:
            errors.append(f"Generated code uses unsupported execution-wrapper syntax: {pattern}")
    errors.extend(_detect_3d_runtime_api_risks(code_for_validation))
    broad_selection_hits = [pattern for pattern in (".source().all()", ".destination().all()") if pattern in compact]
    if broad_selection_hits:
        message = (
            "Contact/load/support selections use broad all-boundary placeholders; "
            "promote to named roller/raceway/load/support selections before production use."
        )
        if require_named_selections:
            errors.append(message)
        else:
            warnings.append(message)
    legacy_inner_domain_load_hits = [
        token
        for token in ("bodyload", "fpervol", "sel_inner_load_region")
        if token in compact
    ]
    if legacy_inner_domain_load_hits:
        errors.append(
            "3D bearing radial load must be applied as an inner-bore BoundaryLoad/FperArea "
            "on sel_inner_bore_load_surface, not as a domain BodyLoad/FperVol on sel_inner_load_region: "
            + ", ".join(legacy_inner_domain_load_hits)
        )
    if "box_inner_bore" in lowered and re.search(
        r"(?:selection\(\s*['\"]box_inner_bore(?:_load_surface)?['\"]\s*\)|\bbox_inner_bore(?:_load_surface)?)"
        r"[\s\S]{0,300}?set\(\s*['\"]condition['\"]\s*,\s*['\"]intersects['\"]\s*\)",
        lowered,
    ):
        errors.append(
            "Inner-bore Box selection must use condition='inside'; intersects includes ring end faces and corrupts load area."
        )
    for token, label in (
        ("boundaryload", "inner-bore BoundaryLoad feature"),
        ("fperarea", "FperArea boundary traction vector"),
        ("sel_inner_bore_load_surface", "named inner-bore load boundary selection"),
        ("displacement2", "inner-bore displacement preload feature"),
        ("inner_radial_displacement", "inner-bore radial displacement preload parameter"),
    ):
        if token not in compact:
            errors.append(f"Generated 3D bearing code is missing expected {label}: {token}")
    if require_named_selections:
        expected_parameters = {
            "inner_diameter": inner_diameter_mm,
            "inner_race_outer_radius": inner_race_outer_radius_mm,
            "pitch_radius": pitch_radius_mm,
            "outer_race_inner_radius": outer_race_inner_radius_mm,
            "outer_diameter": outer_diameter_mm,
            "bearing_width": bearing_width_mm,
            "roller_diameter": roller_diameter_mm,
            "roller_length": roller_length_mm,
            "cage_inner_radius": cage_inner_radius_mm,
            "cage_outer_radius": cage_outer_radius_mm,
            "cage_pocket_clearance": cage_pocket_clearance_mm,
            "roller_angular_offset_deg": roller_angular_offset_deg,
        }
        for name, expected in expected_parameters.items():
            actual = _model_parameter_numeric_value(code_for_validation, name)
            if actual is None or not math.isclose(actual, float(expected), abs_tol=1.0e-12):
                errors.append(f"Production model parameter {name} must be {float(expected):g}.")
        axis_index = 0 if load_axis.lower() == "x" else 1
        signed_pressure = "radial_load/(pi*inner_diameter*bearing_width)"
        signed_displacement = "inner_radial_displacement"
        if int(load_sign) < 0:
            signed_pressure = "-" + signed_pressure
            signed_displacement = "-" + signed_displacement
        expected_load_vector = ["0", "0", "0"]
        expected_load_vector[axis_index] = signed_pressure
        expected_preload_vector = ["0", "0", "0"]
        expected_preload_vector[axis_index] = signed_displacement
        compact_code = re.sub(r"\s+", "", lowered).replace('"', "'")
        compact_expected_load = "[" + ",".join(f"'{value}'" for value in expected_load_vector) + "]"
        compact_expected_preload = "[" + ",".join(f"'{value}'" for value in expected_preload_vector) + "]"
        if compact_expected_load not in compact_code:
            errors.append(
                f"Production BoundaryLoad FperArea must use signed {load_axis.upper()} vector {expected_load_vector}."
            )
        if compact_expected_preload not in compact_code:
            errors.append(
                f"Production displacement preload U0 must use signed {load_axis.upper()} vector {expected_preload_vector}."
            )
    if "set('activate',['solid','on'])" not in compact and 'set("activate",["solid","on"])' not in compact:
        errors.append("Generated 3D bearing code must explicitly activate Solid Mechanics in the stationary study.")
    for token, label in (
        ("maxop_cage", "cage-scoped Maximum coupling operator"),
        ("probe_cage_max_mises", "cage maximum von Mises result probe"),
        ("probe_cage_max_displacement", "cage maximum displacement result probe"),
    ):
        if token not in lowered:
            errors.append(f"Generated 3D bearing code is missing expected cage participation audit: {label} ({token})")
    if require_named_selections and not any(marker in compact for marker in ("selection().create", ".selection('", '.selection("')):
        errors.append("Production 3D bearing code must create/use named selections for contact, load, support, and cage entities.")
    if require_named_selections:
        for token, label in (
            ("cage_inner_radius", "explicit 27.2 mm cage inner radius"),
            ("cage_outer_radius", "explicit 34.8 mm cage outer radius"),
            ("roller_partition_", "12-loop radial roller surface partitions"),
            ("sel_all_roller_boundaries", "aggregate roller boundary selection"),
            ("sel_all_roller_inner_contacts", "split inner-facing roller source group"),
            ("sel_all_roller_outer_contacts", "split outer-facing roller source group"),
            ("cp_all_rollers_inner", "global inner-raceway contact pair"),
            ("cp_all_rollers_outer", "global outer-raceway contact pair"),
            ("contact_all_rollers_inner", "global inner-raceway Contact feature"),
            ("contact_all_rollers_outer", "global outer-raceway Contact feature"),
        ):
            if token not in lowered:
                errors.append(f"Production 3D bearing code is missing {label}: {token}")
        for feature_tag, feature_type in (
            ("fix_outer", "fixed"),
            ("load_inner_bore", "boundaryload"),
            ("preload_inner_radial", "displacement2"),
            ("spring_inner_ring_guidance", "springfoundation2"),
        ):
            if not re.search(
                rf"create\(\s*['\"]{feature_tag}['\"]\s*,\s*['\"]{feature_type}['\"]\s*,\s*2\s*\)",
                lowered,
            ):
                errors.append(
                    f"Production 3D bearing code must create exact feature {feature_tag} as {feature_type}."
                )
        if len(re.findall(r"manualselection\(\s*true\s*\)", lowered)) < 2:
            errors.append("Both global ContactPair features must call manualSelection(True).")
        if "pitch_radius+cage_width/2" in compact or "pitch_radius-cage_width/2" in compact:
            errors.append("Cage radii must be 27.2/34.8 mm parameters, not pitch_radius +/- cage_width/2.")
        for name, expected in (
            ("roller_diameter", float(roller_diameter_mm)),
            ("roller_length", float(roller_length_mm)),
            ("cage_pocket_clearance", float(cage_pocket_clearance_mm)),
        ):
            for match in re.finditer(rf"\b{name}\s*=\s*([-+]?\d+(?:\.\d+)?)\b", lowered):
                if abs(float(match.group(1)) - expected) > 1.0e-12:
                    errors.append(
                        f"Generated local {name}={match.group(1)} contradicts required {expected:g} mm."
                    )
        if (
            abs(float(roller_angular_offset_deg)) > 1.0e-12
            and not _has_contact_selection_angular_offset(
                code_for_validation,
                float(roller_angular_offset_deg),
            )
        ):
            errors.append(
                "Production per-roller contact selections must apply the requested "
                f"{float(roller_angular_offset_deg):g} degree angular offset."
            )
        if lowered.count("selresultshow") < 5:
            errors.append("Base rings/cage annulus, roller loop, and final cage must expose all result selections.")
        if not (
            _difference_slot_contains_radius(code_for_validation, "inner_ring", "input", "inner_race_outer_radius")
            and _difference_slot_contains_radius(code_for_validation, "inner_ring", "input2", "inner_diameter/2")
        ):
            errors.append(
                "Production inner_ring Difference must use the larger inner race cylinder as input "
                "and subtract only the inner_diameter/2 bore as input2."
            )
        if not (
            _difference_slot_contains_radius(code_for_validation, "outer_ring", "input", "outer_diameter/2")
            and _difference_slot_contains_radius(code_for_validation, "outer_ring", "input2", "outer_race_inner_radius")
        ):
            errors.append(
                "Production outer_ring Difference must use outer_diameter/2 as input "
                "and subtract outer_race_inner_radius as input2."
            )
        if not (
            _difference_slot_contains_radius(code_for_validation, "cage_annulus", "input", "cage_outer_radius")
            and _difference_slot_contains_radius(code_for_validation, "cage_annulus", "input2", "cage_inner_radius")
        ):
            errors.append(
                "Production cage_annulus Difference must use cage_outer_radius as input "
                "and subtract cage_inner_radius as input2."
            )
        if lowered.count("entitydim") < 9:
            errors.append("Production component selections must explicitly declare boundary/domain entitydim.")
        if re.search(r"set\(\s*['\"]entitydim['\"]\s*,\s*[23]\s*\)", lowered):
            errors.append("Production entitydim 2/3 values must be Python strings, not ambiguous integers.")
        if re.search(r"material\(\)\.create\(\s*['\"]mat_steel['\"]\s*,\s*['\"]steel['\"]", lowered):
            errors.append("mat_steel must be created as material type Common, not Steel.")
        for material_token in ("common", "youngsmodulus", "poissonsratio", "density"):
            if material_token not in lowered:
                errors.append(f"Production steel material is missing required Common/property evidence: {material_token}")
        if "propertygroup('def')" not in lowered and 'propertygroup("def")' not in lowered:
            errors.append("Production steel properties must be assigned through propertyGroup('def').")
        if re.search(r"\.create\([^,\n]+,\s*['\"](?:contact|fixed|boundaryload|displacement2|springfoundation2)['\"]\s*,\s*1\s*\)", lowered):
            errors.append("All 3D Solid Mechanics boundary features must use entity dimension 2, not 1.")
        if re.search(r"\.set\(\s*['\"]method['\"]\s*,\s*['\"](?:max|maximum)['\"]\s*\)", lowered):
            errors.append("EvalGlobal does not support method='max' or method='maximum'.")
        if _has_pair_bound_contact_selection_edit(code_for_validation):
            errors.append(
                "Pair-bound Solid Mechanics Contact features must bind only with set('pairs', ...); "
                "their selection is not editable in this COMSOL runtime."
            )
        if "formassembly" in lowered or "geom.node(" in lowered or re.search(r"feature\(\)\.create\(\s*['\"]fin['\"]", lowered):
            errors.append("Generated code must configure the existing fin action as assembly, not create a new FormAssembly node.")
        if "cp_roller_" in lowered or "contact_roller_" in lowered:
            errors.append("Per-roller ContactPair/Contact features are forbidden; use the two audited global contact searches.")
        if "cage_pocket" in lowered and ("pair_tag_cage" in lowered or "contact_tag_cage" in lowered or "_cage_pocket'" in lowered and "pair().create" in lowered):
            errors.append("Cage contact is disabled; generated code must not retain cage ContactPair/Contact features.")
        if not re.search(r"create\(\s*['\"]fix_cage_stabilization['\"]\s*,\s*['\"]fixed['\"]\s*,\s*2\s*\)", lowered):
            errors.append("Unloaded cage must use a boundary Fixed stabilization feature.")
        for key in ("pname", "plistarr", "punit"):
            if not re.search(rf"set\(\s*['\"]{key}['\"]\s*,\s*\[", lowered):
                errors.append(f"Production auxiliary continuation {key} must use a one-element string array.")
        if re.search(r"study\(\s*['\"]std1['\"]\s*\)\.create\([^\n]+['\"]parametric['\"]", lowered):
            errors.append("Production study must use Stationary auxiliary continuation, not a separate Parametric Sweep feature.")
        for key, value in (
            ("useparam", "on"),
            ("pcontinuationmode", "manual"),
            ("pcontinuation", "radial_load"),
            ("preusesol", "yes"),
        ):
            if not re.search(rf"set\(\s*['\"]{key}['\"]\s*,\s*['\"]{value}['\"]\s*\)", lowered):
                errors.append(f"Production Stationary auxiliary continuation must set {key}={value!r}.")
        for token in (
            "sel_inner_raceway_contact",
            "sel_outer_raceway_contact",
            "sel_outer_support_surface",
            "sel_inner_bore_load_surface",
            "sel_cage_body",
        ):
            if token not in lowered:
                errors.append(f"Production 3D bearing code is missing named selection: {token}")
        for index in range(1, roller_count + 1):
            if f"sel_roller_{index}_body" not in lowered and not _has_segmented_loop_tag_evidence(code_for_validation, "sel_roller_", "_body"):
                errors.append(f"Production 3D bearing code is missing per-roller body selection: sel_roller_{index}_body")
            if f"sel_roller_{index}_boundary" not in lowered and not _has_segmented_loop_tag_evidence(code_for_validation, "sel_roller_", "_boundary"):
                errors.append(f"Production 3D bearing code is missing per-roller boundary audit selection: sel_roller_{index}_boundary")
            if f"intop_roller_{index}" not in lowered and not _has_segmented_loop_tag_evidence(code_for_validation, "intop_roller_"):
                errors.append(f"Production 3D bearing code is missing per-roller Integration operator: intop_roller_{index}")
            if f"probe_roller_{index}_max_mises" not in lowered and not _has_segmented_loop_tag_evidence(code_for_validation, "probe_roller_", "_max_mises"):
                errors.append(f"Production 3D bearing code is missing per-roller max-stress probe: probe_roller_{index}_max_mises")
        for token in ("probe_cage_max_mises", "probe_cage_max_displacement"):
            if token not in lowered:
                errors.append(f"Production 3D bearing code is missing cage participation probe: {token}")
        if "probe_scope_verified" not in lowered:
            errors.append("Production 3D bearing code is missing verified selection-scoped per-roller probe evaluation evidence: probe_scope_verified")
    return {
        "success": not errors,
        "errors": errors,
        "warnings": warnings,
        "quality_level": "production_candidate" if require_named_selections else "smoke",
        "requires_named_selections": require_named_selections,
    }


def selection_plan(*, roller_count: int = VERIFIED_ROLLER_COUNT) -> dict[str, Any]:
    """Target named-selection contract for production-grade 3D bearing runs."""
    roller_contact_sets = []
    for index in range(1, roller_count + 1):
        angle = 360.0 * (index - 1) / roller_count
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
            *[f"probe_roller_{index}_max_mises" for index in range(1, roller_count + 1)],
        ],
        "production_gate": "validate_3d_bearing_code_draft(require_named_selections=True)",
    }


def build_3d_execution_context(
    *,
    workflow: str,
    draft_quality: dict[str, Any] | None,
    repair_history: list[dict[str, Any]] | None,
    require_free_generated_code: bool,
    allow_verified_fallback: bool,
    draft_summary: dict[str, Any] | None = None,
    selection_binding_audit: dict[str, Any] | None = None,
    physical_result_audit: dict[str, Any] | None = None,
    contact_convergence_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build structured 3D audit context for generated/template execution artifacts."""
    context: dict[str, Any] = {
        "workflow": workflow,
        "require_free_generated_code": require_free_generated_code,
        "allow_verified_fallback": allow_verified_fallback,
        "draft_quality": draft_quality or {},
        "repair_history": repair_history or [],
    }
    if draft_summary is not None:
        context["draft_summary"] = {
            "name": draft_summary.get("name"),
            "success": draft_summary.get("success"),
            "missing_calls": draft_summary.get("missing_calls", []),
            "missing_successes": draft_summary.get("missing_successes", []),
            "response_excerpt": str(draft_summary.get("response", ""))[:400],
        }
    if selection_binding_audit is not None:
        context["selection_binding_audit"] = selection_binding_audit
    if physical_result_audit is not None:
        context["physical_result_audit"] = physical_result_audit
    if contact_convergence_report is not None:
        context["contact_convergence_report"] = contact_convergence_report
    return context


def selection_binding_contract(*, roller_count: int = VERIFIED_ROLLER_COUNT) -> dict[str, Any]:
    """Return the auditable geometry-binding contract for 3D bearing selections."""
    entries: list[dict[str, Any]] = [
        {
            "tag": "sel_inner_raceway_contact",
            "role": "inner_raceway_contact_global",
            "entitydim": 2,
            "required": True,
            "expected_min_entities": 1,
            "binding_method": "named Box/Intersection boundary selection",
        },
        {
            "tag": "sel_outer_raceway_contact",
            "role": "outer_raceway_contact_global",
            "entitydim": 2,
            "required": True,
            "expected_min_entities": 1,
            "binding_method": "named Box/Intersection boundary selection",
        },
        {
            "tag": "sel_outer_support_surface",
            "role": "outer_ring_support_surface",
            "entitydim": 2,
            "required": True,
            "expected_min_entities": 1,
            "binding_method": "named support boundary selection",
        },
        {
            "tag": "sel_inner_bore_load_surface",
            "role": "inner_bore_radial_load_surface",
            "entitydim": 2,
            "required": True,
            "expected_min_entities": 1,
            "binding_method": "named inner-bore boundary load selection",
        },
        {
            "tag": "sel_cage_body",
            "role": "cage_body",
            "entitydim": 3,
            "required": True,
            "expected_min_entities": 1,
            "binding_method": "named cage domain selection",
        },
    ]
    for index in range(1, roller_count + 1):
        entries.extend([
            {
                "tag": f"sel_roller_{index}_body",
                "role": "roller_body",
                "roller": f"roller_{index}",
                "entitydim": 3,
                "required": True,
                "expected_min_entities": 1,
                "binding_method": "per-roller domain selection",
            },
            {
                "tag": f"sel_roller_{index}_inner_contact",
                "role": "roller_inner_contact_surface",
                "roller": f"roller_{index}",
                "entitydim": 2,
                "required": True,
                "expected_min_entities": 1,
                "binding_method": "Intersection of roller boundary selection and local contact patch",
            },
            {
                "tag": f"sel_roller_{index}_outer_contact",
                "role": "roller_outer_contact_surface",
                "roller": f"roller_{index}",
                "entitydim": 2,
                "required": True,
                "expected_min_entities": 1,
                "binding_method": "Intersection of roller boundary selection and local contact patch",
            },
            {
                "tag": f"sel_roller_{index}_cage_contact",
                "role": "roller_cage_pocket_contact_surface",
                "roller": f"roller_{index}",
                "entitydim": 2,
                "required": True,
                "expected_min_entities": 1,
                "binding_method": "Intersection of roller boundary selection and cage-pocket contact patch",
            },
            {
                "tag": f"sel_inner_raceway_{index}_contact",
                "role": "inner_raceway_local_contact_surface",
                "roller": f"roller_{index}",
                "entitydim": 2,
                "required": True,
                "expected_min_entities": 1,
                "binding_method": "Intersection of inner-ring boundary selection and local contact patch",
            },
            {
                "tag": f"sel_outer_raceway_{index}_contact",
                "role": "outer_raceway_local_contact_surface",
                "roller": f"roller_{index}",
                "entitydim": 2,
                "required": True,
                "expected_min_entities": 1,
                "binding_method": "Intersection of outer-ring boundary selection and local contact patch",
            },
            {
                "tag": f"sel_cage_pocket_{index}_contact",
                "role": "cage_pocket_local_contact_surface",
                "roller": f"roller_{index}",
                "entitydim": 2,
                "required": True,
                "expected_min_entities": 1,
                "binding_method": "Intersection of cage boundary selection and local cage-pocket contact patch",
            },
        ])
    return {
        "kind": "bearing_3d_selection_binding_contract",
        "roller_count": roller_count,
        "entries": entries,
        "runtime_report_schema": {
            "tag": "selection tag",
            "entitydim": "COMSOL entity dimension reported for the selection",
            "entity_count": "number of selected entities after geometry finalization",
            "entities": "optional compact entity id sample",
            "binding_source": "Box, Intersection, Explicit, object boundary selection, or runtime probe",
        },
    }


def audit_3d_selection_binding(
    *,
    java_code: str | None = None,
    selection_report: dict[str, Any] | None = None,
    roller_count: int = VERIFIED_ROLLER_COUNT,
) -> dict[str, Any]:
    """Audit 3D bearing selections from code evidence and/or runtime entity counts."""
    contract = selection_binding_contract(roller_count=roller_count)
    report_by_tag = _normalize_selection_report(selection_report)
    code_lower = (java_code or "").lower()
    compact = re.sub(r"\s+", "", code_lower)
    errors: list[str] = []
    warnings: list[str] = []
    items: list[dict[str, Any]] = []
    for entry in contract["entries"]:
        tag = entry["tag"]
        evidence = report_by_tag.get(tag, {})
        present_in_code = tag.lower() in code_lower if java_code is not None else None
        entity_count = _selection_entity_count(evidence)
        item = {
            **entry,
            "present_in_code": present_in_code,
            "runtime_entity_count": entity_count,
            "runtime_evidence": evidence,
            "status": "unchecked",
        }
        if java_code is not None and not present_in_code:
            errors.append(f"Missing required selection tag in generated code: {tag}")
            item["status"] = "missing_in_code"
        if evidence:
            reported_dim = evidence.get("entitydim")
            if reported_dim is not None and int(reported_dim) != int(entry["entitydim"]):
                errors.append(
                    f"Selection {tag} has entitydim {reported_dim}, expected {entry['entitydim']}."
                )
                item["status"] = "wrong_entitydim"
            if entity_count is None:
                warnings.append(f"Selection {tag} runtime report did not include entity_count/entities.")
            elif entity_count < int(entry["expected_min_entities"]):
                errors.append(
                    f"Selection {tag} selected {entity_count} entities, expected at least {entry['expected_min_entities']}."
                )
                item["status"] = "empty_runtime_selection"
            elif item["status"] == "unchecked":
                item["status"] = "runtime_bound"
        elif selection_report is not None:
            errors.append(f"Runtime selection report is missing required selection: {tag}")
            item["status"] = "missing_runtime_report"
        elif item["status"] == "unchecked" and present_in_code:
            item["status"] = "code_declared_runtime_unverified"
        items.append(item)
    broad_contact_patterns = (".source().all()", ".destination().all()")
    broad_hits = [pattern for pattern in broad_contact_patterns if pattern in compact]
    if broad_hits:
        errors.append(
            "Generated code still contains broad contact all-entity selection placeholders: "
            + ", ".join(broad_hits)
        )
    if ".selection().all()" in compact:
        warnings.append(
            "Generated code contains generic selection().all(); this is acceptable for materials, "
            "but load/contact/support selections should stay named and auditable."
        )
    contact_source_overlap_audit = _audit_roller_contact_source_overlaps(
        report_by_tag,
        roller_count=roller_count,
    )
    errors.extend(contact_source_overlap_audit["errors"])
    warnings.extend(contact_source_overlap_audit["warnings"])
    runtime_checked = selection_report is not None
    declared_count = sum(1 for item in items if item["present_in_code"] is True)
    bound_count = sum(1 for item in items if item["status"] == "runtime_bound")
    return {
        "success": not errors,
        "kind": "bearing_3d_selection_binding_audit",
        "roller_count": roller_count,
        "runtime_checked": runtime_checked,
        "required_selection_count": len(items),
        "code_declared_count": declared_count,
        "runtime_bound_count": bound_count,
        "errors": errors,
        "warnings": warnings,
        "contact_source_overlap_audit": contact_source_overlap_audit,
        "items": items,
        "contract": contract,
    }


def build_selection_binding_probe_code(
    *,
    roller_count: int = VERIFIED_ROLLER_COUNT,
    component_tag: str = "comp1",
) -> str:
    """Build Python/MPh probe code that reports COMSOL selection entity counts."""
    entries = [
        {
            "tag": entry["tag"],
            "role": entry["role"],
            "entitydim": entry["entitydim"],
        }
        for entry in selection_binding_contract(roller_count=roller_count)["entries"]
    ]
    lines = [
        f"selection_probe_entries = {entries!r}",
        f"output.write('{SELECTION_BINDING_PROBE_START}\\n')",
        "for selection_probe_entry in selection_probe_entries:",
        "    selection_probe_tag = selection_probe_entry['tag']",
        "    selection_probe_error = ''",
        "    selection_probe_entities = []",
        "    try:",
        f"        selection_probe_selection = model.component({component_tag!r}).selection(selection_probe_tag)",
        "        try:",
        "            selection_probe_entities = list(selection_probe_selection.entities())",
        "        except Exception as selection_probe_entities_error:",
        "            selection_probe_error = str(selection_probe_entities_error)",
        "    except Exception as selection_probe_lookup_error:",
        "        selection_probe_error = str(selection_probe_lookup_error)",
        "    selection_probe_count = len(selection_probe_entities) if not selection_probe_error else -1",
    "    selection_probe_entity_sample = ','.join(str(item) for item in selection_probe_entities)",
        "    output.write(",
        "        'SEL|'",
        "        + selection_probe_tag",
        "        + '|'",
        "        + str(selection_probe_entry['entitydim'])",
        "        + '|'",
        "        + str(selection_probe_count)",
        "        + '|'",
        "        + selection_probe_entity_sample",
        "        + '|'",
        "        + selection_probe_error.replace('\\n', ' ')",
        "        + '\\n'",
        "    )",
        f"output.write('{SELECTION_BINDING_PROBE_END}\\n')",
    ]
    return "\n".join(lines)


def parse_selection_binding_probe_output(output: str) -> dict[str, Any]:
    """Parse selection entity-count output emitted by build_selection_binding_probe_code."""
    report: dict[str, Any] = {"selections": []}
    in_block = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line == SELECTION_BINDING_PROBE_START:
            in_block = True
            continue
        if line == SELECTION_BINDING_PROBE_END:
            break
        if not in_block or not line.startswith("SEL|"):
            continue
        parts = line.split("|", 5)
        if len(parts) != 6:
            continue
        _, tag, entitydim, entity_count, entity_sample, error = parts
        parsed_count = int(entity_count)
        entities = [int(item) for item in entity_sample.split(",") if item.strip().isdigit()]
        item: dict[str, Any] = {
            "tag": tag,
            "entitydim": int(entitydim),
            "entity_count": max(parsed_count, 0),
            "entities": entities,
            "binding_source": "runtime_selection_entities_probe",
        }
        if parsed_count < 0 or error:
            item["success"] = False
            item["error"] = error or "selection probe failed"
        else:
            item["success"] = True
        report["selections"].append(item)
    report["success"] = bool(report["selections"]) and all(item.get("success") for item in report["selections"])
    report["count"] = len(report["selections"])
    return report


def audit_3d_physical_results(
    *,
    evaluations: list[dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
    min_von_mises_pa: float = 1.0,
    min_displacement_m: float = 1e-12,
    min_contact_pressure_pa: float = 1.0,
    require_displacement: bool = False,
    require_contact_pressure: bool = False,
) -> dict[str, Any]:
    """Audit solved 3D bearing outputs for nonzero, physically useful response evidence."""
    evaluations = evaluations or []
    metrics = dict(metrics or {})
    expression_values = {
        str(item.get("expression") or ""): _evaluation_representative_value(item)
        for item in evaluations
        if item.get("success", True)
    }
    von_mises = _first_numeric(
        metrics.get("von_mises_max"),
        metrics.get("max_von_mises_pa"),
        expression_values.get("solid.mises"),
        expression_values.get("maxop1(solid.mises)"),
    )
    displacement = _first_numeric(
        metrics.get("displacement_max"),
        metrics.get("max_displacement_m"),
        expression_values.get("solid.disp"),
        expression_values.get("sqrt(u^2+v^2+w^2)"),
        expression_values.get("maxop1(solid.disp)"),
    )
    contact_pressure = _first_numeric(
        metrics.get("contact_pressure_guess"),
        metrics.get("contact_pressure_estimate_pa"),
        metrics.get("max_contact_pressure"),
        expression_values.get("contact_pressure_guess"),
        expression_values.get("contact_pressure_est"),
        expression_values.get("max_contact_pressure"),
    )
    errors: list[str] = []
    warnings: list[str] = []
    checks = {
        "von_mises_nonzero": {
            "value": von_mises,
            "threshold": min_von_mises_pa,
            "required": True,
            "unit": "Pa",
        },
        "displacement_nonzero": {
            "value": displacement,
            "threshold": min_displacement_m,
            "required": require_displacement,
            "unit": "m",
        },
        "contact_pressure_nonzero": {
            "value": contact_pressure,
            "threshold": min_contact_pressure_pa,
            "required": require_contact_pressure,
            "unit": "Pa",
        },
    }
    missing_checks: list[str] = []
    near_zero_checks: list[str] = []
    passed_checks: list[str] = []
    for name, check in checks.items():
        value = check["value"]
        threshold = float(check["threshold"])
        if value is None:
            missing_checks.append(name)
            message = f"Physical result check {name} is missing."
            if check["required"]:
                errors.append(message)
            else:
                warnings.append(message)
            continue
        if abs(float(value)) < threshold:
            near_zero_checks.append(name)
            message = f"Physical result check {name} is near zero: {value} < {threshold} {check['unit']}."
            if check["required"]:
                errors.append(message)
            else:
                warnings.append(message)
        else:
            passed_checks.append(name)
    production_required = {
        "von_mises_nonzero",
        "displacement_nonzero",
        "contact_pressure_nonzero",
    }
    production_ready = (
        not errors
        and not (production_required - set(passed_checks))
    )
    quality_level = (
        "production_physics_gate"
        if production_ready
        else "failed_physics_gate"
        if errors
        else "nonzero_stress_smoke_gate"
    )
    return {
        "success": not errors,
        "kind": "bearing_3d_physical_result_audit",
        "quality_level": quality_level,
        "production_ready": production_ready,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "passed_checks": passed_checks,
        "missing_checks": missing_checks,
        "near_zero_checks": near_zero_checks,
        "metrics": metrics,
        "evaluated_expressions": sorted(expression_values),
    }


def build_contact_convergence_report(
    *,
    solve_result: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    selection_binding_audit: dict[str, Any] | None = None,
    physical_result_audit: dict[str, Any] | None = None,
    contact_pair_count: int | None = None,
    expected_contact_pair_count: int = VERIFIED_ROLLER_COUNT * 3,
) -> dict[str, Any]:
    """Build an auditable contact-convergence report for 3D bearing runs."""
    solve_result = solve_result or {}
    metrics = dict(metrics or {})
    contact_pressure = _first_numeric(
        metrics.get("contact_pressure_guess"),
        metrics.get("contact_pressure_estimate_pa"),
        metrics.get("max_contact_pressure"),
        metrics.get("contact_pressure_est"),
    )
    solve_success = solve_result.get("success")
    solve_status = str(solve_result.get("status") or solve_result.get("message") or "")
    solver_warnings = solve_result.get("warnings") or solve_result.get("solver_warnings") or []
    if isinstance(solver_warnings, str):
        solver_warnings = [solver_warnings]
    solver_log = str(solve_result.get("log") or solve_result.get("stdout") or solve_result.get("output") or "")
    warnings: list[str] = []
    errors: list[str] = []
    evidence = {
        "solve_success": solve_success,
        "solve_status": solve_status,
        "solve_elapsed_seconds": solve_result.get("elapsed_seconds"),
        "solver_warnings": solver_warnings,
        "solver_iteration_count": solve_result.get("iteration_count") or solve_result.get("solver_iterations"),
        "solver_residual": solve_result.get("residual") or solve_result.get("final_residual"),
        "contact_pressure_pa": contact_pressure,
        "contact_pair_count": contact_pair_count,
        "expected_contact_pair_count": expected_contact_pair_count,
        "selection_binding_success": (selection_binding_audit or {}).get("success"),
        "selection_binding_runtime_checked": (selection_binding_audit or {}).get("runtime_checked"),
        "physical_result_success": (physical_result_audit or {}).get("success"),
        "physical_result_quality_level": (physical_result_audit or {}).get("quality_level"),
        "physical_result_production_ready": (physical_result_audit or {}).get("production_ready"),
    }
    if solve_success is False:
        errors.append(f"COMSOL solve failed before contact convergence could be trusted: {solve_result.get('error') or solve_status}")
    elif solve_success is None:
        warnings.append("Solve result was not provided; contact convergence is not runtime-verified.")
    if solver_warnings:
        warnings.append("COMSOL solve reported warnings; contact convergence requires review.")
    if any(token in (solve_status + " " + solver_log).lower() for token in ("failed to converge", "not converged", "nonlinear solver did not converge")):
        errors.append("COMSOL solve output indicates nonlinear contact convergence failure.")
    if contact_pair_count is None:
        warnings.append("Contact pair count was not provided.")
    elif contact_pair_count < expected_contact_pair_count:
        errors.append(
            f"Only {contact_pair_count} contact pairs were reported; expected at least {expected_contact_pair_count}."
        )
    if contact_pressure is None:
        warnings.append("Contact pressure metric was not available.")
    elif abs(contact_pressure) < 1.0:
        errors.append(f"Contact pressure is near zero: {contact_pressure} Pa.")
    if selection_binding_audit is None:
        warnings.append("Selection binding audit was not provided.")
    elif not selection_binding_audit.get("success"):
        errors.append("Selection binding audit failed; contact pair entity bindings are not trustworthy.")
    elif not selection_binding_audit.get("runtime_checked"):
        warnings.append("Selection binding audit was code-declared only; runtime entity-count probe was not provided.")
    if physical_result_audit is None:
        warnings.append("Physical result audit was not provided.")
    elif not physical_result_audit.get("success"):
        errors.append("Physical result audit failed; contact convergence cannot be accepted.")
    elif not physical_result_audit.get("production_ready"):
        warnings.append("Physical result audit is not production-ready; nonzero stress, displacement, and contact pressure are not all verified.")
    runtime_verified = solve_success is True and not warnings and not errors
    quality_level = (
        "contact_runtime_convergence_checked"
        if runtime_verified
        else "contact_convergence_failed"
        if errors
        else "contact_smoke_convergence_unverified"
    )
    return {
        "success": not errors,
        "kind": "bearing_3d_contact_convergence_report",
        "quality_level": quality_level,
        "runtime_verified": runtime_verified,
        "errors": errors,
        "warnings": warnings,
        "evidence": evidence,
        "recommended_next_steps": _contact_convergence_next_steps(errors, warnings),
    }


def default_3d_artifact_qa(
    summary: dict[str, Any],
    *,
    answerer: Callable[[str, dict], str] | None = None,
) -> list[dict[str, str]]:
    """Build reusable Q&A prompts/answers for 3D bearing result packages."""
    if answerer is None:
        from comsol_agent.tools.simulation import _answer_from_artifact_summary as answerer

    questions = [
        "最大应力是多少，最大应力位置在哪里？",
        "哪个滚子附近风险最高？",
        "保持架是否建模？",
        "滚子和外圈有没有接触？",
        "载荷、材料和模型参数是什么？",
        "应力图和模型文件在哪里？",
    ]
    return [{"question": question, "answer": answerer(question, summary)} for question in questions]


def _normalize_selection_report(selection_report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not selection_report:
        return {}
    if "selections" in selection_report and isinstance(selection_report["selections"], list):
        return {
            str(item.get("tag") or item.get("name")): dict(item)
            for item in selection_report["selections"]
            if item.get("tag") or item.get("name")
        }
    return {
        str(tag): dict(value) if isinstance(value, dict) else {"entities": value}
        for tag, value in selection_report.items()
    }


def _audit_roller_contact_source_overlaps(
    report_by_tag: dict[str, dict[str, Any]],
    *,
    roller_count: int = VERIFIED_ROLLER_COUNT,
) -> dict[str, Any]:
    """Detect one roller boundary being reused by competing contact source selections."""
    errors: list[str] = []
    warnings: list[str] = []
    overlaps: list[dict[str, Any]] = []
    checked = bool(report_by_tag)
    for index in range(1, roller_count + 1):
        contact_tags = [
            f"sel_roller_{index}_inner_contact",
            f"sel_roller_{index}_outer_contact",
            f"sel_roller_{index}_cage_contact",
        ]
        entity_sets = {
            tag: _selection_entities_set(report_by_tag.get(tag, {}))
            for tag in contact_tags
        }
        if not any(entity_sets.values()):
            continue
        for left_index, left_tag in enumerate(contact_tags):
            for right_tag in contact_tags[left_index + 1:]:
                shared = sorted(entity_sets[left_tag] & entity_sets[right_tag])
                if not shared:
                    continue
                overlap = {
                    "roller": f"roller_{index}",
                    "left_selection": left_tag,
                    "right_selection": right_tag,
                    "shared_entities": shared,
                    "shared_entity_count": len(shared),
                }
                overlaps.append(overlap)
                errors.append(
                    f"Roller {index} contact source selections overlap: "
                    f"{left_tag} and {right_tag} share {len(shared)} boundary entities "
                    f"({', '.join(str(item) for item in shared[:12])})."
                )
        for tag in contact_tags:
            evidence = report_by_tag.get(tag, {})
            entities = evidence.get("entities")
            entity_count = _selection_entity_count(evidence)
            if entity_count and isinstance(entities, list) and len(entities) < entity_count:
                warnings.append(
                    f"Selection {tag} overlap audit used a partial entity sample "
                    f"({len(entities)}/{entity_count}); increase probe entity output for full coverage."
                )
    return {
        "success": not errors,
        "runtime_checked": checked,
        "checked_contact_source_sets": roller_count * 3 if checked else 0,
        "overlap_count": len(overlaps),
        "overlaps": overlaps,
        "errors": errors,
        "warnings": warnings,
    }


def _selection_entities_set(evidence: dict[str, Any]) -> set[int]:
    entities = evidence.get("entities")
    if not isinstance(entities, list | tuple | set):
        return set()
    output: set[int] = set()
    for entity in entities:
        try:
            output.add(int(entity))
        except (TypeError, ValueError):
            continue
    return output


def _selection_entity_count(evidence: dict[str, Any]) -> int | None:
    if "entity_count" in evidence:
        return int(evidence["entity_count"])
    entities = evidence.get("entities")
    if isinstance(entities, list | tuple | set):
        return len(entities)
    return None


def _evaluation_representative_value(evaluation: dict[str, Any]) -> float | None:
    stats = evaluation.get("statistics") or {}
    for candidate in (stats.get("max"), stats.get("mean"), evaluation.get("value")):
        number = _coerce_float(candidate)
        if number is not None:
            return number
    return None


def _first_numeric(*values: Any) -> float | None:
    for value in values:
        number = _coerce_float(value)
        if number is not None:
            return number
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _contact_convergence_next_steps(errors: list[str], warnings: list[str]) -> list[str]:
    steps: list[str] = []
    joined = " ".join([*errors, *warnings]).lower()
    if "solve" in joined or "runtime-verified" in joined:
        steps.append("Record the COMSOL solve result and nonlinear contact status in the run artifact.")
    if "contact pressure" in joined:
        steps.append("Evaluate contact pressure or a verified contact-pressure proxy after solve.")
    if "production-ready" in joined or "displacement" in joined:
        steps.append("Evaluate nonzero von Mises stress, displacement magnitude, and contact pressure in the same solved model.")
    if "selection binding" in joined:
        steps.append("Run selection entity-count probes for all roller/raceway contact selections.")
    if "contact pair count" in joined:
        steps.append("Report the number of created Contact Pair features and compare it with the roller-count contract.")
    if not steps:
        steps.append("Run a mesh/contact-parameter sensitivity check before design use.")
    return steps


def _created_tags_from_code(java_code: str) -> set[str]:
    tags: set[str] = set()
    for pattern in (
        r"\.create\(\s*['\"]([^'\"]+)['\"]",
        r"\.pair\(\)\.create\(\s*['\"]([^'\"]+)['\"]",
        r"\.selection\(\)\.create\(\s*['\"]([^'\"]+)['\"]",
        r"\.cpl\(\)\.create\(\s*['\"]([^'\"]+)['\"]",
    ):
        tags.update(re.findall(pattern, java_code))
    if "component().create('comp1'" in java_code or 'component().create("comp1"' in java_code:
        tags.add("comp1")
    if "geom().create('geom1'" in java_code or 'geom().create("geom1"' in java_code:
        tags.add("geom1")
    return tags


def _count_3d_roller_feature_tags(compact_code: str) -> int:
    return len(set(re.findall(r"(?:roller_|roller|cyl_r|rol_?)\d+", compact_code)))


def _count_3d_cage_pocket_feature_tags(compact_code: str) -> int:
    return len(set(re.findall(r"(?:cage_pocket_|pocket_|pocket|pkt_?|cpocket_?)\d+", compact_code)))


def _count_3d_cage_contact_pair_tags(compact_code: str) -> int:
    return len(set(re.findall(r"cp_[a-z0-9_]*cage_pocket[a-z0-9_]*", compact_code)))


def _count_3d_cage_contact_feature_tags(compact_code: str) -> int:
    return len(set(re.findall(r"contact_[a-z0-9_]*cage[a-z0-9_]*", compact_code)))


def _count_3d_roller_cage_contact_selection_tags(compact_code: str) -> int:
    return len(set(re.findall(r"sel_[a-z0-9_]*cage_contact", compact_code)))


def _count_3d_cage_pocket_contact_selection_tags(compact_code: str) -> int:
    return len(set(re.findall(r"sel_[a-z0-9_]*(?:pocket|pkt)[a-z0-9_]*contact", compact_code)))


def _has_segmented_loop_tag_evidence(java_code: str, prefix: str, suffix: str = "") -> bool:
    if not _has_indexed_iteration_loop(java_code):
        return False
    escaped_prefix = re.escape(prefix)
    escaped_suffix = re.escape(suffix)
    patterns = (
        rf"f['\"]{escaped_prefix}\{{\s*i\s*\+\s*1\s*\}}{escaped_suffix}['\"]",
        rf"f['\"]{escaped_prefix}\{{\s*index\s*\+\s*1\s*\}}{escaped_suffix}['\"]",
        rf"f['\"]{escaped_prefix}\{{\s*idx\s*\}}{escaped_suffix}['\"]",
        rf"f['\"]{escaped_prefix}\{{\s*n\s*\}}{escaped_suffix}['\"]",
        rf"f['\"]{escaped_prefix}\{{\s*roller_idx\s*\}}{escaped_suffix}['\"]",
        rf"f['\"]{escaped_prefix}\{{\s*roller_index\s*\}}{escaped_suffix}['\"]",
        rf"f['\"]{escaped_prefix}\{{\s*i\s*\}}{escaped_suffix}['\"]",
        rf"f['\"]{escaped_prefix}\{{\s*index\s*\}}{escaped_suffix}['\"]",
        rf"['\"]{escaped_prefix}['\"]\s*\+\s*str\(\s*i\s*\+\s*1\s*\)\s*\+\s*['\"]{escaped_suffix}['\"]",
        rf"['\"]{escaped_prefix}['\"]\s*\+\s*str\(\s*index\s*\+\s*1\s*\)\s*\+\s*['\"]{escaped_suffix}['\"]",
        rf"['\"]{escaped_prefix}['\"]\s*\+\s*str\(\s*idx\s*\)\s*\+\s*['\"]{escaped_suffix}['\"]",
        rf"['\"]{escaped_prefix}['\"]\s*\+\s*str\(\s*n\s*\)\s*\+\s*['\"]{escaped_suffix}['\"]",
        rf"['\"]{escaped_prefix}['\"]\s*\+\s*str\(\s*roller_idx\s*\)\s*\+\s*['\"]{escaped_suffix}['\"]",
        rf"['\"]{escaped_prefix}['\"]\s*\+\s*str\(\s*roller_index\s*\)\s*\+\s*['\"]{escaped_suffix}['\"]",
        rf"['\"]{escaped_prefix}['\"]\s*\+\s*str\(\s*i\s*\)\s*\+\s*['\"]{escaped_suffix}['\"]",
        rf"['\"]{escaped_prefix}['\"]\s*\+\s*str\(\s*index\s*\)\s*\+\s*['\"]{escaped_suffix}['\"]",
    )
    return any(re.search(pattern, java_code) for pattern in patterns)


def _has_twelve_iteration_loop(java_code: str) -> bool:
    return bool(
        re.search(r"range\(\s*(?:verified_roller_count|num_rollers|12)\s*\)", java_code, flags=re.IGNORECASE)
        or re.search(r"range\(\s*1\s*,\s*13\s*\)", java_code, flags=re.IGNORECASE)
        or re.search(r"\b(?:num_rollers|verified_roller_count)\s*=\s*12\b", java_code, flags=re.IGNORECASE)
    )


def _has_indexed_iteration_loop(java_code: str) -> bool:
    return bool(
        re.search(r"range\(\s*(?:verified_roller_count|num_rollers|roller_count|\d+)\s*\)", java_code, flags=re.IGNORECASE)
        or re.search(r"range\(\s*1\s*,\s*(?:verified_roller_count|num_rollers|roller_count|\d+)\s*\+?\s*1?\s*\)", java_code, flags=re.IGNORECASE)
        or re.search(r"\b(?:num_rollers|verified_roller_count|roller_count)\s*=\s*\d+\b", java_code, flags=re.IGNORECASE)
    )


def _loop_can_cover_index(java_code: str, index: int) -> bool:
    if index <= 0:
        return False
    lowered = java_code.lower()
    numeric_loop_bounds = [int(value) for value in re.findall(r"range\(\s*(\d+)\s*\)", lowered)]
    numeric_loop_bounds.extend(
        int(value) - 1
        for value in re.findall(r"range\(\s*1\s*,\s*(\d+)\s*\)", lowered)
    )
    numeric_loop_bounds.extend(
        int(value)
        for value in re.findall(r"range\(\s*1\s*,\s*(\d+)\s*\+\s*1\s*\)", lowered)
    )
    variable_values = {
        name: int(value)
        for name, value in re.findall(
            r"\b(num_rollers|verified_roller_count|roller_count)\s*=\s*(\d+)\b",
            lowered,
        )
    }
    for name, value in variable_values.items():
        if re.search(rf"range\(\s*{re.escape(name)}\s*\)", lowered):
            numeric_loop_bounds.append(value)
        if re.search(rf"range\(\s*1\s*,\s*{re.escape(name)}\s*\+\s*1\s*\)", lowered):
            numeric_loop_bounds.append(value)
    return any(bound >= index for bound in numeric_loop_bounds)


def _has_required_tag_loop_evidence(java_code: str, required_tag: str) -> bool:
    match = re.fullmatch(r"(.+?)(\d+)(.*)", required_tag)
    if not match:
        return False
    prefix, index_text, suffix = match.groups()
    index = int(index_text)
    if not _loop_can_cover_index(java_code, index):
        return False
    if _has_segmented_loop_tag_evidence(java_code, prefix, suffix):
        return True
    return prefix in java_code and (not suffix or suffix in java_code)


def _detect_3d_runtime_api_risks(java_code: str) -> list[str]:
    compact = re.sub(r"\s+", "", java_code).lower()
    errors: list[str] = []
    risky_patterns = {
        ".component(\"comp1\").study()": "Use top-level model.study(), not component-scoped study(), for COMSOL/MPh execution.",
        ".component('comp1').study()": "Use top-level model.study(), not component-scoped study(), for COMSOL/MPh execution.",
        ".component(\"comp1\").study(": "Use top-level model.study('std1'), not component-scoped study('std1').",
        ".component('comp1').study(": "Use top-level model.study('std1'), not component-scoped study('std1').",
        ".component(\"comp1\").result()": "Use top-level model.result(), not component-scoped result(), for result nodes.",
        ".component('comp1').result()": "Use top-level model.result(), not component-scoped result(), for result nodes.",
        ".component(\"comp1\").result(": "Use top-level model.result('tag'), not component-scoped result('tag').",
        ".component('comp1').result(": "Use top-level model.result('tag'), not component-scoped result('tag').",
        ".selection().set([\"geom1\"])": "Selections cannot target the geometry tag geom1; create named geometric selections or bounded Box selections.",
        ".selection().set(['geom1'])": "Selections cannot target the geometry tag geom1; create named geometric selections or bounded Box selections.",
        ".source().set([\"geom1\"])": "Contact pair source cannot target geom1 placeholder; use named roller/raceway boundary selections.",
        ".source().set(['geom1'])": "Contact pair source cannot target geom1 placeholder; use named roller/raceway boundary selections.",
        ".destination().set([\"geom1\"])": "Contact pair destination cannot target geom1 placeholder; use named raceway boundary selections.",
        ".destination().set(['geom1'])": "Contact pair destination cannot target geom1 placeholder; use named raceway boundary selections.",
        "\"contact_pair\"": "Contact physics feature should set verified pairs list via set('pairs', [pair_tag]).",
        "'contact_pair'": "Contact physics feature should set verified pairs list via set('pairs', [pair_tag]).",
    }
    for pattern, message in risky_patterns.items():
        if pattern in compact:
            errors.append(f"Generated code has runtime-risky COMSOL API pattern: {message}")
    regex_risks = (
        (r"\.pair\(\)\.create\(\s*['\"][^'\"]+['\"]\s*,\s*['\"]contact['\"]", "Generated code creates contact pairs with lower-case 'contact'; use COMSOL Contact pair type."),
        (r"\.pair\(\)\.create\(\s*['\"](?:pair1|pair2|pair_inner|pair_outer)['\"]", "Generated code has runtime-risky COMSOL API pattern: Contact pair tags should be explicit roller/raceway pairs, not broad pair placeholders."),
        (r"\.pair\(\s*['\"](?:pair1|pair2|pair_inner|pair_outer)['\"]", "Generated code has runtime-risky COMSOL API pattern: Contact pair tags should be explicit roller/raceway pairs, not broad pair placeholders."),
        (r"['\"]FixedConstraint['\"]", "Generated code has runtime-risky COMSOL API pattern: Solid Mechanics fixed support should use the verified Fixed feature id, not FixedConstraint."),
        (r"feature\(\)\.create\(\s*['\"][^'\"]+['\"]\s*,\s*['\"]Contact['\"]\s*,\s*1\s*\)", "Generated code creates Solid Contact physics on entity dimension 1; use boundary dimension 2 for 3D contact."),
        (r"['\"](?:CylinderSelection|BoxSelection|ExplicitSelection)['\"]", "Generated code uses unsupported geometry selection feature types CylinderSelection/BoxSelection/ExplicitSelection; use verified component Box selections."),
        (r"\.geom\(\s*['\"]geom1['\"]\s*\)\.feature\(\)\.create\(\s*['\"][^'\"]+['\"]\s*,\s*['\"]Explicit['\"]", "Generated code creates Explicit as a geometry operation; use model.component('comp1').selection().create(tag, 'Box') region selections."),
        (r"\.physics\(\)\.create\(\s*['\"][^'\"]+['\"]\s*,\s*['\"]ContactPair['\"]", "Generated code creates ContactPair as a physics interface; use component pair().create plus Solid Mechanics Contact features."),
        (r"\.physics\(\s*['\"]solid['\"]\s*\)\.create\(\s*['\"][^'\"]+['\"]\s*,\s*['\"]ContactPair['\"]", "Generated code creates ContactPair as a Solid Mechanics feature; use component pair().create plus Contact features."),
        (r"\.set\(\s*['\"]object[s]?['\"]", "Generated code uses Java-style Difference object/objects setters; use selection('input')/selection('input2').set([...])."),
        (r"\.selection\(\)\.setNamed\(", "Generated code uses setNamed selection API; use selection().named(...) or explicit verified selections."),
        (r"\.pair\(\s*['\"][^'\"]+['\"]\s*\)\.set\(\s*['\"](?:source|destination)['\"]", "Generated code sets Contact pair endpoints with set('source'/'destination'); use pair.source().named(...) and pair.destination().named(...)."),
    )
    for pattern, message in regex_risks:
        if re.search(pattern, java_code):
            errors.append(f"Generated code has runtime-risky COMSOL API pattern: {message}")
    if ".coupling()" in java_code or re.search(r"\.coupling\(\s*['\"][^'\"]+['\"]\s*\)", java_code):
        errors.append("Generated code has runtime-risky COMSOL API pattern: Component Maximum operators should use verified cpl() API, not coupling().")
    syntax_error = _python_syntax_error(java_code)
    if syntax_error:
        errors.append(f"Generated code is not Python/MPh executable syntax after normalization: {syntax_error}")
    return errors


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
        if stripped.startswith(("model.", "//", "/*", "*", "*/")):
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
