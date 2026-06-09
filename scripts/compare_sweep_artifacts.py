"""Compare archived COMSOL sweep artifacts from the SQLite archive."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.tools.simulation import simulation_compare_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare archived sweep artifacts.")
    parser.add_argument("--run-id", action="append", dest="run_ids", default=None)
    parser.add_argument("--query", default=None, help="Archive search query when run IDs are omitted.")
    parser.add_argument("--metric", default="mean", help="Metric column to rank.")
    parser.add_argument("--expression", default=None, help="Optional expression filter.")
    parser.add_argument("--direction", choices=["max", "min"], default="max")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--archive-path", default=None)
    args = parser.parse_args()

    result = simulation_compare_artifacts(
        run_ids=args.run_ids,
        query=args.query,
        metric=args.metric,
        expression=args.expression,
        direction=args.direction,
        limit=args.limit,
        archive_path=args.archive_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result.get("success"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
