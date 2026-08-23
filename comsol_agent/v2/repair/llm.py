"""Restricted LLM CandidateProvider producing only exact M3 PatchSet values."""

from __future__ import annotations

import json
from pathlib import PurePosixPath

from comsol_agent.v2.contracts import Observation
from comsol_agent.v2.model_gateway import ModelGateway, ModelRequest, ModelTask
from comsol_agent.v2.tools import PatchSet

from .models import Diagnosis, RepairCandidate, RepairKind

REPAIR_PROMPT_ID = "repair.exact-local-patch"
REPAIR_PROMPT_VERSION = "1.0.0"


class RestrictedLLMPatchProvider:
    """Callable adapter for M6; it never executes model code or commands."""

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        verifier: str,
        required_gates: frozenset[str],
        max_replacements: int = 8,
    ) -> None:
        self.gateway = gateway
        self.verifier = verifier
        self.required_gates = required_gates
        self.max_replacements = max_replacements

    async def __call__(
        self, diagnosis: Diagnosis, observation: Observation
    ) -> RepairCandidate | None:
        if RepairKind.LLM_PATCH not in diagnosis.allowed_repair_kinds:
            return None
        allowed_paths = tuple(diagnosis.affected_scope.targets)
        if diagnosis.affected_scope.kind not in {"file", "workspace"} or not allowed_paths:
            return None
        request = ModelRequest(
            task=ModelTask.LOCAL_REPAIR,
            prompt_id=REPAIR_PROMPT_ID,
            prompt_version=REPAIR_PROMPT_VERSION,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return one exact local PatchSet JSON object. Use only allowed_paths and "
                        "exact old/new text replacements. Do not emit commands, shell, Java model "
                        "programs, Python programs, whole files, permission changes, or prose."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "diagnosis": diagnosis.model_dump(mode="json"),
                            "trigger": {
                                "observation_id": observation.observation_id,
                                "stage": observation.stage,
                                "status": observation.status,
                                "error_class": observation.error_class,
                                "data": observation.data,
                            },
                            "allowed_paths": allowed_paths,
                            "max_replacements": self.max_replacements,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            output_schema_id="m3-patch-set",
            output_schema_version="1.0",
            output_json_schema=PatchSet.model_json_schema(),
            max_output_tokens=4000,
            max_retries=1,
            metadata={"authority": "candidate_only", "execution": False},
        )
        response = await self.gateway.complete(request)
        patch = PatchSet.model_validate(response.structured.value)
        self._validate_patch(patch, allowed_paths)
        return RepairCandidate(
            kind=RepairKind.LLM_PATCH,
            observation_id=observation.observation_id,
            diagnosis_fingerprint=diagnosis.fingerprint,
            scope=diagnosis.affected_scope,
            verifier=self.verifier,
            payload={"patch": patch.model_dump(mode="json")},
            provenance=(
                f"model_gateway:{response.provider}/{response.model}:"
                f"{response.request_id}:{REPAIR_PROMPT_VERSION}"
            ),
            required_gates=self.required_gates,
        )

    def _validate_patch(self, patch: PatchSet, allowed_paths: tuple[str, ...]) -> None:
        if len(patch.replacements) > self.max_replacements:
            raise ValueError("LLM patch exceeds replacement budget")
        allowed = {str(PurePosixPath(path)) for path in allowed_paths}
        for replacement in patch.replacements:
            path = str(PurePosixPath(replacement.path))
            if path not in allowed:
                raise ValueError(f"LLM patch path is outside diagnosed scope: {path}")
            if replacement.expected_count != 1:
                raise ValueError("LLM patches require exact single-match replacements")
            if len(replacement.old) > 8000 or len(replacement.new) > 8000:
                raise ValueError("LLM patch replacement is too large")
            lowered = replacement.new.lower()
            if any(token in lowered for token in ("subprocess.", "os.system(", "runtime.exec(")):
                raise ValueError("LLM patch attempts to introduce command execution")
