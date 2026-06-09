"""List or read archived simulation templates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.memory.archive_store import ArchiveStore
from comsol_agent.simulation.skills import seed_builtin_templates
from comsol_agent.cli.config import load_config
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.tools.simulation import (
    simulation_export_template,
    simulation_list_templates,
    simulation_read_template,
    simulation_run_template,
    simulation_save_template,
    simulation_search_templates,
    simulation_validate_template,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect archived simulation templates.")
    parser.add_argument("--domain", default=None)
    parser.add_argument("--query", default=None, help="Search templates by keyword.")
    parser.add_argument("--show", default=None, help="Read one template by exact name.")
    parser.add_argument("--validate", default=None, help="Validate one archived template by exact name.")
    parser.add_argument("--validate-file", default=None, help="Validate a local Java/API seed file.")
    parser.add_argument("--run", default=None, help="Run one archived template against COMSOL.")
    parser.add_argument("--model-name", default=None, help="Loaded COMSOL model name for --run.")
    parser.add_argument("--create-model-name", default=None, help="Create this COMSOL model before --run.")
    parser.add_argument("--artifact-dir", default=None, help="Artifact output directory for --run.")
    parser.add_argument("--artifact-name", default=None, help="Artifact run-name prefix for --run.")
    parser.add_argument("--no-archive-results", action="store_true", help="Do not index --run artifacts.")
    parser.add_argument("--keep-model", action="store_true", help="Do not close a model created by --run.")
    parser.add_argument("--cores", type=int, default=1, help="COMSOL core limit for --run.")
    parser.add_argument("--version", default=None, help="Override configured COMSOL version for --run.")
    parser.add_argument("--export", default=None, help="Export one template to a .java file.")
    parser.add_argument("--output", default=None, help="Output path for --export.")
    parser.add_argument("--no-header", action="store_true", help="Omit metadata comments for --export.")
    parser.add_argument("--no-overwrite", action="store_true", help="Fail if --export output exists.")
    parser.add_argument("--save", default=None, help="Save/update one template by name.")
    parser.add_argument("--java-file", default=None, help="Java/API code file for --save.")
    parser.add_argument("--params-json", default=None, help="Inline JSON object for --save params.")
    parser.add_argument("--params-file", default=None, help="JSON file for --save params.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--archive-path", default=None)
    parser.add_argument("--seed-builtins", action="store_true", help="Seed built-in templates before listing.")
    args = parser.parse_args()

    archive_path = Path(args.archive_path).expanduser() if args.archive_path else _default_archive_path()
    if args.seed_builtins:
        try:
            seed_builtin_templates(ArchiveStore(archive_path))
        except Exception as exc:
            result = {
                "success": False,
                "error": f"Could not seed built-in templates: {exc}",
                "archive_path": str(archive_path),
            }
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            raise SystemExit(1)

    if args.save:
        if not args.java_file:
            result = {"success": False, "error": "--java-file is required with --save."}
        else:
            try:
                java_code = Path(args.java_file).expanduser().read_text(encoding="utf-8")
                params = _load_params(args.params_json, args.params_file)
            except Exception as exc:
                result = {"success": False, "error": str(exc)}
            else:
                result = simulation_save_template(
                    name=args.save,
                    domain=args.domain,
                    java_code=java_code,
                    params=params,
                    archive_path=str(archive_path),
                )
    elif args.export:
        result = simulation_export_template(
            args.export,
            output_path=args.output,
            include_params_header=not args.no_header,
            overwrite=not args.no_overwrite,
            archive_path=str(archive_path),
        )
    elif args.validate:
        try:
            params = _load_params(args.params_json, args.params_file)
        except Exception as exc:
            result = {"success": False, "error": str(exc)}
        else:
            result = simulation_validate_template(
                name=args.validate,
                params=params or None,
                archive_path=str(archive_path),
            )
    elif args.validate_file:
        try:
            java_code = Path(args.validate_file).expanduser().read_text(encoding="utf-8")
            params = _load_params(args.params_json, args.params_file)
        except Exception as exc:
            result = {"success": False, "error": str(exc)}
        else:
            result = simulation_validate_template(
                name=Path(args.validate_file).stem,
                java_code=java_code,
                params=params,
                archive_path=str(archive_path),
            )
    elif args.run:
        try:
            params = _load_params(args.params_json, args.params_file)
        except Exception as exc:
            result = {"success": False, "error": str(exc)}
        else:
            result = _run_template_with_comsol(
                template_name=args.run,
                params=params or None,
                model_name=args.model_name,
                create_model_name=args.create_model_name,
                close_model=False if args.keep_model else None,
                artifact_dir=args.artifact_dir,
                artifact_name=args.artifact_name,
                archive_results=not args.no_archive_results,
                archive_path=str(archive_path),
                cores=args.cores,
                version=args.version,
            )
    elif args.show:
        result = simulation_read_template(args.show, archive_path=str(archive_path))
    elif args.query:
        result = simulation_search_templates(
            query=args.query,
            domain=args.domain,
            limit=args.limit,
            archive_path=str(archive_path),
        )
    else:
        result = simulation_list_templates(
            domain=args.domain,
            limit=args.limit,
            archive_path=str(archive_path),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result.get("success"):
        raise SystemExit(1)


def _default_archive_path() -> Path:
    return Path.home() / ".comsol_agent" / "archive" / "archive.sqlite3"


def _load_params(params_json: str | None, params_file: str | None) -> dict:
    if params_file:
        return json.loads(Path(params_file).expanduser().read_text(encoding="utf-8"))
    if params_json:
        return json.loads(params_json)
    return {}


def _run_template_with_comsol(
    *,
    template_name: str,
    params: dict | None,
    model_name: str | None,
    create_model_name: str | None,
    close_model: bool | None,
    artifact_dir: str | None,
    artifact_name: str | None,
    archive_results: bool,
    archive_path: str,
    cores: int,
    version: str | None,
) -> dict:
    if sum(bool(value) for value in (model_name, create_model_name)) != 1:
        return {
            "success": False,
            "error": "Provide exactly one of model_name or create_model_name.",
        }
    config = load_config()
    client = COMSOLClient.get_instance()
    try:
        client.start(
            cores=cores,
            version=version or config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        return simulation_run_template(
            name=template_name,
            params=params,
            model_name=model_name,
            create_model_name=create_model_name,
            close_model=close_model,
            artifact_dir=artifact_dir,
            artifact_name=artifact_name,
            archive_results=archive_results,
            archive_path=archive_path,
        )
    finally:
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


if __name__ == "__main__":
    main()
