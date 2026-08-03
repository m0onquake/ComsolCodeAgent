#!/usr/bin/env python3
"""Run one strict bearing command with a real wall-clock process watchdog."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=15)
        return
    except subprocess.TimeoutExpired:
        pass
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")

    artifact_root = Path(args.artifact_root)
    artifact_root.mkdir(parents=True, exist_ok=True)
    manifest_path = artifact_root / "strict_watchdog_manifest.json"
    log_path = artifact_root / "strict_watchdog_process.log"
    started_epoch = time.time()
    manifest: dict[str, object] = {
        "status": "running",
        "started_at": _now(),
        "timeout_seconds": args.timeout_seconds,
        "model_name": args.model_name,
        "command": command,
        "no_mph_input": not any(str(item).lower().endswith(".mph") for item in command),
        "process_log": str(log_path),
    }
    _write_manifest(manifest_path, manifest)

    with log_path.open("w", encoding="utf-8") as process_log:
        process = subprocess.Popen(
            command,
            stdout=process_log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        manifest["pid"] = process.pid
        _write_manifest(manifest_path, manifest)
        deadline_epoch = started_epoch + args.timeout_seconds
        try:
            while process.poll() is None and time.time() < deadline_epoch:
                time.sleep(min(0.5, max(0.01, deadline_epoch - time.time())))
            if process.poll() is None:
                raise subprocess.TimeoutExpired(command, args.timeout_seconds)
            return_code = int(process.returncode or 0)
            status = "completed" if return_code == 0 else "failed"
        except subprocess.TimeoutExpired:
            status = "timed_out"
            return_code = 124
            _terminate_process_group(process)
        except KeyboardInterrupt:
            status = "interrupted"
            return_code = 130
            _terminate_process_group(process)

    manifest.update(
        {
            "status": status,
            "return_code": return_code,
            "finished_at": _now(),
            "elapsed_seconds": time.time() - started_epoch,
            "timed_out": status == "timed_out",
        }
    )
    _write_manifest(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return int(return_code)


if __name__ == "__main__":
    sys.exit(main())
