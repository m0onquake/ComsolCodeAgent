"""Bearing-contact parameter planning helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from comsol_agent.simulation.skills import BEARING_CONTACT_DEFAULTS


@dataclass(frozen=True)
class BearingContactField:
    """One user-facing bearing-contact setup field."""

    name: str
    label: str
    default: str
    required_for_production: bool
    question: str
    assumption: str


@dataclass(frozen=True)
class BearingContactPlan:
    """Structured plan for quick-demo or clarification-first bearing setup."""

    ready_to_run: bool
    mode: str
    template_name: str
    provided_params: dict[str, str]
    resolved_params: dict[str, str]
    defaulted_params: dict[str, str]
    missing_required: list[str]
    follow_up_questions: list[str]
    assumptions: list[str]
    recommended_outputs: list[str]
    next_steps: list[str]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MultirollerBearingPlan:
    """Structured plan for a real multi-roller bearing contact workflow."""

    ready_to_run: bool
    mode: str
    workflow: str
    provided_params: dict[str, str]
    resolved_params: dict[str, str]
    defaulted_params: dict[str, str]
    missing_required: list[str]
    follow_up_questions: list[str]
    assumptions: list[str]
    contact_requirements: list[str]
    generated_code_requirements: list[str]
    recommended_outputs: list[str]
    next_steps: list[str]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


BEARING_CONTACT_FIELDS: tuple[BearingContactField, ...] = (
    BearingContactField(
        name="bearing_type",
        label="Bearing type",
        default="deep_groove_ball_bearing",
        required_for_production=True,
        question="轴承类型是什么？如果不确定，我将按深沟球轴承处理。",
        assumption="Default bearing type is a deep-groove ball bearing.",
    ),
    BearingContactField(
        name="inner_diameter",
        label="Inner diameter",
        default=BEARING_CONTACT_DEFAULTS["inner_diameter"],
        required_for_production=True,
        question="内径是多少？请给出带单位的值，例如 25[mm]。",
        assumption="Inner diameter defaults to 25[mm].",
    ),
    BearingContactField(
        name="outer_diameter",
        label="Outer diameter",
        default=BEARING_CONTACT_DEFAULTS["outer_diameter"],
        required_for_production=True,
        question="外径是多少？请给出带单位的值，例如 52[mm]。",
        assumption="Outer diameter defaults to 52[mm].",
    ),
    BearingContactField(
        name="bearing_width",
        label="Bearing width",
        default=BEARING_CONTACT_DEFAULTS["bearing_width"],
        required_for_production=True,
        question="轴承宽度是多少？请给出带单位的值，例如 15[mm]。",
        assumption="Bearing width defaults to 15[mm].",
    ),
    BearingContactField(
        name="ball_count",
        label="Ball count",
        default=BEARING_CONTACT_DEFAULTS["ball_count"],
        required_for_production=False,
        question="滚珠数量是多少？如果未知，默认使用 8。",
        assumption="Ball count defaults to 8.",
    ),
    BearingContactField(
        name="ball_diameter",
        label="Ball diameter",
        default=BEARING_CONTACT_DEFAULTS["ball_diameter"],
        required_for_production=True,
        question="滚珠直径是多少？请给出带单位的值，例如 7.94[mm]。",
        assumption="Ball diameter defaults to 7.94[mm].",
    ),
    BearingContactField(
        name="radial_load",
        label="Radial load",
        default=BEARING_CONTACT_DEFAULTS["radial_load"],
        required_for_production=True,
        question="径向载荷是多少？请给出带单位的值，例如 1000[N]。",
        assumption="Radial load defaults to 1000[N].",
    ),
    BearingContactField(
        name="material",
        label="Material",
        default="bearing_steel",
        required_for_production=False,
        question="材料是什么？如果未知，默认使用轴承钢 E=210[GPa], nu=0.30。",
        assumption="Material defaults to bearing steel with E=210[GPa], nu=0.30.",
    ),
    BearingContactField(
        name="contact_model",
        label="Contact model",
        default="2d_plane_strain_hertz_style_pressure",
        required_for_production=True,
        question="需要快速 2D Hertz-style 默认案例，还是生产级 3D 接触对模型？",
        assumption="Default model is a 2D plane-strain single-ball/raceway Hertz-style pressure cell.",
    ),
    BearingContactField(
        name="friction_coefficient",
        label="Friction coefficient",
        default=BEARING_CONTACT_DEFAULTS["friction_coefficient"],
        required_for_production=False,
        question="摩擦系数是多少？润滑钢-钢接触可先用 0.05。",
        assumption="Friction coefficient defaults to 0.05.",
    ),
)


MULTIROLLER_DEFAULTS: dict[str, str] = {
    "bearing_type": "cylindrical_roller_bearing",
    "inner_diameter": "40[mm]",
    "outer_diameter": "80[mm]",
    "bearing_width": "18[mm]",
    "roller_count": "8",
    "roller_diameter": "8[mm]",
    "roller_length": "16[mm]",
    "radial_load": "3000[N]",
    "material": "bearing_steel",
    "E_steel": "210[GPa]",
    "nu_steel": "0.30",
    "rho_steel": "7850[kg/m^3]",
    "friction_coefficient": "0.05",
    "contact_interference": "2[um]",
    "contact_model": "2d_plane_strain_multiroller_contact_pair",
    "cage_included": "false",
    "sector_angle": "90[deg]",
    "mesh_contact_size": "0.08[mm]",
    "mesh_bulk_size": "0.8[mm]",
}


MULTIROLLER_FIELDS: tuple[BearingContactField, ...] = (
    BearingContactField(
        name="bearing_type",
        label="Bearing type",
        default=MULTIROLLER_DEFAULTS["bearing_type"],
        required_for_production=True,
        question="轴承类型是什么？例如圆柱滚子、滚针或调心滚子轴承。",
        assumption="Default bearing type is a cylindrical roller bearing.",
    ),
    BearingContactField(
        name="inner_diameter",
        label="Inner diameter",
        default=MULTIROLLER_DEFAULTS["inner_diameter"],
        required_for_production=True,
        question="内圈内径是多少？请给出带单位的值，例如 40[mm]。",
        assumption="Inner diameter defaults to 40[mm].",
    ),
    BearingContactField(
        name="outer_diameter",
        label="Outer diameter",
        default=MULTIROLLER_DEFAULTS["outer_diameter"],
        required_for_production=True,
        question="外圈外径是多少？请给出带单位的值，例如 80[mm]。",
        assumption="Outer diameter defaults to 80[mm].",
    ),
    BearingContactField(
        name="bearing_width",
        label="Bearing width",
        default=MULTIROLLER_DEFAULTS["bearing_width"],
        required_for_production=True,
        question="轴承宽度是多少？请给出带单位的值，例如 18[mm]。",
        assumption="Bearing width defaults to 18[mm].",
    ),
    BearingContactField(
        name="roller_count",
        label="Roller count",
        default=MULTIROLLER_DEFAULTS["roller_count"],
        required_for_production=True,
        question="滚子/滚针数量是多少？",
        assumption="Roller count defaults to 8.",
    ),
    BearingContactField(
        name="roller_diameter",
        label="Roller diameter",
        default=MULTIROLLER_DEFAULTS["roller_diameter"],
        required_for_production=True,
        question="滚子直径是多少？请给出带单位的值，例如 8[mm]。",
        assumption="Roller diameter defaults to 8[mm].",
    ),
    BearingContactField(
        name="roller_length",
        label="Roller length",
        default=MULTIROLLER_DEFAULTS["roller_length"],
        required_for_production=True,
        question="滚子有效长度是多少？请给出带单位的值，例如 16[mm]。",
        assumption="Roller length defaults to 16[mm].",
    ),
    BearingContactField(
        name="radial_load",
        label="Radial load",
        default=MULTIROLLER_DEFAULTS["radial_load"],
        required_for_production=True,
        question="径向载荷是多少？请给出带单位的值，例如 3000[N]。",
        assumption="Radial load defaults to 3000[N].",
    ),
    BearingContactField(
        name="contact_model",
        label="Contact model",
        default=MULTIROLLER_DEFAULTS["contact_model"],
        required_for_production=True,
        question="接触模型采用 2D 平面应变扇区、多滚子接触对，还是完整 3D 多滚子模型？",
        assumption="Default contact model is a 2D plane-strain multi-roller contact-pair sector.",
    ),
    BearingContactField(
        name="cage_included",
        label="Cage included",
        default=MULTIROLLER_DEFAULTS["cage_included"],
        required_for_production=False,
        question="是否需要建立保持架几何或保持架约束？",
        assumption="Cage is omitted in the first run; roller spacing is represented by explicit roller positions/constraints.",
    ),
    BearingContactField(
        name="friction_coefficient",
        label="Friction coefficient",
        default=MULTIROLLER_DEFAULTS["friction_coefficient"],
        required_for_production=False,
        question="接触摩擦系数是多少？润滑钢-钢接触可先用 0.05。",
        assumption="Friction coefficient defaults to 0.05.",
    ),
)


def plan_bearing_contact_setup(
    *,
    user_request: str,
    provided_params: dict[str, Any] | None = None,
    allow_defaults: bool = False,
) -> BearingContactPlan:
    """Plan clarification/default handling for a bearing-contact simulation."""
    normalized_params = _normalize_params(provided_params or {})
    quick_demo = allow_defaults or _looks_like_quick_demo(user_request)
    required_missing = [
        field.name
        for field in BEARING_CONTACT_FIELDS
        if field.required_for_production and field.name not in normalized_params
    ]
    defaulted_fields = [
        field
        for field in BEARING_CONTACT_FIELDS
        if field.name not in normalized_params
    ]
    resolved = {
        field.name: normalized_params.get(field.name, field.default)
        for field in BEARING_CONTACT_FIELDS
    }
    resolved.update(_template_param_subset(normalized_params))
    defaulted = {field.name: field.default for field in defaulted_fields}
    mode = "quick_default_demo" if quick_demo else "clarify_before_run"
    ready = quick_demo or not required_missing
    questions = [] if ready else [field.question for field in BEARING_CONTACT_FIELDS if field.name in required_missing]
    assumptions = [field.assumption for field in defaulted_fields] if ready else []
    template_name = _select_template_name(user_request, normalized_params)
    notes = [
        f"Use {template_name} for this planned workflow.",
        "bearing_contact_pair_seed is an explicit 2D COMSOL contact-pair cell; bearing_contact_hertz_seed remains the lighter Hertz-style pressure workflow.",
        "Neither built-in bearing seed is a full production 3D multi-ball bearing model yet.",
    ]
    if not ready:
        notes.append("Ask the follow-up questions before creating/running a COMSOL model.")

    return BearingContactPlan(
        ready_to_run=ready,
        mode=mode,
        template_name=template_name,
        provided_params=normalized_params,
        resolved_params=resolved,
        defaulted_params=defaulted,
        missing_required=required_missing if not ready else [],
        follow_up_questions=questions,
        assumptions=assumptions,
        recommended_outputs=[
            "solid.mises",
            "contact_pressure_guess",
            "runtime_smoke/bearing_contact_demo/bearing_contact_von_mises.png",
        ],
        next_steps=_next_steps(ready),
        notes=notes,
    )


def plan_multiroller_bearing_setup(
    *,
    user_request: str,
    provided_params: dict[str, Any] | None = None,
    allow_defaults: bool = False,
) -> MultirollerBearingPlan:
    """Plan a multi-roller bearing workflow without substituting unrelated structures."""
    normalized_params = _normalize_multiroller_params(provided_params or {})
    quick_demo = allow_defaults or _looks_like_quick_demo(user_request)
    missing = [
        field.name
        for field in MULTIROLLER_FIELDS
        if field.required_for_production and field.name not in normalized_params
    ]
    defaulted_fields = [
        field
        for field in MULTIROLLER_FIELDS
        if field.name not in normalized_params
    ]
    resolved = {
        field.name: normalized_params.get(field.name, field.default)
        for field in MULTIROLLER_FIELDS
    }
    for key, value in MULTIROLLER_DEFAULTS.items():
        resolved.setdefault(key, normalized_params.get(key, value))
    defaulted = {field.name: field.default for field in defaulted_fields}
    ready = quick_demo or not missing
    mode = "quick_default_real_contact_demo" if quick_demo else "clarify_before_run"
    questions = [] if ready else [field.question for field in MULTIROLLER_FIELDS if field.name in missing]
    assumptions = [field.assumption for field in defaulted_fields] if ready else []
    if ready and resolved.get("cage_included", "false").lower() in {"false", "no", "0"}:
        assumptions.append(
            "Cage geometry is not built in the first demo; the report must state this and preserve a cage-extension step."
        )

    contact_requirements = [
        "Model inner ring, outer ring, and at least two rolling elements; do not replace the bearing with a plate/block surrogate.",
        "Create explicit COMSOL Contact Pair/Contact features for roller-to-inner-raceway and roller-to-outer-raceway interfaces.",
        "Apply radial load through the inner ring or roller set and constrain the outer ring/raceway with engineering-meaningful supports.",
        "Use Solid Mechanics with stationary nonlinear contact; keep mesh refined at roller/raceway contact boundaries.",
    ]
    generated_code_requirements = [
        "Use generated-code fallback unless a true multi-roller contact template is found.",
        "Generated Java/API code must create parameters, ring/raceway geometry, multiple rollers, materials, contact pairs, mesh, study, and stress plot.",
        "The code must expose result expressions for solid.mises and a contact-pressure/contact-status estimate when available.",
        "The result package must include max stress, approximate max location or highest-risk roller/contact region, and whether inner/outer contact pairs were created.",
    ]
    notes = [
        "No built-in multi-roller contact template is currently trusted; use template search first, then generated-code fallback.",
        "A 2D plane-strain sector or reduced roller count is acceptable only if rollers still physically contact inner/outer raceways.",
        "A full production 3D bearing with cage, end effects, and convergence studies remains a follow-up after this real-contact demo.",
    ]
    if not ready:
        notes.append("Ask the follow-up questions before generating or executing COMSOL code.")

    return MultirollerBearingPlan(
        ready_to_run=ready,
        mode=mode,
        workflow="generated_code_multiroller_contact",
        provided_params=normalized_params,
        resolved_params=resolved,
        defaulted_params=defaulted,
        missing_required=missing if not ready else [],
        follow_up_questions=questions,
        assumptions=assumptions,
        contact_requirements=contact_requirements,
        generated_code_requirements=generated_code_requirements,
        recommended_outputs=[
            "solid.mises",
            "contact pressure/status by roller-raceway contact pair when available",
            "von_mises.png",
            "summary.json",
            "report.md or report.html",
        ],
        next_steps=_multiroller_next_steps(ready),
        notes=notes,
    )


def _normalize_params(params: dict[str, Any]) -> dict[str, str]:
    normalized = {}
    aliases = {
        "id": "inner_diameter",
        "od": "outer_diameter",
        "width": "bearing_width",
        "balls": "ball_count",
        "load": "radial_load",
        "friction": "friction_coefficient",
    }
    for key, value in params.items():
        if value in (None, ""):
            continue
        normalized_key = aliases.get(str(key).strip().lower(), str(key).strip())
        normalized[normalized_key] = str(value).strip()
    return normalized


def _normalize_multiroller_params(params: dict[str, Any]) -> dict[str, str]:
    normalized = {}
    aliases = {
        "id": "inner_diameter",
        "od": "outer_diameter",
        "width": "bearing_width",
        "rollers": "roller_count",
        "roller_num": "roller_count",
        "roller_number": "roller_count",
        "roller_d": "roller_diameter",
        "roller_dia": "roller_diameter",
        "roller_l": "roller_length",
        "load": "radial_load",
        "friction": "friction_coefficient",
        "cage": "cage_included",
        "保持架": "cage_included",
        "滚子数量": "roller_count",
        "滚子直径": "roller_diameter",
        "滚子长度": "roller_length",
    }
    for key, value in params.items():
        if value in (None, ""):
            continue
        normalized_key = aliases.get(str(key).strip().lower(), str(key).strip())
        normalized[normalized_key] = str(value).strip()
    return normalized


def _template_param_subset(params: dict[str, str]) -> dict[str, str]:
    return {name: value for name, value in params.items() if name in BEARING_CONTACT_DEFAULTS}


def _looks_like_quick_demo(user_request: str) -> bool:
    lowered = user_request.lower()
    quick_markers = (
        "default",
        "demo",
        "example",
        "quick",
        "默认",
        "案例",
        "示例",
        "先跑",
        "跑通",
    )
    return any(marker in lowered for marker in quick_markers)


def _select_template_name(user_request: str, params: dict[str, str]) -> str:
    requested_model = params.get("contact_model", "")
    lowered = f"{user_request} {requested_model}".lower()
    pair_markers = (
        "contact pair",
        "real contact",
        "realistic",
        "production",
        "真实",
        "更真实",
        "接触对",
        "生产级",
    )
    if any(marker in lowered for marker in pair_markers):
        return "bearing_contact_pair_seed"
    return "bearing_contact_hertz_seed"


def _next_steps(ready: bool) -> list[str]:
    if not ready:
        return [
            "Ask the listed follow-up questions.",
            "Call this planner again with the user's answers in provided_params.",
            "Run bearing_contact_hertz_seed only after ready_to_run is true.",
        ]
    return [
        "Search/read/validate the recommended bearing-contact template.",
        "Run simulation_run_template with close_model=false.",
        "Solve the default study, evaluate solid.mises and contact_pressure_guess, export the stress PNG, and archive/report the run.",
    ]


def _multiroller_next_steps(ready: bool) -> list[str]:
    if not ready:
        return [
            "Ask the listed follow-up questions.",
            "Call this planner again with the user's answers in provided_params.",
            "Do not generate or execute COMSOL code until the real-contact bearing scope is explicit or defaults are allowed.",
        ]
    return [
        "Search existing templates for multi-roller contact coverage.",
        "If no true multi-roller contact template fits, call simulation_plan_generated_code with the resolved parameters and contact requirements.",
        "Generate setup-only COMSOL Java/API code for rings, rollers, contact pairs, mesh, study, and stress outputs.",
        "Validate, execute on a new model, solve, plot solid.mises, package results, and answer artifact questions from the package.",
    ]
