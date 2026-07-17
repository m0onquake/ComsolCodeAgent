"""Bearing-family registry and request planner.

This registry is narrower than the general model-family registry: it keeps
bearing topology, contact intent, and executable COMSOL parameters separate so
planner output cannot accidentally pass natural-language bearing intents into
``model.param().set(...)``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


CONTACT_POLICIES: tuple[str, ...] = (
    "frictionless",
    "frictional",
    "interference_fit",
    "radial_preload",
    "axial_preload",
    "clearance",
    "staged_contact_activation",
    "cage_pocket_contact_load_transfer",
)


@dataclass(frozen=True)
class BearingFamilySpec:
    """Planning metadata for one bearing topology."""

    name: str
    bearing_type: str
    rolling_element: str
    load_modes: tuple[str, ...]
    geometry_slots: tuple[str, ...]
    required_slots: tuple[str, ...]
    contact_policies: tuple[str, ...]
    default_assumptions: dict[str, str]
    starter_templates: tuple[str, ...]
    output_expressions: tuple[str, ...]
    quality_gate: str
    keywords: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def match_score(self, text: str) -> int:
        lowered = text.lower()
        return sum(1 for keyword in self.keywords if _keyword_matches(lowered, keyword.lower()))


BEARING_FAMILIES: tuple[BearingFamilySpec, ...] = (
    BearingFamilySpec(
        name="deep_groove_ball",
        bearing_type="deep_groove_ball_bearing",
        rolling_element="ball",
        load_modes=("radial", "combined_radial_axial_light"),
        geometry_slots=("inner_diameter", "outer_diameter", "bearing_width", "ball_count", "ball_diameter"),
        required_slots=("bearing_type", "load_mode", "contact_policy", "outputs"),
        contact_policies=CONTACT_POLICIES,
        default_assumptions={
            "topology": "Deep-groove ball bearing with one ball/raceway contact cell for smoke fidelity.",
            "smoke_fidelity": "2D contact-pair cell is allowed only as a labeled fast regression layer.",
            "material": "Bearing steel E=210[GPa], nu=0.30.",
        },
        starter_templates=("bearing_contact_pair_seed", "bearing_contact_hertz_seed"),
        output_expressions=("solid.mises", "solid.disp", "contact_pressure_guess"),
        quality_gate="validate_deep_groove_ball_contact_pair_or_declared_smoke_fidelity",
        keywords=("deep groove", "deep-groove", "ball bearing", "滚珠", "球轴承", "深沟", "深沟球轴承"),
    ),
    BearingFamilySpec(
        name="angular_contact_ball",
        bearing_type="angular_contact_ball_bearing",
        rolling_element="ball",
        load_modes=("axial", "combined_radial_axial"),
        geometry_slots=("contact_angle", "inner_diameter", "outer_diameter", "bearing_width", "ball_count", "ball_diameter"),
        required_slots=("bearing_type", "contact_angle", "load_mode", "contact_policy", "outputs"),
        contact_policies=CONTACT_POLICIES,
        default_assumptions={
            "topology": "Angular-contact ball bearing; contact angle must be explicit for production geometry.",
            "starter_status": "Planner support exists; full 3D angular-contact topology generation is generated-code only.",
        },
        starter_templates=(),
        output_expressions=("solid.mises", "solid.disp", "contact_pressure"),
        quality_gate="validate_angular_contact_ball_declared_contact_angle_and_no_deep_groove_substitution",
        keywords=("angular contact", "angular-contact", "角接触", "角接触球轴承"),
    ),
    BearingFamilySpec(
        name="cylindrical_roller",
        bearing_type="cylindrical_roller_bearing",
        rolling_element="cylindrical_roller",
        load_modes=("radial", "combined_radial_axial_limited"),
        geometry_slots=("inner_diameter", "outer_diameter", "bearing_width", "roller_count", "roller_diameter", "roller_length", "cage"),
        required_slots=("bearing_type", "roller_count", "load_mode", "contact_policy", "outputs"),
        contact_policies=CONTACT_POLICIES,
        default_assumptions={
            "topology": "3D cylindrical rollers between inner and outer raceways.",
            "staging": "Use coarse raceway-only preload, refined raceway-only preload, continuous BoundaryLoad continuation diagnostics, then optional cage-pocket contact.",
            "high_load_visual": "For high-load stress images, use the verified raceway-only high-load direct starter if the full staged boundary-load/cage path has not converged; label it as visual fidelity.",
            "boundary_load_continuation": "Try all_raceway_continuous_boundary_load, then all_raceway_split_control_boundary_load if same-surface BoundaryLoad plus prescribed displacement fails. all_raceway_high_preload_reaction_equivalent is only equivalent-load evidence when reaction_equivalent.success is true; otherwise run load_side_group_boundary_load or explicit support/constraint reaction before reattempting all-12 design BoundaryLoad.",
            "cage": "Cage stage must use roller-to-cage-pocket contact load transfer; temporary cage stabilization is not a final substitute.",
        },
        starter_templates=(
            "bearing_3d_cylindrical_roller_staged_fixture",
            "bearing_3d_cylindrical_roller_legacy_raceway_highload_direct",
        ),
        output_expressions=("solid.mises", "solid.disp", "contact_pressure_est", "maxop_cage(solid.mises)"),
        quality_gate="validate_3d_bearing_code_draft(require_named_selections=True)",
        keywords=("cylindrical roller", "roller bearing", "multiroller", "roller", "圆柱滚子", "滚子轴承", "滚道先接触", "保持架"),
    ),
    BearingFamilySpec(
        name="tapered_roller",
        bearing_type="tapered_roller_bearing",
        rolling_element="tapered_roller",
        load_modes=("axial", "radial", "combined_radial_axial"),
        geometry_slots=("cone_angle", "cup_angle", "inner_diameter", "outer_diameter", "bearing_width", "roller_count", "roller_length"),
        required_slots=("bearing_type", "cone_angle", "roller_count", "load_mode", "contact_policy", "outputs"),
        contact_policies=CONTACT_POLICIES,
        default_assumptions={
            "topology": "Tapered roller bearing with cone/cup raceways and combined axial/radial load path.",
            "starter_status": "Planner and quality gate only; do not reuse deep-groove ball templates for this topology.",
        },
        starter_templates=(),
        output_expressions=("solid.mises", "solid.disp", "contact_pressure"),
        quality_gate="validate_tapered_roller_requires_cone_cup_geometry_or_declared_unsupported_fidelity",
        keywords=("tapered roller", "taper roller", "圆锥滚子", "圆锥滚子轴承", "锥滚子"),
    ),
    BearingFamilySpec(
        name="needle_roller",
        bearing_type="needle_roller_bearing",
        rolling_element="needle_roller",
        load_modes=("radial",),
        geometry_slots=("inner_diameter", "outer_diameter", "bearing_width", "needle_count", "needle_diameter", "needle_length", "cage"),
        required_slots=("bearing_type", "needle_count", "load_mode", "contact_policy", "outputs"),
        contact_policies=CONTACT_POLICIES,
        default_assumptions={
            "topology": "Needle roller bearing represented as long slender rollers with radial contact.",
            "starter_status": "Use cylindrical-roller generated-code path only if the slender needle geometry is preserved.",
        },
        starter_templates=(),
        output_expressions=("solid.mises", "solid.disp", "contact_pressure"),
        quality_gate="validate_needle_roller_slender_geometry_and_no_ball_template_substitution",
        keywords=("needle roller", "needle bearing", "滚针", "滚针轴承"),
    ),
    BearingFamilySpec(
        name="thrust_bearing",
        bearing_type="thrust_bearing",
        rolling_element="ball_or_roller",
        load_modes=("axial",),
        geometry_slots=("shaft_washer", "housing_washer", "rolling_element_count", "rolling_element_diameter", "thrust_gap"),
        required_slots=("bearing_type", "rolling_element", "axial_load", "contact_policy", "outputs"),
        contact_policies=CONTACT_POLICIES,
        default_assumptions={
            "topology": "Thrust bearing with axial load transfer between washers through balls or rollers.",
            "starter_status": "Planner and quality gate only; ball/raceway radial deep-groove templates are not valid.",
        },
        starter_templates=(),
        output_expressions=("solid.mises", "solid.disp", "contact_pressure"),
        quality_gate="validate_thrust_bearing_axial_washer_topology_or_declared_unsupported_fidelity",
        keywords=("thrust bearing", "thrust", "推力轴承", "轴向轴承"),
    ),
    BearingFamilySpec(
        name="general_bearing",
        bearing_type="general_bearing",
        rolling_element="unspecified",
        load_modes=("radial", "axial", "combined_radial_axial"),
        geometry_slots=("bearing_type", "inner_diameter", "outer_diameter", "bearing_width", "rolling_element"),
        required_slots=("bearing_type", "rolling_element", "load_mode", "contact_policy", "outputs"),
        contact_policies=CONTACT_POLICIES,
        default_assumptions={
            "workflow": "Clarify topology before choosing a template; do not default to deep-groove unless user allows it.",
        },
        starter_templates=(),
        output_expressions=("solid.mises", "solid.disp", "contact_pressure"),
        quality_gate="validate_general_bearing_topology_clarified_before_generation",
        keywords=("bearing", "轴承"),
    ),
)


EXECUTABLE_PARAM_ALIASES: dict[str, str] = {
    "load": "radial_load",
    "radial force": "radial_load",
    "axial force": "axial_load",
    "balls": "ball_count",
    "rollers": "roller_count",
    "needles": "needle_count",
    "friction": "friction_coefficient",
    "interference": "contact_interference",
    "clearance": "contact_clearance",
    "preload": "radial_preload",
    "radial preload": "radial_preload",
    "axial preload": "axial_preload",
    "id": "inner_diameter",
    "od": "outer_diameter",
    "width": "bearing_width",
    "滚子数量": "roller_count",
    "滚珠数量": "ball_count",
    "滚珠直径": "ball_diameter",
    "滚子直径": "roller_diameter",
    "滚子长度": "roller_length",
    "径向载荷": "radial_load",
    "轴向载荷": "axial_load",
    "过盈": "contact_interference",
    "游隙": "contact_clearance",
}

INTENT_SLOT_KEYS: frozenset[str] = frozenset(
    {
        "bearing_type",
        "rolling_element",
        "contact_policy",
        "contact_model",
        "cage",
        "cage_included",
        "cage_model",
        "geometry",
        "material",
        "outputs",
        "load_mode",
        "fidelity",
        "真实接触",
        "保持架",
    }
)


def list_bearing_families() -> list[BearingFamilySpec]:
    return list(BEARING_FAMILIES)


def get_bearing_family(name: str) -> BearingFamilySpec:
    normalized = name.strip().lower()
    for spec in BEARING_FAMILIES:
        if spec.name == normalized or spec.bearing_type == normalized:
            return spec
    raise KeyError(f"Unknown bearing family: {name}")


def infer_bearing_family(user_request: str, preferred_bearing_type: str | None = None) -> BearingFamilySpec:
    text = " ".join(part for part in (user_request, preferred_bearing_type or "") if part)
    if preferred_bearing_type:
        preferred = preferred_bearing_type.strip().lower()
        for spec in BEARING_FAMILIES:
            if preferred in {spec.name, spec.bearing_type}:
                return spec
    scored = [(spec.match_score(text), spec) for spec in BEARING_FAMILIES if spec.name != "general_bearing"]
    scored.sort(key=lambda item: item[0], reverse=True)
    if scored and scored[0][0] > 0:
        return scored[0][1]
    return get_bearing_family("general_bearing")


def plan_bearing_modeling_request(
    *,
    user_request: str,
    known_params: dict[str, Any] | None = None,
    allow_defaults: bool = False,
    preferred_bearing_type: str | None = None,
    contact_policy: str | None = None,
    archive_path: str | None = None,
) -> dict[str, Any]:
    """Return a stable JSON-ready plan for a bearing modeling request."""
    spec = infer_bearing_family(user_request, preferred_bearing_type)
    request_params = _extract_params_from_text(user_request)
    executable_params = _normalize_executable_params({**request_params, **(known_params or {})})
    resolved_contact_policy = normalize_contact_policy(contact_policy, user_request, executable_params)
    load_mode = infer_load_mode(user_request, executable_params, spec)
    missing_decisions = _missing_decisions(
        spec=spec,
        user_request=user_request,
        executable_params=executable_params,
        load_mode=load_mode,
        contact_policy=resolved_contact_policy,
    )
    ready_to_generate = bool(allow_defaults or not missing_decisions)
    template_policy = _template_policy(spec, resolved_contact_policy)
    if spec.name in {"tapered_roller", "thrust_bearing", "angular_contact_ball", "needle_roller"} and not spec.starter_templates:
        ready_to_generate = False if not allow_defaults else ready_to_generate
        template_policy["declared_unsupported_fidelity"] = (
            "No trusted full-topology starter template is registered for this bearing family. "
            "Generated-code planning may proceed only after topology-specific decisions are confirmed; "
            "deep-groove ball templates are rejected."
        )

    return {
        "bearing_family": spec.name,
        "rolling_element": spec.rolling_element,
        "load_mode": load_mode,
        "contact_policy": resolved_contact_policy,
        "ready_to_generate": ready_to_generate,
        "missing_decisions": [] if ready_to_generate else missing_decisions,
        "follow_up_questions": [] if ready_to_generate else _follow_up_questions(missing_decisions, spec),
        "resolved_executable_params": executable_params,
        "template_policy": template_policy,
        "recommended_workflow": _recommended_workflow(spec, ready_to_generate, allow_defaults),
        "quality_contract": {
            "quality_gate": spec.quality_gate,
            "bearing_type": spec.bearing_type,
            "required_slots": list(spec.required_slots),
            "geometry_slots": list(spec.geometry_slots),
            "contact_policies": list(spec.contact_policies),
            "default_assumptions": dict(spec.default_assumptions),
            "output_expressions": list(spec.output_expressions),
            "smoke_fidelity_must_be_labeled": spec.name == "deep_groove_ball",
            "reject_topology_substitution": spec.name not in {"deep_groove_ball", "general_bearing"},
        },
        "next_tool_chain": _next_tool_chain(spec, ready_to_generate),
        "archive_path": archive_path,
    }


def normalize_contact_policy(
    contact_policy: str | None,
    user_request: str,
    executable_params: dict[str, str] | None = None,
) -> str:
    explicit = (contact_policy or "").strip().lower().replace(" ", "_").replace("-", "_")
    if explicit in CONTACT_POLICIES:
        return explicit
    text = f"{user_request} {contact_policy or ''}".lower()
    params = executable_params or {}
    if any(marker in text for marker in ("无摩擦", "frictionless", "no friction")):
        return "frictionless"
    if any(marker in text for marker in ("摩擦", "frictional", "friction")) or "friction_coefficient" in params:
        return "frictional"
    if any(marker in text for marker in ("过盈", "interference")) or "contact_interference" in params:
        return "interference_fit"
    if any(marker in text for marker in ("径向预紧", "radial preload")) or "radial_preload" in params:
        return "radial_preload"
    if any(marker in text for marker in ("轴向预紧", "axial preload")) or "axial_preload" in params:
        return "axial_preload"
    if any(marker in text for marker in ("游隙", "clearance")) or "contact_clearance" in params:
        return "clearance"
    if any(marker in text for marker in ("分步", "先接触", "staged")):
        return "staged_contact_activation"
    if any(marker in text for marker in ("保持架接触", "cage-pocket", "cage pocket")):
        return "cage_pocket_contact_load_transfer"
    if any(marker in text for marker in ("真实接触", "real contact", "contact pair", "接触对")):
        return "frictionless"
    return "frictionless"


def infer_load_mode(user_request: str, executable_params: dict[str, str], spec: BearingFamilySpec) -> str:
    text = user_request.lower()
    radial = "radial_load" in executable_params or any(marker in text for marker in ("radial", "径向"))
    axial = "axial_load" in executable_params or any(marker in text for marker in ("axial", "轴向", "推力"))
    if radial and axial:
        return "combined_radial_axial"
    if axial:
        return "axial"
    if radial:
        return "radial"
    return spec.load_modes[0] if spec.load_modes else "radial"


def _normalize_executable_params(params: dict[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_key, raw_value in params.items():
        if raw_value in (None, ""):
            continue
        key = EXECUTABLE_PARAM_ALIASES.get(str(raw_key).strip().lower(), str(raw_key).strip())
        if key.lower() in INTENT_SLOT_KEYS:
            continue
        value = str(raw_value).strip()
        if _looks_like_executable_value(value):
            normalized[key] = value
    return normalized


def _extract_params_from_text(text: str) -> dict[str, str]:
    params: dict[str, str] = {}
    load_match = re.search(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:\[?\s*N\s*\]?|牛)", text, flags=re.IGNORECASE)
    if load_match:
        if any(marker in text for marker in ("轴向", "axial", "推力")) and not any(marker in text for marker in ("径向", "radial")):
            params["axial_load"] = f"{load_match.group(1)}[N]"
        else:
            params["radial_load"] = f"{load_match.group(1)}[N]"
    count_match = re.search(r"(\d+)\s*(?:个)?\s*(滚子|rollers?|滚针|balls?|滚珠)", text, flags=re.IGNORECASE)
    if count_match:
        element = count_match.group(2).lower()
        key = "ball_count" if element in {"ball", "balls", "滚珠"} else "roller_count"
        params[key] = count_match.group(1)
    return params


def _looks_like_executable_value(value: str) -> bool:
    stripped = value.strip()
    if not stripped or stripped.lower() in {"true", "false", "yes", "no"}:
        return False
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", stripped):
        return True
    if "[" in stripped and "]" in stripped:
        return True
    if re.search(r"[+\-*/()]", stripped) and re.search(r"[A-Za-z0-9_]", stripped):
        return True
    return False


def _missing_decisions(
    *,
    spec: BearingFamilySpec,
    user_request: str,
    executable_params: dict[str, str],
    load_mode: str,
    contact_policy: str,
) -> list[str]:
    missing: list[str] = []
    text = user_request.lower()
    if spec.name == "general_bearing":
        missing.append("bearing_type")
    if spec.name == "angular_contact_ball" and "contact_angle" not in executable_params:
        missing.append("contact_angle")
    if spec.name == "tapered_roller":
        for slot in ("cone_angle", "roller_count"):
            if slot not in executable_params:
                missing.append(slot)
    if spec.name == "needle_roller" and "needle_count" not in executable_params and "roller_count" not in executable_params:
        missing.append("needle_count")
    if spec.name == "thrust_bearing" and "axial_load" not in executable_params and "轴向" not in text and "axial" not in text:
        missing.append("axial_load")
    if spec.name == "cylindrical_roller" and "roller_count" not in executable_params and not re.search(r"\d+\s*个?\s*滚子", text):
        missing.append("roller_count")
    if load_mode not in spec.load_modes and not (
        load_mode == "combined_radial_axial" and any("combined" in mode for mode in spec.load_modes)
    ):
        missing.append("load_mode_supported_by_family")
    if contact_policy not in spec.contact_policies:
        missing.append("contact_policy")
    if not any(marker in text for marker in ("输出", "应力", "压力", "位移", "stress", "pressure", "displacement")):
        missing.append("outputs")
    return _dedupe(missing)


def _template_policy(spec: BearingFamilySpec, contact_policy: str) -> dict[str, Any]:
    use_templates = bool(spec.starter_templates)
    return {
        "strategy": "bearing_family_registry_then_topology_specific_template_or_generated_code",
        "family_starter_templates": list(spec.starter_templates),
        "use_template_if_fit": use_templates,
        "contact_policy": contact_policy,
        "smoke_templates": ["bearing_contact_pair_seed", "bearing_contact_hertz_seed"] if spec.name == "deep_groove_ball" else [],
        "reject_deep_groove_substitution": spec.name not in {"deep_groove_ball", "general_bearing"},
        "generated_code_fallback_allowed": True,
    }


def _recommended_workflow(spec: BearingFamilySpec, ready: bool, allow_defaults: bool) -> dict[str, str]:
    if not ready:
        return {
            "action": "ask_follow_up_questions",
            "default_policy": "do_not_generate_until_topology_and_contact_decisions_are_resolved",
        }
    if spec.name == "deep_groove_ball":
        return {
            "action": "run_deep_groove_contact_pair_template_for_labeled_smoke_then_upgrade_if_needed",
            "default_policy": "template_defaults_allowed" if allow_defaults else "use_user_executable_params_only",
        }
    if spec.name == "cylindrical_roller":
        return {
            "action": "use_3d_cylindrical_roller_staged_workflow_with_continuous_boundary_load_diagnostics_or_labeled_legacy_highload_visual",
            "default_policy": "staged_contact_defaults_allowed" if allow_defaults else "use_user_executable_params_only",
        }
    return {
        "action": "generated_code_or_followup_with_declared_unsupported_template_fidelity",
        "default_policy": "do_not_reuse_deep_groove_template_for_this_topology",
    }


def _next_tool_chain(spec: BearingFamilySpec, ready: bool) -> list[str]:
    if not ready:
        return ["ask_follow_up_questions", "simulation_plan_bearing_modeling_request"]
    if spec.name == "deep_groove_ball":
        return [
            "simulation_search_templates",
            "simulation_read_template(bearing_contact_pair_seed)",
            "simulation_run_template(params=resolved_executable_params, validate_first=true)",
            "comsol_solve",
            "comsol_evaluate(solid.mises, solid.disp, contact_pressure_guess)",
            "comsol_plot(expression=solid.mises)",
            "simulation_export_bearing_contact_package",
        ]
    if spec.name == "cylindrical_roller":
        return [
            "simulation_plan_multiroller_bearing",
            "scripts/run_agent_3d_bearing_full_demo.py --direct-fixture-run --contact-stage-mode all_raceway_continuous_boundary_load for inner-bore BoundaryLoad continuation diagnostics; read requested_stage_image and stabilization warnings",
            "scripts/run_agent_3d_bearing_full_demo.py --direct-fixture-run --contact-stage-mode all_raceway_split_control_boundary_load if same-surface bore load/displacement control fails",
            "scripts/run_agent_3d_bearing_full_demo.py --direct-fixture-run --contact-stage-mode all_raceway_high_preload_reaction_equivalent for displacement-control reaction/contact-pressure equivalent-load evidence",
            "scripts/run_agent_3d_bearing_full_demo.py --direct-fixture-run --contact-stage-mode load_side_group_boundary_load for load-side 3/6/all-12 roller inner-bore BoundaryLoad contact continuation after all-12 first-step closure fails",
            "scripts/run_agent_3d_bearing_full_demo.py --direct-fixture-run --contact-stage-mode legacy_raceway_highload_direct for high-load native stress image requests; read requested_stage_image.native_comsol_png from direct_3d_bearing_summary.json",
            "scripts/run_agent_3d_bearing_full_demo.py --direct-fixture-run --contact-stage-mode all_raceway or --run-full-cage-stage for staged raceway/cage verification",
            "simulation_probe_3d_selection_binding",
            "comsol_solve staged raceway-only",
            "comsol_solve staged --run-full-cage-stage when requested",
        ]
    return [
        "simulation_retrieve_api_docs",
        "simulation_plan_generated_code with topology-specific quality contract",
        "simulation_validate_template",
        "simulation_run_template only after no-substitution quality gate passes",
    ]


def _follow_up_questions(missing: list[str], spec: BearingFamilySpec) -> list[str]:
    questions = {
        "bearing_type": "请确认轴承类型，例如深沟球、圆柱滚子、圆锥滚子、滚针或推力轴承。",
        "rolling_element": "请确认滚动体类型和数量。",
        "contact_angle": "角接触球轴承的接触角是多少？请给出数值，例如 15[deg]。",
        "cone_angle": "圆锥滚子轴承的锥角/滚道角是多少？请给出可执行参数，例如 cone_angle=12[deg]。",
        "roller_count": "滚子数量是多少？",
        "needle_count": "滚针数量是多少？",
        "axial_load": "轴向载荷是多少？请给出带单位的值，例如 1000[N]。",
        "load_mode_supported_by_family": f"请确认载荷模式是否适用于 {spec.name}，或改选合适轴承拓扑。",
        "contact_policy": "请选择接触条件：frictionless、frictional、interference_fit、preload、clearance 或 staged_contact_activation。",
        "outputs": "请确认输出项，例如 von Mises 应力、位移和接触压力。",
    }
    return [questions[item] for item in missing if item in questions]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _keyword_matches(text: str, keyword: str) -> bool:
    if any("\u4e00" <= char <= "\u9fff" for char in keyword):
        return keyword in text
    escaped = re.escape(keyword)
    return re.search(rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])", text) is not None
