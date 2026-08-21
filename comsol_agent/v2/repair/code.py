"""M3 Workspace/PatchSet adapter for M6 local code repairs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from comsol_agent.v2.contracts import Observation
from comsol_agent.v2.tools import PatchSet, Workspace

from .models import Diagnosis, RepairCandidate, RepairExecutionLimits


class WorkspaceRepairExecutor:
    """Reuse M3 exact patches and file checkpoints; never edits outside Workspace."""

    def __init__(
        self,
        workspace: Workspace,
        verifier: Callable[[RepairCandidate, Observation], Awaitable[Observation]],
    ) -> None:
        self.workspace = workspace
        self.verifier = verifier
        self._checkpoints: dict[str, str] = {}

    async def create_checkpoint(
        self, diagnosis: Diagnosis, candidate: RepairCandidate
    ) -> str:
        patch = PatchSet.model_validate(candidate.payload["patch"])
        checkpoint = self.workspace.create_checkpoint(
            tuple(item.path for item in patch.replacements)
        )
        self._checkpoints[candidate.candidate_id] = checkpoint.checkpoint_id
        return checkpoint.checkpoint_id

    async def apply(
        self, candidate: RepairCandidate, limits: RepairExecutionLimits
    ) -> None:
        patch = PatchSet.model_validate(candidate.payload["patch"])
        self.workspace.apply_patch(patch)

    async def verify(
        self, candidate: RepairCandidate, trigger: Observation
    ) -> Observation:
        return await self.verifier(candidate, trigger)

    async def rollback(self, checkpoint: str) -> None:
        self.workspace.rollback(checkpoint)

    async def commit(self, checkpoint: str) -> None:
        self.workspace.discard_checkpoint(checkpoint)
