"""Probe local COMSOL/MPh runtime readiness.

Default mode is non-invasive: it checks configuration, executable paths,
MPh importability, and MPh backend discovery without starting COMSOL.

Use ``--start`` to start a COMSOL session. Use ``--create-smoke`` together
with ``--start`` to create, save, and remove a tiny empty model.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.cli.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe local COMSOL/MPh runtime readiness.")
    parser.add_argument("--start", action="store_true", help="Start a COMSOL session via MPh.")
    parser.add_argument(
        "--create-smoke",
        action="store_true",
        help="Create and save a minimal empty model. Implies --start.",
    )
    parser.add_argument("--cores", type=int, default=None, help="Optional COMSOL core limit.")
    parser.add_argument("--version", default=None, help="Override configured COMSOL version.")
    parser.add_argument(
        "--output-dir",
        default="runtime_smoke",
        help="Directory for smoke-test artifacts when --create-smoke is used.",
    )
    args = parser.parse_args()
    if args.create_smoke:
        args.start = True

    config = load_config()
    version = args.version or config.comsol.version
    executable_path = config.comsol.executable_path

    print("COMSOL Agent runtime probe")
    print(f"Python: {sys.executable}")
    print(f"Configured COMSOL version: {version or '(auto)'}")
    print(f"Configured executable: {executable_path or '(auto)'}")

    if executable_path:
        path = Path(executable_path).expanduser()
        print(f"Executable exists: {path.exists()}")
        print(f"Executable is file: {path.is_file()}")
        if not path.exists():
            raise SystemExit(2)

    try:
        import mph
        import mph.discovery as discovery
    except ImportError as exc:
        print(f"MPh import failed: {exc}")
        raise SystemExit(2) from exc

    print(f"MPh version: {getattr(mph, '__version__', 'unknown')}")
    backends = discovery.find_backends()
    print(f"Discovered COMSOL backends: {len(backends)}")
    for backend in backends:
        print(_format_backend(backend))

    if version and not any(str(backend.get("name")) == str(version) for backend in backends):
        print(f"Configured version {version!r} was not found by MPh discovery.")
        raise SystemExit(2)

    if not args.start:
        print("Probe complete. COMSOL was not started. Use --start for runtime validation.")
        return

    print("Starting COMSOL via MPh...")
    client = mph.start(cores=args.cores, version=version)
    print(f"COMSOL client started: version={getattr(client, 'version', 'unknown')}")

    if args.create_smoke:
        _run_create_smoke(client, Path(args.output_dir))

    try:
        client.disconnect()
        print("COMSOL client disconnected.")
    except Exception as exc:
        print(f"Warning: failed to disconnect cleanly: {exc}")


def _format_backend(backend: dict[str, Any]) -> str:
    root = backend.get("root")
    jvm = backend.get("jvm")
    server = backend.get("server")
    return (
        f"- {backend.get('name')} "
        f"build={backend.get('build')} "
        f"root={root} "
        f"jvm_exists={Path(jvm).exists() if jvm else False} "
        f"server={server}"
    )


def _run_create_smoke(client: Any, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "comsol_agent_smoke.mph"
    print("Creating smoke model...")
    model = client.create("comsol_agent_smoke")
    model.save(model_path)
    print(f"Smoke model saved: {model_path.resolve()}")
    try:
        client.remove(model)
        print("Smoke model removed from COMSOL client.")
    except Exception as exc:
        print(f"Warning: failed to remove smoke model from client: {exc}")


if __name__ == "__main__":
    main()
