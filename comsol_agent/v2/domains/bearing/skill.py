"""Permission-neutral workflow instructions for the bearing plugin."""

from __future__ import annotations

from typing import Any


class BearingSkill:
    async def instructions(self, context: Any) -> str:
        return """# Build cylindrical roller bearing (V2)

1. Parse and validate `BearingSpec`; preserve explicit units and provenance.
2. Compare against the prior spec with `bearing.change-set.classify`.
3. If the route is `parameter_override`, restore the compatible B checkpoint,
   apply only typed parameters, run direction-aware load continuation, and audit.
4. If only roller count changes, run the registered deterministic builder; never
   ask an LLM to rewrite the full model.
5. Execute A geometry, B selections/contact/physics/mesh, C solve continuation,
   and D result audits as separate gates. Default engineering preview acceptance
   uses a finite approximate target stress and matching native plot; strict force
   balance remains a separate report and does not block preview delivery.
6. A failed selection/contact gate stops before solve. Non-convergence may use a
   bounded Solver Strategy but may not change geometry or audit thresholds.
7. Promote evidence only after the target load step, force balance, stability,
   loaded-zone direction, native plot, solved MPH, hashes and provenance pass.
   Engineering preview acceptance is never sufficient for verified memory.

This Skill grants no permissions. COMSOL writes/solve authority comes only from
the registered MCP tools and their pinned extension snapshot.
"""
