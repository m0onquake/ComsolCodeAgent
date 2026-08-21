"""Backfill V2 RunManifest JSON files into a quarantined memory snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path

from comsol_agent.v2.memory import JsonMemoryRepository, ManifestMigrator, MemoryGovernance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--agent-version", required=True)
    parser.add_argument("manifests", nargs="+", type=Path)
    arguments = parser.parse_args()

    repository = JsonMemoryRepository(arguments.store)
    report = ManifestMigrator(
        MemoryGovernance(repository), agent_version=arguments.agent_version
    ).migrate(arguments.manifests)
    print(report.model_dump_json(indent=2))
    return 0 if not report.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
