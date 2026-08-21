"""Domain-neutral V2 agent architecture."""

from comsol_agent.v2 import contracts, extensions, kernel, memory

__all__ = ["contracts", "extensions", "kernel", "memory"]

from comsol_agent.v2.kernel.loop import AgentKernel

__all__ = ["AgentKernel"]
