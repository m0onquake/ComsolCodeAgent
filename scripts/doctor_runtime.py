"""Run non-invasive COMSOL Agent runtime diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.diagnostics import run_deep_doctor, run_doctor


def main() -> None:
    parser = argparse.ArgumentParser(description="Run COMSOL Agent runtime diagnostics.")
    parser.add_argument("--json", action="store_true", help="Print full JSON output.")
    parser.add_argument("--deep", action="store_true", help="Call the configured LLM API and start COMSOL.")
    parser.add_argument("--llm-only", action="store_true", help="Only run the real LLM API check.")
    parser.add_argument("--comsol-only", action="store_true", help="Only run the real COMSOL startup check.")
    parser.add_argument("--cores", type=int, default=1, help="COMSOL cores for deep startup checks.")
    parser.add_argument("--create-smoke", action="store_true", help="Create/save a tiny COMSOL model during deep COMSOL check.")
    parser.add_argument("--timeout", type=float, default=30.0, help="LLM API timeout in seconds.")
    args = parser.parse_args()

    if args.deep or args.llm_only or args.comsol_only:
        check_llm = args.deep or args.llm_only
        check_comsol = args.deep or args.comsol_only
        result = asyncio.run(
            run_deep_doctor(
                check_llm=check_llm,
                check_comsol=check_comsol,
                comsol_cores=args.cores,
                create_smoke=args.create_smoke,
                timeout_seconds=args.timeout,
            )
        )
    else:
        result = run_doctor()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"COMSOL Agent doctor: {result['status']}")
        for check in result["checks"]:
            print(f"- {check['name']}: {check['status']} — {check['message']}")

    raise SystemExit(0 if result["success"] else 2)


if __name__ == "__main__":
    main()
