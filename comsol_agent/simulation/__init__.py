"""Simulation domain skills and templates."""

from comsol_agent.simulation.skills import (
    BUILTIN_SKILLS,
    SimulationSkill,
    build_skill_context_message,
    get_skill,
    list_skills,
    match_skills,
    seed_builtin_templates,
)
from comsol_agent.simulation.local_docs import (
    DocumentChunk,
    LocalDocumentIndex,
    SearchResult,
    build_index_from_directory,
)
from comsol_agent.simulation.examples import (
    BUILTIN_EXAMPLES,
    SimulationExample,
    get_example,
    list_examples,
)
from comsol_agent.simulation.sweeps import SweepAxis, SweepCase, SweepPlan, plan_parameter_sweep

__all__ = [
    "BUILTIN_SKILLS",
    "BUILTIN_EXAMPLES",
    "DocumentChunk",
    "LocalDocumentIndex",
    "SearchResult",
    "SimulationExample",
    "SimulationSkill",
    "SweepAxis",
    "SweepCase",
    "SweepPlan",
    "build_skill_context_message",
    "build_index_from_directory",
    "get_example",
    "get_skill",
    "list_examples",
    "list_skills",
    "match_skills",
    "plan_parameter_sweep",
    "seed_builtin_templates",
]
