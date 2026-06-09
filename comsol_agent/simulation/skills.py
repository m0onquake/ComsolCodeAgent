"""Built-in simulation skills and template helpers."""

from __future__ import annotations

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
        lowered = text.lower()
        return any(keyword.lower() in lowered for keyword in self.keywords)

    def context_text(self) -> str:
        return (
            f"[Simulation skill: {self.name}]\n"
            f"Domain: {self.domain}\n"
            f"Physics interfaces: {', '.join(self.physics_interfaces)}\n"
            f"Key parameters: {', '.join(self.key_parameters)}\n"
            "Common checks:\n"
            + "\n".join(f"- {check}" for check in self.common_checks)
        )


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


def get_skill(name: str) -> SimulationSkill:
    """Return a skill by name or domain."""
    normalized = name.lower()
    for skill in BUILTIN_SKILLS:
        if skill.name == normalized or skill.domain == normalized:
            return skill
    raise KeyError(f"Unknown simulation skill: {name}")


def match_skills(text: str, limit: int = 2) -> list[SimulationSkill]:
    """Match skills by domain keywords."""
    matches = [skill for skill in BUILTIN_SKILLS if skill.matches(text)]
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
