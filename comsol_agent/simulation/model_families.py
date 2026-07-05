"""Model-family registry for high-level simulation planning.

The registry is intentionally independent from executable COMSOL templates:
family specs describe the natural-language modeling intent, while template
parameters remain a smaller executable subset handled by simulation tools.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ModelFamilySpec:
    """Planning metadata for one supported model family."""

    name: str
    domain: str
    keywords: tuple[str, ...]
    required_slots: tuple[str, ...]
    default_assumptions: dict[str, str]
    starter_templates: tuple[str, ...]
    output_expressions: tuple[str, ...]
    quality_gate: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def match_score(self, text: str) -> int:
        lowered = text.lower()
        return sum(1 for keyword in self.keywords if _keyword_matches(lowered, keyword.lower()))


MODEL_FAMILIES: tuple[ModelFamilySpec, ...] = (
    ModelFamilySpec(
        name="bearing_contact",
        domain="structural",
        keywords=(
            "bearing",
            "ball bearing",
            "roller bearing",
            "deep groove",
            "raceway",
            "rolling element",
            "hertz",
            "轴承",
            "滚珠轴承",
            "滚子轴承",
            "滚道",
            "赫兹",
            "轴承接触",
        ),
        required_slots=(
            "geometry",
            "material",
            "load_conditions",
            "contact_requirements",
            "outputs",
        ),
        default_assumptions={
            "geometry": "2D plane-strain single ball/raceway contact cell for first pass",
            "material": "bearing steel",
            "study_type": "stationary structural contact",
            "mesh": "local refinement near contact boundaries",
        },
        starter_templates=("bearing_contact_pair_seed", "bearing_contact_hertz_seed"),
        output_expressions=("solid.mises", "solid.disp", "contact_pressure_guess"),
        quality_gate="validate_bearing_contact_code_draft",
    ),
    ModelFamilySpec(
        name="eccentric_shaft",
        domain="structural",
        keywords=(
            "eccentric shaft",
            "eccentric rotor",
            "offset shaft",
            "rotor",
            "shaft",
            "spindle",
            "unbalance",
            "rpm",
            "偏心轴",
            "偏心转子",
            "转轴",
            "主轴",
            "不平衡",
            "转速",
        ),
        required_slots=(
            "geometry",
            "material",
            "load_conditions",
            "boundary_conditions",
            "outputs",
        ),
        default_assumptions={
            "geometry": "3D cylindrical shaft with a simplified eccentric mass/offset segment",
            "physics": "Solid Mechanics with equivalent centrifugal load for MVP planning",
            "study_type": "stationary structural first pass; modal/frequency response as follow-up",
            "support": "simplified bearing/support constraints at shaft ends",
        },
        starter_templates=(),
        output_expressions=("solid.mises", "solid.disp"),
        quality_gate="validate_eccentric_shaft_code_draft",
    ),
    ModelFamilySpec(
        name="gear_pair",
        domain="structural",
        keywords=(
            "gear",
            "gear pair",
            "meshing",
            "tooth",
            "tooth root",
            "contact pressure",
            "torque",
            "pinion",
            "齿轮",
            "齿轮副",
            "啮合",
            "齿根",
            "齿面",
            "接触压力",
            "扭矩",
        ),
        required_slots=(
            "geometry",
            "material",
            "load_conditions",
            "contact_requirements",
            "outputs",
        ),
        default_assumptions={
            "geometry": "simplified two-gear or single-tooth contact cell before full involute geometry",
            "physics": "Solid Mechanics contact",
            "study_type": "stationary structural contact",
            "mesh": "local refinement at tooth root and contact patch",
        },
        starter_templates=(),
        output_expressions=("solid.mises", "solid.disp", "contact_pressure"),
        quality_gate="validate_gear_pair_code_draft",
    ),
    ModelFamilySpec(
        name="pcb_thermal_electric",
        domain="thermal",
        keywords=(
            "pcb",
            "circuit board",
            "fr4",
            "copper layer",
            "chip",
            "joule",
            "electric thermal",
            "thermal electric",
            "convection",
            "电路板",
            "线路板",
            "芯片",
            "铜层",
            "过孔",
            "焦耳热",
            "热仿真",
            "对流",
        ),
        required_slots=(
            "geometry",
            "material",
            "load_conditions",
            "boundary_conditions",
            "outputs",
        ),
        default_assumptions={
            "geometry": "rectangular FR4 board with simplified copper regions and chip heat sources",
            "physics": "Heat Transfer in Solids for MVP; Electric Currents/Joule heating as follow-up",
            "study_type": "stationary thermal",
            "cooling": "convection boundary where specified",
        },
        starter_templates=(),
        output_expressions=("T", "maxop1(T)", "ec.normJ"),
        quality_gate="validate_pcb_thermal_electric_code_draft",
    ),
    ModelFamilySpec(
        name="general",
        domain="general",
        keywords=("model", "simulation", "comsol", "仿真", "模型", "建模"),
        required_slots=(
            "geometry",
            "physics",
            "material",
            "boundary_conditions",
            "study_type",
            "outputs",
        ),
        default_assumptions={
            "workflow": "clarify problem-defining decisions before generated-code fallback",
        },
        starter_templates=(),
        output_expressions=(),
        quality_gate="validate_general_comsol_code_draft",
    ),
)


def list_model_families() -> list[ModelFamilySpec]:
    """Return all registered model-family specs."""
    return list(MODEL_FAMILIES)


def get_model_family(name: str) -> ModelFamilySpec:
    """Return a model-family spec by name."""
    normalized = name.strip().lower()
    for spec in MODEL_FAMILIES:
        if spec.name == normalized:
            return spec
    raise KeyError(f"Unknown model family: {name}")


def infer_model_family(user_request: str, preferred_model_name: str | None = None) -> ModelFamilySpec:
    """Infer the best model family from user text and optional model name hint."""
    text = " ".join(part for part in (user_request, preferred_model_name or "") if part)
    scored = [(spec.match_score(text), spec) for spec in MODEL_FAMILIES if spec.name != "general"]
    scored.sort(key=lambda item: item[0], reverse=True)
    if scored and scored[0][0] > 0:
        return scored[0][1]
    return get_model_family("general")


def _keyword_matches(text: str, keyword: str) -> bool:
    if any("\u4e00" <= char <= "\u9fff" for char in keyword):
        return keyword in text
    escaped = re.escape(keyword)
    return re.search(rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])", text) is not None
