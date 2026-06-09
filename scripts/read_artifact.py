"""Read a compact preview of an archived simulation artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.tools.simulation import simulation_read_artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Read an archived simulation artifact preview.")
    parser.add_argument("run_id")
    parser.add_argument("--max-lines", type=int, default=80)
    parser.add_argument("--archive-path", default=None)
    args = parser.parse_args()

    result = simulation_read_artifact(
        run_id=args.run_id,
        max_lines=args.max_lines,
        archive_path=args.archive_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result.get("success"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
