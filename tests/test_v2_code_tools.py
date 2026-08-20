"""M3 acceptance tests for workspace, sandbox, runners, and code iteration."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

import pytest

from comsol_agent.v2.contracts import Action, Observation
from comsol_agent.v2.kernel import CancellationToken, RunCancelledError
from comsol_agent.v2.runtime import CodeIterationLoop
from comsol_agent.v2.tools import (
    CodeToolExecutor,
    CommandSpec,
    PatchSet,
    ShellSandbox,
    TestRunner,
    TextReplacement,
    Workspace,
    WorkspaceToolError,
)

FIXTURE_REPOSITORY = Path(__file__).parent / "fixtures" / "m3_code_repo"


def copy_fixture_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "fixture-repository"
    shutil.copytree(FIXTURE_REPOSITORY, repository)
    return repository


def make_tools(root: Path) -> tuple[Workspace, ShellSandbox, TestRunner]:
    workspace = Workspace(root)
    ruff = Path(sys.executable).with_name("ruff")
    allowed = [Path(sys.executable)]
    if ruff.exists():
        allowed.append(ruff)
    sandbox = ShellSandbox(
        workspace,
        allowed_executables=tuple(allowed),
        allowed_argument_prefixes={
            Path(sys.executable): (("-m", "pytest"), ("-c",)),
            **({ruff: (("check",),)} if ruff.exists() else {}),
        },
        max_timeout_seconds=300,
    )
    runner = TestRunner(
        sandbox,
        python_executable=sys.executable,
        ruff_executable=ruff if ruff.exists() else None,
    )
    return workspace, sandbox, runner


class EmptyUsernameRepair:
    async def propose(
        self, observation: Observation, workspace: Workspace
    ) -> PatchSet | None:
        evidence = json.dumps(observation.data["failures"])
        if "rejects_empty_values" not in evidence or "DID NOT RAISE" not in evidence:
            return None
        current = workspace.read("sample_project/usernames.py").content
        assert "return value.strip().lower()" in current
        return PatchSet(
            description="Reject the empty normalized username reported by pytest",
            evidence=[observation.observation_id],
            replacements=[
                TextReplacement(
                    path="sample_project/usernames.py",
                    old="    return value.strip().lower()\n",
                    new=(
                        "    normalized = value.strip().lower()\n"
                        "    if not normalized:\n"
                        "        raise ValueError(\"username cannot be empty\")\n"
                        "    return normalized\n"
                    ),
                )
            ],
        )


class NoRepair:
    async def propose(
        self, observation: Observation, workspace: Workspace
    ) -> PatchSet | None:
        return None


def initial_lowercase_patch() -> PatchSet:
    return PatchSet(
        description="Normalize usernames to lowercase",
        replacements=[
            TextReplacement(
                path="sample_project/usernames.py",
                old="    return value.strip()\n",
                new="    return value.strip().lower()\n",
            )
        ],
    )


class TestWorkspaceTools:
    def test_search_read_exact_patch_and_checkpoint_rollback(self, tmp_path: Path):
        root = copy_fixture_repository(tmp_path)
        workspace = Workspace(root)

        matches = workspace.search("normalize_username", include=("*.py",))
        read = workspace.read("sample_project/usernames.py")
        checkpoint = workspace.create_checkpoint(("sample_project/usernames.py",))
        applied = workspace.apply_patch(initial_lowercase_patch())

        assert matches[0].path == "sample_project/__init__.py"
        assert read.sha256
        assert applied.paths == ["sample_project/usernames.py"]
        assert "+    return value.strip().lower()" in applied.diff
        workspace.rollback(checkpoint.checkpoint_id)
        assert workspace.read("sample_project/usernames.py").content == read.content

    def test_rejects_escape_absolute_symlink_and_ambiguous_patch(self, tmp_path: Path):
        root = copy_fixture_repository(tmp_path)
        workspace = Workspace(root)
        (root / "linked.py").symlink_to(root / "sample_project" / "usernames.py")

        for path in ("../outside.py", str(root / "sample_project" / "usernames.py"), "linked.py"):
            with pytest.raises(WorkspaceToolError):
                workspace.read(path)
        with pytest.raises(WorkspaceToolError, match="found 0"):
            workspace.apply_patch(
                PatchSet(
                    description="conflicting edit",
                    replacements=[
                        TextReplacement(
                            path="sample_project/usernames.py",
                            old="text that is not present",
                            new="replacement",
                        )
                    ],
                )
            )


class TestShellSandbox:
    @pytest.mark.asyncio
    async def test_timeout_kills_command_and_returns_structured_result(self, tmp_path: Path):
        _, sandbox, _ = make_tools(copy_fixture_repository(tmp_path))

        result = await sandbox.run(
            CommandSpec(
                argv=[sys.executable, "-c", "import time; time.sleep(2)"],
                timeout_seconds=0.05,
            ),
            CancellationToken(),
        )

        assert result.status == "timed_out"
        assert result.exit_code is not None

    @pytest.mark.asyncio
    async def test_cancellation_kills_process_group_and_propagates(self, tmp_path: Path):
        _, sandbox, _ = make_tools(copy_fixture_repository(tmp_path))
        cancellation = CancellationToken()
        task = asyncio.create_task(
            sandbox.run(
                CommandSpec(
                    argv=[sys.executable, "-c", "import time; time.sleep(2)"],
                    timeout_seconds=5,
                ),
                cancellation,
            )
        )
        await asyncio.sleep(0.05)
        cancellation.cancel("fixture cancellation")

        with pytest.raises(RunCancelledError, match="fixture cancellation"):
            await task

    @pytest.mark.asyncio
    async def test_non_allowlisted_executable_is_rejected_before_start(self, tmp_path: Path):
        workspace = Workspace(copy_fixture_repository(tmp_path))
        sandbox = ShellSandbox(workspace, allowed_executables=(sys.executable,))

        with pytest.raises(RuntimeError, match="not allowlisted"):
            await sandbox.run(
                CommandSpec(argv=["/bin/echo", "not allowed"]), CancellationToken()
            )

    @pytest.mark.asyncio
    async def test_command_profile_rejects_unapproved_python_mode(self, tmp_path: Path):
        workspace = Workspace(copy_fixture_repository(tmp_path))
        sandbox = ShellSandbox(
            workspace,
            allowed_executables=(sys.executable,),
            allowed_argument_prefixes={Path(sys.executable): (("-m", "pytest"),)},
        )

        with pytest.raises(RuntimeError, match="command profile"):
            await sandbox.run(
                CommandSpec(argv=[sys.executable, "-c", "print('blocked')"]),
                CancellationToken(),
            )


class TestStructuredRunners:
    @pytest.mark.asyncio
    async def test_runner_rejects_target_outside_workspace(self, tmp_path: Path):
        _, _, runner = make_tools(copy_fixture_repository(tmp_path))

        with pytest.raises(WorkspaceToolError):
            await runner.pytest(
                action_id="outside-target",
                targets=("../outside.py",),
                cancellation=CancellationToken(),
            )

    @pytest.mark.asyncio
    async def test_pytest_failure_is_a_retryable_structured_observation(self, tmp_path: Path):
        root = copy_fixture_repository(tmp_path)
        workspace, _, runner = make_tools(root)
        workspace.apply_patch(initial_lowercase_patch())

        observation = await runner.pytest(
            action_id="pytest-failure",
            targets=("verification/spec_usernames.py",),
            cancellation=CancellationToken(),
        )

        assert observation.success is False
        assert observation.error_class == "test_failure"
        assert observation.retryable is True
        assert len(observation.data["failures"]) == 1
        assert "rejects_empty_values" in observation.data["failures"][0]["node_id"]
        assert observation.artifacts[0].sha256

    @pytest.mark.asyncio
    async def test_ruff_failure_contains_machine_readable_diagnostics(self, tmp_path: Path):
        root = copy_fixture_repository(tmp_path)
        _, _, runner = make_tools(root)
        if runner.ruff_executable is None:
            pytest.skip("Ruff executable is unavailable")
        (root / "lint_failure.py").write_text("import os\n", encoding="utf-8")

        observation = await runner.ruff(
            action_id="ruff-failure",
            targets=("lint_failure.py",),
            cancellation=CancellationToken(),
        )

        assert observation.error_class == "lint_failure"
        assert observation.data["diagnostics"][0]["code"] == "F401"


class TestCodeIterationAcceptance:
    @pytest.mark.asyncio
    async def test_full_discover_patch_fail_evidence_repair_pass_path(self, tmp_path: Path):
        root = copy_fixture_repository(tmp_path)
        workspace, _, runner = make_tools(root)

        discovery = workspace.search("def normalize_username", include=("*.py",))
        source_before = workspace.read(discovery[0].path).content
        result = await CodeIterationLoop(
            workspace, runner, max_repairs=1
        ).run(
            initial_patch=initial_lowercase_patch(),
            repair_strategy=EmptyUsernameRepair(),
            pytest_targets=("verification/spec_usernames.py",),
        )

        assert source_before == """\
\"\"\"Small deliberately defective module used only by M3 acceptance tests.\"\"\"


def normalize_username(value: str) -> str:
    return value.strip()
"""
        assert result.status == "completed"
        assert [item["success"] for item in result.observations] == [False, True]
        assert result.observations[0]["error_class"] == "test_failure"
        assert result.repair_attempts == 1
        assert len(result.patches) == 2
        final_source = workspace.read("sample_project/usernames.py").content
        assert "raise ValueError" in final_source
        assert "COMSOL" not in final_source
        assert "bearing" not in final_source.lower()

    @pytest.mark.asyncio
    async def test_exhausted_loop_restores_original_file_checkpoint(self, tmp_path: Path):
        root = copy_fixture_repository(tmp_path)
        workspace, _, runner = make_tools(root)
        original = workspace.read("sample_project/usernames.py").content

        result = await CodeIterationLoop(workspace, runner, max_repairs=0).run(
            initial_patch=initial_lowercase_patch(),
            repair_strategy=NoRepair(),
            pytest_targets=("verification/spec_usernames.py",),
        )

        assert result.status == "failed"
        assert result.rolled_back is True
        assert "repair budget exhausted" in result.failure_reason
        assert workspace.read("sample_project/usernames.py").content == original

    @pytest.mark.asyncio
    async def test_builtin_executor_normalizes_workspace_policy_failure(self, tmp_path: Path):
        workspace, sandbox, runner = make_tools(copy_fixture_repository(tmp_path))
        executor = CodeToolExecutor(workspace, sandbox, runner)

        observation = await executor.execute(
            Action(tool="workspace.read", arguments={"path": "../outside.py"}),
            CancellationToken(),
        )

        assert observation.success is False
        assert observation.error_class == "path_outside_workspace"
        assert observation.retryable is False
