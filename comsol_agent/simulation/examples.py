"""Built-in COMSOL example model catalog and runtime helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SimulationExample:
    """A runnable local COMSOL example model."""

    name: str
    domain: str
    description: str
    model_path: str
    default_expression: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["available"] = Path(self.model_path).exists()
        return data


BUILTIN_EXAMPLES: tuple[SimulationExample, ...] = (
    SimulationExample(
        name="thermal_slab",
        domain="thermal",
        description="COMSOL built-in heat conduction in a slab example.",
        model_path=(
            "/Applications/COMSOL62/Multiphysics/applications/Heat_Transfer_Module/"
            "Tutorials,_Conduction/heat_conduction_in_slab.mph"
        ),
        default_expression="T",
    ),
    SimulationExample(
        name="thermal_heat_sink",
        domain="thermal",
        description="COMSOL built-in heat sink tutorial model.",
        model_path=(
            "/Applications/COMSOL62/Multiphysics/applications/Heat_Transfer_Module/"
            "Tutorials,_Forced_and_Natural_Convection/heat_sink.mph"
        ),
        default_expression="T",
    ),
)


def list_examples(domain: str | None = None) -> list[SimulationExample]:
    """Return built-in runnable example models."""
    if domain is None:
        return list(BUILTIN_EXAMPLES)
    normalized = domain.lower()
    return [example for example in BUILTIN_EXAMPLES if example.domain.lower() == normalized]


def get_example(name: str) -> SimulationExample:
    """Return a built-in example by name."""
    normalized = name.lower()
    for example in BUILTIN_EXAMPLES:
        if example.name == normalized:
            return example
    raise KeyError(f"Unknown simulation example: {name}")
