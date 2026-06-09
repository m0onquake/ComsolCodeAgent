"""Export the COMSOL Agent archive index as JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.memory.archive_export import export_archive_bundle
from comsol_agent.memory.archive_store import ArchiveStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Export COMSOL Agent archive records.")
    parser.add_argument("--output", default=None, help="Output JSON path.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--include-timelines", action="store_true")
    parser.add_argument("--max-events", type=int, default=50)
    parser.add_argument("--archive-path", default=None)
    parser.add_argument("--session-dir", default=None)
    args = parser.parse_args()

    archive_path = Path(args.archive_path).expanduser() if args.archive_path else _default_archive_path()
    session_dir = Path(args.session_dir).expanduser() if args.session_dir else _default_session_dir()
    archive = ArchiveStore(archive_path)
    result = export_archive_bundle(
        archive,
        output_path=args.output,
        session_dir=session_dir,
        limit=args.limit,
        include_timelines=args.include_timelines,
        max_events=args.max_events,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result.get("success"):
        raise SystemExit(1)


def _default_archive_path() -> Path:
    return Path.home() / ".comsol_agent" / "archive" / "archive.sqlite3"


def _default_session_dir() -> Path:
    return Path.home() / ".comsol_agent" / "sessions"


if __name__ == "__main__":
    main()
