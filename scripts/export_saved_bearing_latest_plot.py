"""Export the final parametric solution from a solved bearing MPH as a native COMSOL plot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.cli.config import load_config
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.tools.comsol.model_ops import comsol_close_model, comsol_load_model
from scripts.run_agent_3d_bearing_full_demo import _export_native_3d_stage_volume_plot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mph")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--stage-name", default="physical_all12_final_0p101n")
    parser.add_argument("--solution-level", type=int, default=4)
    parser.add_argument("--cores", type=int, default=1)
    args = parser.parse_args()

    config = load_config()
    client = COMSOLClient.get_instance()
    model_name = None
    result: dict[str, object]
    try:
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        loaded = comsol_load_model(args.mph)
        if not loaded.get("success"):
            raise RuntimeError(str(loaded.get("error") or "failed to load MPH"))
        model_name = str(loaded["model_name"])
        result = _export_native_3d_stage_volume_plot(
            model_name,
            stage_name=args.stage_name,
            output_dir=Path(args.output_dir),
            solution_level=args.solution_level,
        )
    except Exception as exc:
        result = {"success": False, "error": str(exc)}
    finally:
        if model_name:
            comsol_close_model(model_name, save=False)
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
