"""Run reproducible DeepSeek -> AgentLoop -> COMSOL end-to-end demos."""

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
from comsol_agent.cli.config import load_config
from comsol_agent.llm.router import create_provider
from comsol_agent.memory.archive_store import ArchiveStore
from comsol_agent.simulation.skills import seed_builtin_templates
from comsol_agent.tools.comsol.client import COMSOLClient


@dataclass(frozen=True)
class DemoPrompt:
    """One reproducible agent demo prompt and its validation gates."""

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


def build_initial_demo_prompts(
    *,
    archive_path: str,
    artifact_root: str,
    report_dir: str,
    template_name: str,
    template_model_name: str,
    example_name: str,
    parameters: dict[str, list[str]],
    expressions: list[str],
    max_cases: int,
) -> list[DemoPrompt]:
    """Build the first two P5 demo prompts; the inspect prompt is built after run IDs exist."""
    template_artifact_dir = str(Path(artifact_root) / "template_runs")
    sweep_artifact_dir = str(Path(artifact_root) / "sweeps")
    return [
        DemoPrompt(
            name="template_run",
            prompt=(
                "Find the thermal simulation template named or matching "
                f"{template_name!r}, validate it, then run it on a newly created "
                f"COMSOL model named {template_model_name!r}. Use the high-level "
                "template tools: simulation_search_templates, simulation_validate_template, "
                "and simulation_run_template. Persist results with "
                "artifact_name='agent_fullflow_template', "
                f"artifact_dir={template_artifact_dir!r}, archive_path={archive_path!r}. "
                "After the run, report the template_execution artifact run_id and JSON path."
            ),
            required_tools=(
                "simulation_search_templates",
                "simulation_validate_template",
                "simulation_run_template",
            ),
            successful_tools=("simulation_run_template",),
        ),
        DemoPrompt(
            name="sweep_report",
            prompt=(
                "Run a small bounded COMSOL parameter sweep using "
                "simulation_run_parameter_sweep, then export an HTML report using "
                "simulation_export_artifact_report. "
                f"Use example_name={example_name!r}, parameters={parameters!r}, "
                f"expressions={expressions!r}, max_cases={max_cases}, solve=true, "
                "persist_results=true, artifact_name='agent_fullflow_sweep', "
                f"artifact_dir={sweep_artifact_dir!r}, archive_path={archive_path!r}. "
                "After the sweep succeeds, export a report with query='agent_fullflow_sweep', "
                f"output_dir={report_dir!r}, report_name='agent_fullflow_sweep_report', "
                "output_format='html', archive_path set to the same archive. "
                "Summarize the best/worst information from the report or comparison."
            ),
            required_tools=(
                "simulation_run_parameter_sweep",
                "simulation_export_artifact_report",
            ),
            successful_tools=(
                "simulation_run_parameter_sweep",
                "simulation_export_artifact_report",
            ),
        ),
    ]


def build_inspect_prompt(*, archive_path: str, run_id: str) -> DemoPrompt:
    """Build the artifact-inspection prompt once a previous run ID is known."""
    return DemoPrompt(
        name="artifact_inspection",
        prompt=(
            f"Inspect the archived simulation artifact {run_id!r} using "
            "simulation_read_artifact. If needed, first use simulation_search_artifacts "
            "to confirm it exists. Then recommend concrete next simulation steps based "
            "only on the artifact preview and its physics domain; do not introduce "
            "unrelated fluid, structural, or electromagnetic workflows unless the "
            "artifact itself mentions them. Use archive_path="
            f"{archive_path!r} and keep the recommendation concise."
        ),
        required_tools=("simulation_read_artifact",),
        successful_tools=("simulation_read_artifact",),
    )


async def run_fullflow_demo(args: argparse.Namespace) -> int:
    """Run the three P5 demos against the configured LLM and local COMSOL runtime."""
    artifact_root = Path(args.artifact_root)
    report_dir = Path(args.report_dir)
    archive_path = Path(args.archive_path)
    artifact_root.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    config = load_config()
    config.agent.max_tool_iterations = max(config.agent.max_tool_iterations, args.max_tool_iterations)
    clear_tools()
    register_all_tools()
    archive_store = ArchiveStore(archive_path)
    seed_builtin_templates(archive_store)

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

        prompts = build_initial_demo_prompts(
            archive_path=str(archive_path),
            artifact_root=str(artifact_root),
            report_dir=str(report_dir),
            template_name=args.template_name,
            template_model_name=args.template_model_name,
            example_name=args.example_name,
            parameters=_parse_sweep_parameters(args.parameter) or {"L": ["0.5[mm]"]},
            expressions=args.expression or ["T"],
            max_cases=args.max_cases,
        )

        summaries = []
        for prompt in prompts:
            summaries.append(await _run_prompt(agent, prompt, tool_events))

        inspect_run_id = _latest_artifact_run_id(
            summaries[-1]["new_tool_results"],
            preferred_tool="simulation_run_parameter_sweep",
        )
        if not inspect_run_id:
            print("Could not identify a sweep artifact run_id for inspection.")
            return 1

        inspect_prompt = build_inspect_prompt(
            archive_path=str(archive_path),
            run_id=inspect_run_id,
        )
        summaries.append(await _run_prompt(agent, inspect_prompt, tool_events))

        failures = [summary for summary in summaries if not summary["success"]]
        print("Fullflow demo summary:")
        print(json.dumps(_compact_summaries(summaries), ensure_ascii=False, indent=2, default=str))
        if failures:
            print(f"Failed demo stages: {[failure['name'] for failure in failures]}")
            return 1
        print("Agent fullflow demo succeeded.")
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
        if artifacts.get("run_id"):
            return str(artifacts["run_id"])
    for result in reversed(tool_results):
        artifacts = result["payload"].get("artifacts") or {}
        if artifacts.get("run_id"):
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
    return bool(payload.get("artifacts") or payload.get("artifact") or payload.get("report"))


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
    elif isinstance(artifacts, list):
        item["run_ids"] = [
            entry.get("run_id")
            for entry in artifacts
            if isinstance(entry, dict) and entry.get("run_id")
        ]
        item["artifact_count"] = len(artifacts)
    if isinstance(artifact, dict) and artifact.get("run_id"):
        item["run_id"] = artifact.get("run_id")
    return {key: value for key, value in item.items() if value not in (None, [], {})}


def _parse_sweep_parameters(assignments: list[str]) -> dict[str, list[str]]:
    parameters = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(f"Invalid sweep parameter assignment: {assignment!r}")
        name, values = assignment.split("=", 1)
        value_list = [value.strip() for value in values.split(",") if value.strip()]
        if not name or not value_list:
            raise ValueError(f"Invalid sweep parameter assignment: {assignment!r}")
        parameters[name] = value_list
    return parameters


def main() -> None:
    parser = argparse.ArgumentParser(description="Run P5 end-to-end agent demos.")
    parser.add_argument("--cores", type=int, default=1, help="COMSOL core limit.")
    parser.add_argument("--template-name", default="thermal_heat_transfer_seed")
    parser.add_argument("--template-model-name", default="agent_fullflow_template_model")
    parser.add_argument("--example-name", default="thermal_slab")
    parser.add_argument(
        "--parameter",
        action="append",
        default=[],
        metavar="NAME=VALUE1,VALUE2",
        help="Sweep axis for the sweep demo. Can be repeated.",
    )
    parser.add_argument(
        "--expression",
        action="append",
        default=None,
        help="Expression for the sweep demo. Can be repeated. Defaults to T.",
    )
    parser.add_argument("--max-cases", type=int, default=1)
    parser.add_argument("--artifact-root", default="runtime_smoke/fullflow_demo")
    parser.add_argument("--report-dir", default="runtime_smoke/fullflow_demo/reports")
    parser.add_argument("--archive-path", default="runtime_smoke/fullflow_demo.sqlite3")
    parser.add_argument("--max-tool-iterations", type=int, default=18)
    parser.add_argument(
        "--print-prompts",
        action="store_true",
        help="Print reproducible prompt fixtures and exit without calling LLM/COMSOL.",
    )
    args = parser.parse_args()

    if args.print_prompts:
        prompts = build_initial_demo_prompts(
            archive_path=args.archive_path,
            artifact_root=args.artifact_root,
            report_dir=args.report_dir,
            template_name=args.template_name,
            template_model_name=args.template_model_name,
            example_name=args.example_name,
            parameters=_parse_sweep_parameters(args.parameter) or {"L": ["0.5[mm]"]},
            expressions=args.expression or ["T"],
            max_cases=args.max_cases,
        )
        prompts.append(build_inspect_prompt(archive_path=args.archive_path, run_id="<sweep_run_id>"))
        print(json.dumps([prompt.to_dict() for prompt in prompts], ensure_ascii=False, indent=2))
        return

    raise SystemExit(asyncio.run(run_fullflow_demo(args)))


if __name__ == "__main__":
    main()
