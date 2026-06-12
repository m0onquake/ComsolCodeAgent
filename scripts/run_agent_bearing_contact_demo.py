"""Run a reproducible agent demo for the bearing-contact default case."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comsol_agent.agent.loop import AgentLoop
from comsol_agent.agent.tools_bootstrap import register_all_tools
from comsol_agent.agent.tool_registry import clear as clear_tools
from comsol_agent.cli.config import get_config_dir, load_config
from comsol_agent.llm.router import create_provider
from comsol_agent.memory.archive_store import ArchiveStore
from comsol_agent.simulation.skills import seed_builtin_templates
from comsol_agent.tools.comsol.client import COMSOLClient


@dataclass(frozen=True)
class DemoPrompt:
    """One reproducible bearing-contact prompt and validation gates."""

    name: str
    prompt: str
    required_tools: tuple[str, ...]
    successful_tools: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "prompt": self.prompt,
            "required_tools": list(self.required_tools),
            "successful_tools": list(self.successful_tools),
        }


def build_bearing_contact_prompts(
    *,
    archive_path: str,
    artifact_root: str,
    report_dir: str,
    template_name: str,
    model_name: str,
    run_id: str = "<template_execution_run_id>",
) -> list[DemoPrompt]:
    """Build prompt fixtures for a bearing-contact agent workflow."""
    artifact_dir = str(Path(artifact_root) / "template_runs")
    stress_plot = str(Path(artifact_root) / "bearing_contact_von_mises.png")
    package_dir = str(Path(artifact_root) / "result_packages")
    return [
        DemoPrompt(
            name="bearing_contact_default_run",
            prompt=(
                "A user asks: build a realistic ball-bearing contact simulation, but "
                "only says 'make a bearing model and show stress results'. Treat this "
                "as a quick default demo: use the built-in defaults instead of asking "
                "follow-up questions, but clearly list the assumptions. Use only this "
                "deterministic tool chain, in this order: simulation_plan_bearing_contact, "
                "simulation_search_templates, simulation_read_template, "
                "simulation_validate_template, simulation_run_template, comsol_solve, "
                "comsol_evaluate, comsol_evaluate, comsol_plot, "
                "simulation_export_bearing_contact_package, comsol_close_model. "
                "Call simulation_plan_bearing_contact with allow_defaults=true first, and use "
                "its assumptions/resolved_params in the final answer. Do not call file tools, local-doc tools, "
                "simulation_save_template, comsol_execute_java, or comsol_get_model_summary. "
                f"Search for, read, and validate the exact template {template_name!r}; every "
                f"simulation_* template call must include archive_path={archive_path!r}. "
                f"Run it on a newly created COMSOL model named {model_name!r}. For "
                "simulation_run_template use close_model=false, "
                "artifact_name='agent_bearing_contact_default', "
                f"artifact_dir={artifact_dir!r}, and archive_path={archive_path!r}. "
                "After the template run succeeds, call comsol_solve without study_name, "
                "evaluate 'solid.mises' and 'contact_pressure_guess', export a stress image "
                f"with comsol_plot to {stress_plot!r}, export a bearing-contact package "
                "with simulation_export_bearing_contact_package using "
                f"output_dir={package_dir!r}, package_name='agent_bearing_contact_package', "
                f"archive_path={archive_path!r}, and template_run_id from simulation_run_template, "
                "then close the model without saving. Report the template_execution artifact "
                "run_id, template JSON path, package JSON/Markdown/model paths, plot path, "
                "default bearing dimensions, radial load, contact assumptions, and stress/contact summary."
            ),
            required_tools=(
                "simulation_plan_bearing_contact",
                "simulation_search_templates",
                "simulation_read_template",
                "simulation_validate_template",
                "simulation_run_template",
                "comsol_solve",
                "comsol_evaluate",
                "comsol_plot",
                "simulation_export_bearing_contact_package",
                "comsol_close_model",
            ),
            successful_tools=(
                "simulation_plan_bearing_contact",
                "simulation_run_template",
                "comsol_solve",
                "comsol_evaluate",
                "comsol_plot",
                "simulation_export_bearing_contact_package",
                "comsol_close_model",
            ),
        ),
        DemoPrompt(
            name="bearing_contact_artifact_report",
            prompt=(
                f"Inspect the archived bearing contact template execution {run_id!r} "
                "with simulation_read_artifact. Then export an HTML template execution "
                "report using simulation_export_artifact_report with kind='template_execution', "
                "query='agent_bearing_contact_default', "
                f"output_dir={report_dir!r}, report_name='agent_bearing_contact_report', "
                f"archive_path={archive_path!r}. Summarize whether the workflow reached "
                "model setup, execution, artifact archival, and what would be needed for "
                "a production 3D multi-ball contact solve."
            ),
            required_tools=("simulation_read_artifact", "simulation_export_artifact_report"),
            successful_tools=("simulation_read_artifact", "simulation_export_artifact_report"),
        ),
    ]


async def run_bearing_contact_demo(args: argparse.Namespace) -> int:
    """Run the bearing-contact demo against the configured LLM and COMSOL runtime."""
    artifact_root = Path(args.artifact_root)
    report_dir = Path(args.report_dir)
    archive_path = Path(args.archive_path)
    artifact_root.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    config = load_config()
    config.agent.max_tool_iterations = args.max_tool_iterations
    clear_tools()
    register_all_tools()
    archive_store = ArchiveStore(archive_path)
    seed_builtin_templates(archive_store)
    seed_builtin_templates(ArchiveStore(get_config_dir() / "archive" / "archive.sqlite3"))

    provider = create_provider(
        config.llm.provider,
        model=config.llm.model,
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
    )
    client = COMSOLClient.get_instance()
    tool_events: list[tuple[str, dict[str, Any]]] = []
    try:
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        agent = AgentLoop(
            llm_provider=provider,
            config=config,
            on_tool_call=lambda name, call_args: tool_events.append((name, call_args)),
            archive_store=archive_store,
        )

        first_prompt = build_bearing_contact_prompts(
            archive_path=str(archive_path),
            artifact_root=str(artifact_root),
            report_dir=str(report_dir),
            template_name=args.template_name,
            model_name=args.model_name,
        )[0]
        summaries = [await _run_prompt(agent, first_prompt, tool_events)]
        run_id = _latest_artifact_run_id(
            summaries[-1]["new_tool_results"],
            preferred_tool="simulation_run_template",
        )
        if not run_id:
            print("Could not identify a bearing contact template_execution run_id.")
            return 1

        report_prompt = build_bearing_contact_prompts(
            archive_path=str(archive_path),
            artifact_root=str(artifact_root),
            report_dir=str(report_dir),
            template_name=args.template_name,
            model_name=args.model_name,
            run_id=run_id,
        )[1]
        summaries.append(await _run_prompt(agent, report_prompt, tool_events))

        failures = [summary for summary in summaries if not summary["success"]]
        print("Bearing-contact demo summary:")
        print(json.dumps(_compact_summaries(summaries), ensure_ascii=False, indent=2, default=str))
        if failures:
            print(f"Failed demo stages: {[failure['name'] for failure in failures]}")
            return 1
        print("Agent bearing-contact demo succeeded.")
        return 0
    finally:
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


async def _run_prompt(
    agent: AgentLoop,
    prompt: DemoPrompt,
    tool_events: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    previous_event_count = len(tool_events)
    previous_tool_result_count = len(_tool_results(agent.state.messages))
    print(f"\n=== Demo: {prompt.name} ===")
    print(prompt.prompt)
    response = await agent.run(prompt.prompt)
    print("Agent response:")
    print(response)

    new_events = tool_events[previous_event_count:]
    new_tool_results = _tool_results(agent.state.messages)[previous_tool_result_count:]
    observed_tools = [name for name, _ in new_events]
    successful_tools = {
        result["name"]
        for result in new_tool_results
        if result["payload"].get("success") is True
    }
    missing_calls = [name for name in prompt.required_tools if name not in observed_tools]
    missing_successes = [name for name in prompt.successful_tools if name not in successful_tools]
    success = not missing_calls and not missing_successes
    if missing_calls:
        print(f"Missing required tool calls: {missing_calls}")
    if missing_successes:
        print(f"Missing successful tool results: {missing_successes}")

    return {
        "name": prompt.name,
        "success": success,
        "response": response,
        "observed_tools": observed_tools,
        "missing_calls": missing_calls,
        "missing_successes": missing_successes,
        "new_tool_results": new_tool_results,
    }


def _tool_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        try:
            payload = json.loads(message.get("content") or "{}")
        except json.JSONDecodeError as exc:
            payload = {"success": False, "error": str(exc)}
        results.append({"name": message.get("name"), "payload": payload})
    return results


def _latest_artifact_run_id(tool_results: list[dict[str, Any]], *, preferred_tool: str) -> str | None:
    for result in reversed(tool_results):
        if result["name"] != preferred_tool:
            continue
        artifacts = result["payload"].get("artifacts") or {}
        if isinstance(artifacts, dict) and artifacts.get("run_id"):
            return str(artifacts["run_id"])
    for result in reversed(tool_results):
        artifacts = result["payload"].get("artifacts") or {}
        if isinstance(artifacts, dict) and artifacts.get("run_id"):
            return str(artifacts["run_id"])
    return None


def _compact_summaries(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = []
    for summary in summaries:
        compact.append({
            "name": summary["name"],
            "success": summary["success"],
            "observed_tools": summary["observed_tools"],
            "missing_calls": summary["missing_calls"],
            "missing_successes": summary["missing_successes"],
            "artifacts": [
                _compact_tool_artifact(result)
                for result in summary["new_tool_results"]
                if _has_compact_artifact(result)
            ],
        })
    return compact


def _has_compact_artifact(result: dict[str, Any]) -> bool:
    payload = result["payload"]
    return bool(payload.get("artifacts") or payload.get("artifact") or payload.get("report") or payload.get("run_id"))


def _compact_tool_artifact(result: dict[str, Any]) -> dict[str, Any]:
    payload = result["payload"]
    report = payload.get("report") or {}
    artifact = payload.get("artifact") or {}
    artifacts = payload.get("artifacts")
    item: dict[str, Any] = {
        "tool": result["name"],
        "report_id": report.get("report_id"),
        "path": report.get("path"),
        "html_path": report.get("html_path"),
    }
    if isinstance(artifacts, dict):
        item["run_id"] = artifacts.get("run_id")
    if isinstance(artifact, dict) and artifact.get("run_id"):
        item["run_id"] = artifact.get("run_id")
    if payload.get("run_id"):
        item["run_id"] = payload.get("run_id")
        item["path"] = payload.get("markdown_path") or payload.get("json_path") or item.get("path")
        item["model_path"] = payload.get("model_path")
        item["plot_path"] = payload.get("plot_path")
    return {key: value for key, value in item.items() if value not in (None, [], {})}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an agent bearing-contact demo.")
    parser.add_argument("--cores", type=int, default=1, help="COMSOL core limit.")
    parser.add_argument("--template-name", default="bearing_contact_pair_seed")
    parser.add_argument("--model-name", default="agent_bearing_contact_model")
    parser.add_argument("--artifact-root", default="runtime_smoke/bearing_contact_demo")
    parser.add_argument("--report-dir", default="runtime_smoke/bearing_contact_demo/reports")
    parser.add_argument("--archive-path", default="runtime_smoke/bearing_contact_demo.sqlite3")
    parser.add_argument("--max-tool-iterations", type=int, default=20)
    parser.add_argument(
        "--print-prompts",
        action="store_true",
        help="Print reproducible prompt fixtures and exit without calling LLM/COMSOL.",
    )
    args = parser.parse_args()

    if args.print_prompts:
        prompts = build_bearing_contact_prompts(
            archive_path=args.archive_path,
            artifact_root=args.artifact_root,
            report_dir=args.report_dir,
            template_name=args.template_name,
            model_name=args.model_name,
        )
        print(json.dumps([prompt.to_dict() for prompt in prompts], ensure_ascii=False, indent=2))
        return

    raise SystemExit(asyncio.run(run_bearing_contact_demo(args)))


if __name__ == "__main__":
    main()
