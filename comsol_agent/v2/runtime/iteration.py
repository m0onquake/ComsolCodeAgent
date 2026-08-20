"""Bounded, evidence-driven code repair orchestration for M3."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol
from uuid import uuid4

from comsol_agent.v2.contracts import Observation
from comsol_agent.v2.kernel import CancellationToken, RunCancelledError
from comsol_agent.v2.tools.models import (
    CodeIterationResult,
    IterationStatus,
    PatchSet,
)
from comsol_agent.v2.tools.testing import TestRunner
from comsol_agent.v2.tools.workspace import Workspace


class EvidenceRepairStrategy(Protocol):
    """Propose a local patch from the most recent structured failure evidence."""

    async def propose(
        self, observation: Observation, workspace: Workspace
    ) -> PatchSet | None: ...


class CodeIterationLoop:
    """Apply a candidate patch and perform a bounded test/repair loop.

    Every patch gets its own file checkpoint. Failure, repeated evidence,
    exhaustion, or cancellation rolls all patches back in reverse order.
    """

    def __init__(
        self,
        workspace: Workspace,
        test_runner: TestRunner,
        *,
        max_repairs: int = 2,
        rollback_on_failure: bool = True,
    ) -> None:
        if max_repairs < 0:
            raise ValueError("max_repairs cannot be negative")
        self.workspace = workspace
        self.test_runner = test_runner
        self.max_repairs = max_repairs
        self.rollback_on_failure = rollback_on_failure

    async def run(
        self,
        *,
        initial_patch: PatchSet,
        repair_strategy: EvidenceRepairStrategy,
        pytest_targets: tuple[str, ...],
        cancellation: CancellationToken | None = None,
        timeout_seconds: float = 120.0,
    ) -> CodeIterationResult:
        token = cancellation or CancellationToken()
        checkpoints: list[str] = []
        patches = []
        observations: list[Observation] = []
        seen_failures: set[str] = set()
        repair_attempts = 0
        try:
            self._apply_with_checkpoint(initial_patch, checkpoints, patches)
            while True:
                token.raise_if_cancelled()
                observation = await self.test_runner.pytest(
                    action_id=uuid4().hex,
                    targets=pytest_targets,
                    timeout_seconds=timeout_seconds,
                    cancellation=token,
                )
                observations.append(observation)
                if observation.success:
                    self._discard(checkpoints)
                    return CodeIterationResult(
                        status=IterationStatus.COMPLETED,
                        observations=[item.model_dump(mode="json") for item in observations],
                        patches=patches,
                        repair_attempts=repair_attempts,
                    )
                fingerprint = self._failure_fingerprint(observation)
                if fingerprint in seen_failures:
                    return self._failed(
                        observations,
                        patches,
                        repair_attempts,
                        checkpoints,
                        "same structured failure repeated after repair",
                    )
                seen_failures.add(fingerprint)
                if not observation.retryable:
                    return self._failed(
                        observations,
                        patches,
                        repair_attempts,
                        checkpoints,
                        f"non-repairable test observation: {observation.error_class}",
                    )
                if repair_attempts >= self.max_repairs:
                    return self._failed(
                        observations,
                        patches,
                        repair_attempts,
                        checkpoints,
                        f"repair budget exhausted (limit={self.max_repairs})",
                    )
                proposal = await repair_strategy.propose(observation, self.workspace)
                if proposal is None:
                    return self._failed(
                        observations,
                        patches,
                        repair_attempts,
                        checkpoints,
                        "repair strategy produced no safe patch",
                    )
                if observation.observation_id not in proposal.evidence:
                    return self._failed(
                        observations,
                        patches,
                        repair_attempts,
                        checkpoints,
                        "repair patch does not cite the triggering Observation",
                    )
                repair_attempts += 1
                self._apply_with_checkpoint(proposal, checkpoints, patches)
        except RunCancelledError:
            self._rollback(checkpoints)
            raise
        except Exception:
            self._rollback(checkpoints)
            raise

    def _apply_with_checkpoint(
        self, patch: PatchSet, checkpoints: list[str], patches: list
    ) -> None:
        paths = tuple(replacement.path for replacement in patch.replacements)
        checkpoint = self.workspace.create_checkpoint(paths)
        checkpoints.append(checkpoint.checkpoint_id)
        patches.append(self.workspace.apply_patch(patch))

    def _failed(
        self,
        observations: list[Observation],
        patches: list,
        repair_attempts: int,
        checkpoints: list[str],
        reason: str,
    ) -> CodeIterationResult:
        rolled_back = False
        if self.rollback_on_failure:
            self._rollback(checkpoints)
            rolled_back = True
        else:
            self._discard(checkpoints)
        return CodeIterationResult(
            status=IterationStatus.FAILED,
            observations=[item.model_dump(mode="json") for item in observations],
            patches=patches,
            repair_attempts=repair_attempts,
            rolled_back=rolled_back,
            failure_reason=reason,
        )

    def _rollback(self, checkpoints: list[str]) -> None:
        while checkpoints:
            self.workspace.rollback(checkpoints.pop())

    def _discard(self, checkpoints: list[str]) -> None:
        while checkpoints:
            self.workspace.discard_checkpoint(checkpoints.pop())

    @staticmethod
    def _failure_fingerprint(observation: Observation) -> str:
        evidence = {
            "error_class": observation.error_class,
            "failures": observation.data.get("failures", []),
            "exit_code": observation.data.get("exit_code"),
        }
        encoded = json.dumps(evidence, sort_keys=True, ensure_ascii=True).encode()
        return hashlib.sha256(encoded).hexdigest()
