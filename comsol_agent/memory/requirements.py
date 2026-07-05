"""Lightweight multi-turn simulation requirement state.

This module keeps deterministic requirement slots extracted from user turns.
It is intentionally small: the LLM still handles nuanced interpretation, while
the state object prevents obvious cross-turn requirements from being dropped
when a later tool call only contains a short request such as "continue".
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


REQUIREMENT_SLOTS = (
    "geometry",
    "physics",
    "material",
    "boundary_conditions",
    "study_type",
    "outputs",
    "contact_requirements",
    "load_conditions",
    "entity_binding",
    "calibration",
    "user_preferences",
)

EXECUTABLE_PARAM_NAMES = {
    "E",
    "nu",
    "rho",
    "power",
    "T_ambient",
    "voltage",
    "current",
    "torque",
    "rpm",
    "shaft_length",
    "shaft_diameter",
    "eccentricity",
    "board_length",
    "board_width",
    "board_thickness",
    "chip_power",
    "convection_h",
    "gear_module",
    "tooth_count",
    "pressure_angle",
    "face_width",
    "radial_load",
    "ball_count",
    "ball_diameter",
    "inner_diameter",
    "outer_diameter",
    "bearing_width",
}

_SLOT_MARKERS: dict[str, tuple[str, ...]] = {
    "geometry": (
        "geometry",
        "2d",
        "3d",
        "bearing",
        "shaft",
        "gear",
        "pcb",
        "fr4",
        "roller",
        "cylinder",
        "plate",
        "几何",
        "二维",
        "三维",
        "轴承",
        "偏心轴",
        "转轴",
        "齿轮",
        "齿轮副",
        "电路板",
        "线路板",
        "滚子",
        "实体",
    ),
    "physics": (
        "physics",
        "solid mechanics",
        "heat transfer",
        "structural",
        "thermal",
        "electric currents",
        "joule",
        "物理",
        "固体力学",
        "传热",
        "热仿真",
        "焦耳热",
        "结构",
        "力学",
    ),
    "material": (
        "material",
        "steel",
        "copper",
        "aluminum",
        "fr4",
        "材料",
        "钢",
        "铜",
        "铝",
        "基材",
    ),
    "boundary_conditions": (
        "boundary",
        "fixed",
        "constraint",
        "temperature",
        "convection",
        "边界",
        "固定",
        "约束",
        "对流",
    ),
    "study_type": (
        "stationary",
        "time dependent",
        "frequency",
        "eigen",
        "study",
        "稳态",
        "瞬态",
        "频域",
        "研究",
    ),
    "outputs": (
        "output",
        "plot",
        "evaluate",
        "stress",
        "strain",
        "displacement",
        "von mises",
        "结果",
        "输出",
        "云图",
        "应力",
        "位移",
    ),
    "contact_requirements": (
        "contact",
        "contact pair",
        "contact pressure",
        "convergence",
        "接触",
        "收敛",
    ),
    "load_conditions": (
        "load",
        "force",
        "torque",
        "rpm",
        "power",
        "载荷",
        "施加",
        "扭矩",
        "转速",
        "功率",
    ),
    "entity_binding": (
        "entity binding",
        "selection",
        "domain",
        "boundary selection",
        "几何实体绑定",
        "实体绑定",
        "选择",
        "边界选择",
    ),
    "calibration": (
        "calibration",
        "non-zero stress",
        "nonzero stress",
        "非零应力",
        "校准",
    ),
    "user_preferences": (
        "prefer",
        "must",
        "avoid",
        "do not",
        "需要",
        "必须",
        "不要",
        "优先",
    ),
}


@dataclass
class RequirementSlot:
    """One accumulated user requirement slot."""

    value: str
    evidence: list[str] = field(default_factory=list)
    updated_at_turn: int = 0


@dataclass
class ModelingRequest:
    """Separated natural-language intent and executable parameters."""

    intent_slots: dict[str, str]
    executable_params: dict[str, str]
    turn_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RequirementState:
    """Cross-turn requirement memory for simulation planning."""

    slots: dict[str, RequirementSlot] = field(default_factory=dict)
    turn_count: int = 0

    def observe_user_message(self, text: str) -> dict[str, str]:
        """Extract deterministic slot updates from one user message."""
        self.turn_count += 1
        updates = extract_requirement_updates(text)
        for key, value in updates.items():
            self._set_slot(key, value, evidence=text)
        return updates

    def to_known_params(self) -> dict[str, str]:
        """Return legacy decision-slot values for generated-code planning."""
        return {
            key: slot.value
            for key, slot in self.slots.items()
            if key in REQUIREMENT_SLOTS and slot.value.strip()
        }

    def to_modeling_request(self) -> ModelingRequest:
        """Return natural-language intent separately from executable params."""
        intent_slots = self.to_known_params()
        return ModelingRequest(
            intent_slots=intent_slots,
            executable_params=_extract_executable_params(intent_slots),
            turn_count=self.turn_count,
        )

    def merge_known_params(self, known_params: dict[str, Any] | None) -> dict[str, str]:
        """Fill missing known_params from requirement memory.

        Explicit tool arguments win because they may be more specific than the
        deterministic memory summary.
        """
        merged = self.to_known_params()
        for key, value in (known_params or {}).items():
            if value in (None, ""):
                continue
            merged[str(key).strip()] = str(value).strip()
        return merged

    def summary(self) -> str:
        """Human-readable compact state for diagnostics and snapshots."""
        if not self.slots:
            return ""
        return "; ".join(f"{key}: {slot.value}" for key, slot in self.slots.items())

    def _set_slot(self, key: str, value: str, *, evidence: str) -> None:
        current = self.slots.get(key)
        if current is None:
            self.slots[key] = RequirementSlot(
                value=value,
                evidence=[_clip(evidence)],
                updated_at_turn=self.turn_count,
            )
            return

        current.value = _merge_text(current.value, value)
        clipped = _clip(evidence)
        if clipped not in current.evidence:
            current.evidence.append(clipped)
            current.evidence = current.evidence[-3:]
        current.updated_at_turn = self.turn_count


def extract_requirement_updates(text: str) -> dict[str, str]:
    """Extract requirement slot updates with conservative keyword matching."""
    normalized = " ".join(str(text).strip().split())
    if not normalized:
        return {}

    lowered = normalized.lower()
    updates: dict[str, str] = {}
    for slot, markers in _SLOT_MARKERS.items():
        if any(marker in lowered for marker in markers):
            updates[slot] = _slot_value(slot, normalized)
    return updates


def _slot_value(slot: str, text: str) -> str:
    prefix = {
        "contact_requirements": "contact requirements",
        "load_conditions": "load conditions",
        "entity_binding": "entity binding requirements",
        "calibration": "calibration requirements",
        "user_preferences": "user preference",
    }.get(slot)
    if prefix is None:
        return _clip(text, limit=320)
    return f"{prefix}: {_clip(text, limit=280)}"


def _merge_text(previous: str, new: str) -> str:
    if not previous:
        return new
    if new in previous:
        return previous
    if previous in new:
        return new
    return _clip(f"{previous}; {new}", limit=520)


def _clip(text: str, limit: int = 360) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 16)].rstrip() + "...[truncated]"


def _extract_executable_params(slots: dict[str, str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for value in slots.values():
        for name, param_value in re.findall(
            r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]*)\s*=\s*([0-9.+\-eE]+(?:\[[^\]]+\])?)",
            value,
        ):
            if name in EXECUTABLE_PARAM_NAMES or "[" in param_value:
                params[name] = param_value
    return params
