"""Reusable 3D bearing generation contracts and offline quality gates."""

from __future__ import annotations

import json
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
            "Create parameters, comp1, geom1, inner_ring, outer_ring, and cage_annulus only. "
            "Define shared downstream parameters pitch_dia, pocket_dia, radial_load, mesh_bulk_size, and mesh_contact_size. "
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
        ),
    ),
    Segmented3DCodeSpec(
        segment_id="B_cage_pockets_and_rollers",
        title="cage Boolean pocket cutters, cage Difference, and twelve rollers",
        goal=(
            "Continue from segment A. Create cage_pocket_1..cage_pocket_12, cage Difference, "
            "and roller_1..roller_12 only. Do not recreate comp1/geom1 or create physics/mesh/study/result."
        ),
        depends_on=("A_base_geometry",),
        required_creates=("cage_pocket_1", "cage_pocket_12", "cage", "roller_1", "roller_12"),
        allowed_prefixes=("cage_pocket_", "cage", "roller_"),
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
            "physics()",
            "mesh()",
            "pair().create",
        ),
    ),
    Segmented3DCodeSpec(
        segment_id="C_selections_contacts_physics",
        title="named selections, materials, Solid Mechanics, and 24 Contact Pairs",
        goal=(
            "Continue from segments A and B. Create named Box/Intersection selections, materials, "
            "SolidMechanics, radial load/support, 24 explicit roller/raceway Contact Pair features, "
            "Contact physics features, and per-roller Maximum coupling operators using component cpl() API. Do not create mesh/study/result."
        ),
        depends_on=("A_base_geometry", "B_cage_pockets_and_rollers"),
        required_creates=(
            "sel_inner_raceway_contact",
            "sel_outer_raceway_contact",
            "sel_outer_support_surface",
            "sel_inner_load_region",
            "sel_cage_body",
            "sel_roller_1_body",
            "sel_roller_12_body",
            "sel_roller_1_inner_contact",
            "sel_roller_12_outer_contact",
            "sel_inner_raceway_1_contact",
            "sel_outer_raceway_12_contact",
            "cp_roller_1_inner_raceway",
            "cp_roller_12_outer_raceway",
            "contact_roller_1_inner",
            "contact_roller_12_outer",
            "maxop_roller_1",
            "maxop_roller_12",
        ),
        allowed_prefixes=("sel_", "box_", "cp_", "contact_", "solid", "mat_", "maxop_", "load_", "fix_"),
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
        ),
    ),
    Segmented3DCodeSpec(
        segment_id="D_mesh_study_results",
        title="assembly finalization, mesh, stationary study, 3D result, and probes",
        goal=(
            "Continue from segments A-C. Finalize geometry as assembly, create mesh, stationary study, "
            "PlotGroup3D solid.mises, global max/contact pressure numerical outputs, and "
            "probe_roller_1_max_mises..probe_roller_12_max_mises. This is the only segment allowed to call geom.run()."
        ),
        depends_on=("A_base_geometry", "B_cage_pockets_and_rollers", "C_selections_contacts_physics"),
        required_creates=(
            "mesh1",
            "std1",
            "pg_stress3d",
            "max_von_mises",
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
    if spec.segment_id == "C_selections_contacts_physics":
        segment_extra_contract = (
            "\nSEGMENT_EXTRA_CONTRACT:\n"
            "- Create global named selections exactly: sel_inner_raceway_contact, sel_outer_raceway_contact, "
            "sel_outer_support_surface, sel_inner_load_region, sel_cage_body.\n"
            "- In a 12-iteration loop, create/use literal f-string families exactly: "
            "sel_roller_{i+1}_body, sel_roller_{i+1}_inner_contact, sel_roller_{i+1}_outer_contact, "
            "sel_inner_raceway_{i+1}_contact, sel_outer_raceway_{i+1}_contact.\n"
            "- Create Contact Pair tags exactly cp_roller_{i+1}_inner_raceway and "
            "cp_roller_{i+1}_outer_raceway, with source/destination named to the corresponding contact patch selections.\n"
            "- Create Solid Mechanics Contact features contact_roller_{i+1}_inner and contact_roller_{i+1}_outer, "
            "and set('pairs', [pair_tag]) on each Contact feature.\n"
            "- Use Solid Mechanics fixed support feature type 'Fixed', not 'FixedConstraint'.\n"
        )
    elif spec.segment_id == "D_mesh_study_results":
        segment_extra_contract = (
            "\nSEGMENT_EXTRA_CONTRACT:\n"
            "- Use model.component('comp1').cpl().create(maxop_tag, 'Maximum') for Maximum operators; do not use coupling().\n"
            "- Create probe_roller_{i+1}_max_mises in a 12-iteration loop and scope it through "
            "maxop_roller_{i+1}(solid.mises).\n"
            "- Add model.param().set('probe_scope_verified', 'true') or equivalent model parameter evidence.\n"
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


def validate_segmented_3d_segment(
    spec: Segmented3DCodeSpec,
    manifest: dict[str, Any] | None,
    java_code: str,
    *,
    completed_manifests: list[dict[str, Any]],
    existing_tags: set[str],
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
    for tag in spec.required_creates:
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


def assemble_segmented_3d_code(segment_results: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """Assemble validated segment code and run final full-bearing quality gates."""
    code = "\n\n".join(str(item.get("code") or "").strip() for item in segment_results if item.get("code"))
    quality = validate_3d_bearing_code_draft(code, require_named_selections=True)
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


def validate_3d_bearing_code_draft(java_code: str, *, require_named_selections: bool = False) -> dict[str, Any]:
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
        roller_features = max(roller_features, VERIFIED_ROLLER_COUNT)
    if _has_segmented_loop_tag_evidence(code_for_validation, "cage_pocket_"):
        pocket_features = max(pocket_features, VERIFIED_ROLLER_COUNT)
    if roller_features < VERIFIED_ROLLER_COUNT and not any(token in compact for token in ("roller_12", "cyl_r12", "roller12", "rol12", "rol_11")):
        errors.append("Generated code is missing expected twelfth roller geometry for full demo scale: roller_12/cyl_r12/rol12/rol_11")
    if pocket_features < VERIFIED_ROLLER_COUNT and not any(token in compact for token in ("pocket_12", "pocket12", "cage_pocket_12", "pkt12", "pkt_11")):
        errors.append("Generated code is missing expected twelfth cage pocket representation: pocket_12/pocket12/cage_pocket_12/pkt12/pkt_11")
    for pattern, label in required_patterns.items():
        if pattern == "pocket" and pocket_features >= VERIFIED_ROLLER_COUNT:
            continue
        if pattern not in compact:
            errors.append(f"Generated code is missing expected {label}: {pattern}")
    if roller_features < VERIFIED_ROLLER_COUNT:
        errors.append(f"3D full-bearing demo must create or reference at least {VERIFIED_ROLLER_COUNT} rollers.")
    if pocket_features < VERIFIED_ROLLER_COUNT:
        errors.append(f"3D full-bearing demo must create or reference at least {VERIFIED_ROLLER_COUNT} cage pockets/constraints.")
    cage_boolean_direct = re.search(r"feature\(['\"]cage['\"]\).*selection\(['\"]input2['\"]\).*cage_pocket_", compact)
    cage_boolean_via_list = bool(
        re.search(r"(?:pocket_list|pocket_tags|cage_pockets)=?\[?f?['\"]cage_pocket_", compact)
        and re.search(r"feature\(['\"]cage['\"]\).*selection\(['\"]input2['\"]\)\.set\((?:pocket_list|pocket_tags|cage_pockets)\)", compact)
    )
    if "cage" in compact and not (cage_boolean_direct or cage_boolean_via_list):
        errors.append("Cage must use Boolean pocket cutouts via cage Difference input2 selections, not only point/constraint markers.")
    if "cage is omitted" in lowered or "cage geometry is omitted" in lowered:
        errors.append("Cage must be included in the 3D main demo, not omitted.")
    if any(pattern in compact for pattern in ("model.sol(", "study().run", "result().run", ".solve(")):
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
    if require_named_selections and not any(marker in compact for marker in ("selection().create", ".selection('", '.selection("')):
        errors.append("Production 3D bearing code must create/use named selections for contact, load, support, and cage entities.")
    if require_named_selections:
        for token in (
            "sel_inner_raceway_contact",
            "sel_outer_raceway_contact",
            "sel_outer_support_surface",
            "sel_inner_load_region",
            "sel_cage_body",
        ):
            if token not in lowered:
                errors.append(f"Production 3D bearing code is missing named selection: {token}")
        for index in range(1, VERIFIED_ROLLER_COUNT + 1):
            if f"sel_roller_{index}_body" not in lowered and not _has_segmented_loop_tag_evidence(code_for_validation, "sel_roller_", "_body"):
                errors.append(f"Production 3D bearing code is missing per-roller body selection: sel_roller_{index}_body")
            if f"sel_roller_{index}_inner_contact" not in lowered and not _has_segmented_loop_tag_evidence(code_for_validation, "sel_roller_", "_inner_contact"):
                errors.append(f"Production 3D bearing code is missing per-roller inner contact selection: sel_roller_{index}_inner_contact")
            if f"sel_roller_{index}_outer_contact" not in lowered and not _has_segmented_loop_tag_evidence(code_for_validation, "sel_roller_", "_outer_contact"):
                errors.append(f"Production 3D bearing code is missing per-roller outer contact selection: sel_roller_{index}_outer_contact")
            if f"sel_inner_raceway_{index}_contact" not in lowered and not _has_segmented_loop_tag_evidence(code_for_validation, "sel_inner_raceway_", "_contact"):
                errors.append(f"Production 3D bearing code is missing per-roller inner raceway contact patch: sel_inner_raceway_{index}_contact")
            if f"sel_outer_raceway_{index}_contact" not in lowered and not _has_segmented_loop_tag_evidence(code_for_validation, "sel_outer_raceway_", "_contact"):
                errors.append(f"Production 3D bearing code is missing per-roller outer raceway contact patch: sel_outer_raceway_{index}_contact")
            if f"probe_roller_{index}_max_mises" not in lowered and not _has_segmented_loop_tag_evidence(code_for_validation, "probe_roller_", "_max_mises"):
                errors.append(f"Production 3D bearing code is missing per-roller max-stress probe: probe_roller_{index}_max_mises")
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
            "tag": "sel_inner_load_region",
            "role": "inner_ring_load_region",
            "entitydim": 3,
            "required": True,
            "expected_min_entities": 1,
            "binding_method": "named load domain selection",
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
        "    selection_probe_entity_sample = ','.join(str(item) for item in selection_probe_entities[:20])",
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
    expected_contact_pair_count: int = VERIFIED_ROLLER_COUNT * 2,
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


def _has_segmented_loop_tag_evidence(java_code: str, prefix: str, suffix: str = "") -> bool:
    if not _has_twelve_iteration_loop(java_code):
        return False
    escaped_prefix = re.escape(prefix)
    escaped_suffix = re.escape(suffix)
    patterns = (
        rf"f['\"]{escaped_prefix}\{{\s*i\s*\+\s*1\s*\}}{escaped_suffix}['\"]",
        rf"f['\"]{escaped_prefix}\{{\s*index\s*\+\s*1\s*\}}{escaped_suffix}['\"]",
        rf"f['\"]{escaped_prefix}\{{\s*i\s*\}}{escaped_suffix}['\"]",
        rf"f['\"]{escaped_prefix}\{{\s*index\s*\}}{escaped_suffix}['\"]",
        rf"['\"]{escaped_prefix}['\"]\s*\+\s*str\(\s*i\s*\+\s*1\s*\)\s*\+\s*['\"]{escaped_suffix}['\"]",
        rf"['\"]{escaped_prefix}['\"]\s*\+\s*str\(\s*index\s*\+\s*1\s*\)\s*\+\s*['\"]{escaped_suffix}['\"]",
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


def _has_required_tag_loop_evidence(java_code: str, required_tag: str) -> bool:
    match = re.fullmatch(r"(.+?)(\d+)(.*)", required_tag)
    if not match:
        return False
    prefix, index_text, suffix = match.groups()
    index = int(index_text)
    if index not in {1, VERIFIED_ROLLER_COUNT}:
        return False
    if _has_segmented_loop_tag_evidence(java_code, prefix, suffix):
        return True
    return _has_twelve_iteration_loop(java_code) and prefix in java_code and (not suffix or suffix in java_code)


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
