"""Export a Markdown report for archived COMSOL sweep artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.tools.simulation import simulation_export_artifact_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Export an archived sweep comparison report.")
    parser.add_argument("--run-id", action="append", dest="run_ids", default=None)
    parser.add_argument("--query", default=None, help="Archive search query when run IDs are omitted.")
    parser.add_argument("--metric", default="mean", help="Metric column to rank.")
    parser.add_argument("--expression", default=None, help="Optional expression filter.")
    parser.add_argument("--direction", choices=["max", "min"], default="max")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--report-name", default=None)
    parser.add_argument("--title", default=None)
    parser.add_argument("--format", choices=["markdown", "html", "both"], default="markdown")
    parser.add_argument("--archive-path", default=None)
    args = parser.parse_args()

    result = simulation_export_artifact_report(
        run_ids=args.run_ids,
        query=args.query,
        metric=args.metric,
        expression=args.expression,
        direction=args.direction,
        limit=args.limit,
        output_dir=args.output_dir,
        report_name=args.report_name,
        title=args.title,
        output_format=args.format,
        archive_path=args.archive_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result.get("success"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
