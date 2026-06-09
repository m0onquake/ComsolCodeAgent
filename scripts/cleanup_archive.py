"""Find or remove stale simulation artifact index rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.memory.archive_cleanup import cleanup_missing_artifact_indexes
from comsol_agent.memory.archive_store import ArchiveStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup stale COMSOL Agent archive indexes.")
    parser.add_argument("--kind", default=None, help="Optional artifact kind filter.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true", help="Delete stale index rows. Default is dry-run.")
    parser.add_argument("--archive-path", default=None)
    args = parser.parse_args()

    archive_path = Path(args.archive_path).expanduser() if args.archive_path else _default_archive_path()
    archive = ArchiveStore(archive_path)
    result = cleanup_missing_artifact_indexes(
        archive,
        kind=args.kind,
        limit=args.limit,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result.get("success"):
        raise SystemExit(1)


def _default_archive_path() -> Path:
    return Path.home() / ".comsol_agent" / "archive" / "archive.sqlite3"


if __name__ == "__main__":
    main()
