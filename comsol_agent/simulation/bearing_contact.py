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
    notes = [
        "Use bearing_contact_hertz_seed for the first runnable default workflow.",
        "The current default is a 2D plane-strain Hertz-style smoke case, not a production 3D contact-pair model.",
    ]
    if not ready:
        notes.append("Ask the follow-up questions before creating/running a COMSOL model.")

    return BearingContactPlan(
        ready_to_run=ready,
        mode=mode,
        template_name="bearing_contact_hertz_seed",
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


def _next_steps(ready: bool) -> list[str]:
    if not ready:
        return [
            "Ask the listed follow-up questions.",
            "Call this planner again with the user's answers in provided_params.",
            "Run bearing_contact_hertz_seed only after ready_to_run is true.",
        ]
    return [
        "Search/read/validate bearing_contact_hertz_seed.",
        "Run simulation_run_template with close_model=false.",
        "Solve the default study, evaluate solid.mises and contact_pressure_guess, export the stress PNG, and archive/report the run.",
    ]
