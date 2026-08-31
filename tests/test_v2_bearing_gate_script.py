"""Process-containment tests for the real COMSOL bearing gate wrapper."""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.run_v2_bearing_gate import _run_bounded_process_group
from scripts.run_v2_m9_followup_gate import _compact_event, _compact_snapshot


def test_bounded_gate_terminates_descendant_processes_on_timeout(tmp_path: Path) -> None:
    terminated = tmp_path / "descendant-terminated.txt"
    child_code = (
        "import pathlib,signal,time; "
        f"marker=pathlib.Path({str(terminated)!r}); "
        "signal.signal(signal.SIGTERM, lambda *_: "
        "(marker.write_text('terminated', encoding='utf-8'), raise_system_exit())); "
        "time.sleep(60)"
    )
    # A named function is needed because Python lambdas cannot contain `raise`.
    child_code = "def raise_system_exit():\n raise SystemExit(0)\n" + child_code
    parent_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "time.sleep(60)"
    )

    result, timed_out = _run_bounded_process_group(
        [sys.executable, "-c", parent_code],
        cwd=tmp_path,
        timeout_seconds=0.5,
    )

    assert timed_out is True
    assert result.returncode != 0
    assert terminated.read_text(encoding="utf-8") == "terminated"


def test_followup_evidence_compacts_failure_and_gate_payloads() -> None:
    huge = "x" * 10_000
    event = _compact_event(
        {
            "kind": "failure",
            "data": {"error_class": "budget", "message": "exhausted", "details": huge},
        }
    )
    snapshot = _compact_snapshot(
        {
            "gates": {
                "physical_audit": {
                    "state": "passed",
                    "evidence": huge,
                    "checks": [{"name": "balance", "passed": True, "actual": huge}],
                }
            },
            "failure": {"code": "BUDGET", "message": "exhausted", "details": huge},
        }
    )

    assert event["data"] == {"error_class": "budget", "message": "exhausted"}
    assert snapshot["failure"] == {"code": "BUDGET", "message": "exhausted"}
    assert snapshot["gates"]["physical_audit"]["checks"] == [
        {"name": "balance", "passed": True}
    ]
    assert huge not in repr(snapshot)
