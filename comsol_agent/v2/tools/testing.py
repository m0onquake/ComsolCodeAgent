"""pytest and Ruff runners that normalize process evidence into Observations."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

from comsol_agent.v2.contracts import ArtifactRef, Observation, SourceRef
from comsol_agent.v2.kernel import CancellationToken

from .models import CommandSpec, SandboxStatus, TestFailure
from .sandbox import ShellSandbox


class TestRunner:
    __test__ = False

    def __init__(
        self,
        sandbox: ShellSandbox,
        *,
        python_executable: str | Path = sys.executable,
        ruff_executable: str | Path | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.python_executable = str(Path(python_executable).resolve(strict=True))
        self.ruff_executable = (
            str(Path(ruff_executable).resolve(strict=True)) if ruff_executable else None
        )

    async def pytest(
        self,
        *,
        action_id: str,
        targets: tuple[str, ...] = (),
        extra_args: tuple[str, ...] = (),
        timeout_seconds: float = 120.0,
        cancellation: CancellationToken,
    ) -> Observation:
        self._validate_targets(targets)
        self._validate_extra_args(extra_args)
        report_relative = f".v2-artifacts/pytest-{uuid4().hex}.xml"
        report_path = self.sandbox.workspace.root / report_relative
        report_path.parent.mkdir(parents=True, exist_ok=True)
        result = await self.sandbox.run(
            CommandSpec(
                argv=[
                    self.python_executable,
                    "-m",
                    "pytest",
                    *targets,
                    "-q",
                    f"--junitxml={report_relative}",
                    *extra_args,
                ],
                timeout_seconds=timeout_seconds,
            ),
            cancellation,
        )
        failures = self._parse_pytest_report(report_path) if report_path.exists() else []
        artifact = self._artifact(report_path, "application/xml") if report_path.exists() else None
        success = result.status == SandboxStatus.COMPLETED and result.exit_code == 0
        if result.status == SandboxStatus.TIMED_OUT:
            error_class = "test_timeout"
            status = "timed_out"
        elif result.status == SandboxStatus.OUTPUT_LIMIT:
            error_class = "test_output_limit"
            status = "output_limit"
        elif result.exit_code == 1:
            error_class = "test_failure"
            status = "failed"
        elif result.exit_code not in (0, 1):
            error_class = "test_execution_error"
            status = "error"
        else:
            error_class = None
            status = "passed"
        return Observation(
            action_id=action_id,
            success=success,
            status=status,
            stage="test",
            data={
                "runner": "pytest",
                "exit_code": result.exit_code,
                "failures": [failure.model_dump(mode="json") for failure in failures],
                "stdout": result.stdout,
                "stderr": result.stderr,
                "targets": list(targets),
            },
            artifacts=[artifact] if artifact else [],
            error_class=error_class,
            exception_type=None if success else "PytestFailure",
            location=failures[0].location if failures else None,
            retryable=error_class == "test_failure",
            duration_ms=result.duration_ms,
            source=SourceRef(kind="test_runner", identifier="pytest", version="1.0"),
        )

    async def ruff(
        self,
        *,
        action_id: str,
        targets: tuple[str, ...] = (".",),
        extra_args: tuple[str, ...] = (),
        timeout_seconds: float = 120.0,
        cancellation: CancellationToken,
    ) -> Observation:
        if self.ruff_executable is None:
            raise ValueError("Ruff executable was not configured")
        self._validate_targets(targets)
        self._validate_extra_args(extra_args)
        result = await self.sandbox.run(
            CommandSpec(
                argv=[
                    self.ruff_executable,
                    "check",
                    *targets,
                    "--output-format=json",
                    *extra_args,
                ],
                timeout_seconds=timeout_seconds,
            ),
            cancellation,
        )
        diagnostics: list[dict] = []
        if result.stdout.strip():
            try:
                parsed = json.loads(result.stdout)
                if isinstance(parsed, list):
                    diagnostics = parsed
            except json.JSONDecodeError:
                diagnostics = []
        success = result.status == SandboxStatus.COMPLETED and result.exit_code == 0
        if result.status == SandboxStatus.TIMED_OUT:
            error_class = "lint_timeout"
            status = "timed_out"
        elif result.status == SandboxStatus.OUTPUT_LIMIT:
            error_class = "lint_output_limit"
            status = "output_limit"
        elif result.exit_code == 1:
            error_class = "lint_failure"
            status = "failed"
        elif result.exit_code not in (0, 1):
            error_class = "lint_execution_error"
            status = "error"
        else:
            error_class = None
            status = "passed"
        location = None
        if diagnostics:
            first = diagnostics[0]
            location = f"{first.get('filename')}:{first.get('location', {}).get('row')}"
        return Observation(
            action_id=action_id,
            success=success,
            status=status,
            stage="test",
            data={
                "runner": "ruff",
                "exit_code": result.exit_code,
                "diagnostics": diagnostics,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "targets": list(targets),
            },
            error_class=error_class,
            exception_type=None if success else "RuffFailure",
            location=location,
            retryable=error_class == "lint_failure",
            duration_ms=result.duration_ms,
            source=SourceRef(kind="test_runner", identifier="ruff", version="1.0"),
        )

    @staticmethod
    def _parse_pytest_report(report_path: Path) -> list[TestFailure]:
        try:
            root = ET.parse(report_path).getroot()
        except (ET.ParseError, OSError):
            return []
        failures: list[TestFailure] = []
        for testcase in root.iter("testcase"):
            outcome = testcase.find("failure")
            kind = "failure"
            if outcome is None:
                outcome = testcase.find("error")
                kind = "error"
            if outcome is None:
                continue
            classname = testcase.attrib.get("classname", "")
            name = testcase.attrib.get("name", "unknown")
            node_id = f"{classname}::{name}" if classname else name
            detail = outcome.text or ""
            location_match = re.search(r"([^\s:]+\.py):(\d+)", detail)
            failures.append(
                TestFailure(
                    node_id=node_id,
                    message=outcome.attrib.get("message", detail.splitlines()[0] if detail else ""),
                    detail=detail,
                    location=(
                        f"{location_match.group(1)}:{location_match.group(2)}"
                        if location_match
                        else None
                    ),
                    kind=kind,
                )
            )
        return failures

    @staticmethod
    def _artifact(path: Path, media_type: str) -> ArtifactRef:
        return ArtifactRef(
            uri=path.as_uri(),
            media_type=media_type,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            source=SourceRef(kind="test_runner", identifier="pytest", version="1.0"),
        )

    def _validate_targets(self, targets: tuple[str, ...]) -> None:
        for target in targets:
            path_part = target.split("::", maxsplit=1)[0]
            if not path_part or path_part.startswith("-"):
                raise ValueError(f"invalid test target: {target}")
            self.sandbox.workspace.resolve(path_part)

    @staticmethod
    def _validate_extra_args(extra_args: tuple[str, ...]) -> None:
        forbidden = (
            "--basetemp",
            "--config",
            "--confcutdir",
            "--junitxml",
            "--output-file",
            "--rootdir",
        )
        for argument in extra_args:
            if Path(argument).is_absolute() or ".." in Path(argument).parts:
                raise ValueError(f"extra argument contains an external path: {argument}")
            if argument.startswith(forbidden):
                raise ValueError(f"extra argument overrides sandbox-owned output: {argument}")
