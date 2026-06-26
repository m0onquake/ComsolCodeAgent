"""Run a DeepSeek agent demo for the P7 generated-code fallback path."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
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
    """One generated-code demo prompt and its validation gates."""

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


def build_code_generation_prompt(*, archive_path: str) -> DemoPrompt:
    """Ask the agent to plan fallback generation and return raw Java/API code."""
    return DemoPrompt(
        name="generated_code_draft",
        prompt=(
            "A user asks for a COMSOL simulation that is not covered by any exact saved template: "
            "create a simple 2D structural steel plate, 50[mm] by 10[mm], fix the left edge, "
            "apply a horizontal traction on the right edge, run a stationary Solid Mechanics study, "
            "and prepare a von Mises stress plot. "
            "First call simulation_plan_generated_code with domain='structural', allow_defaults=false, "
            "archive_path="
            f"{archive_path!r}, and known_params containing geometry, physics, material, "
            "boundary_conditions, study_type, outputs, L='50[mm]', H='10[mm]', edge_load='2[MPa]'. "
            "Then use the returned controlled_prompt_block to draft COMSOL Java/API code directly. "
            "Do not call simulation_validate_template, simulation_run_template, comsol_execute_java, "
            "file tools, or COMSOL tools in this step. "
            "Return the generated code between literal markers GENERATED_CODE_START and GENERATED_CODE_END. "
            "Inside the markers return only executable COMSOL Java/API code for the existing `model` object. "
            "Do not include Markdown fences or explanatory prose inside the markers. "
            "The code must set unit-aware parameters, create comp1/geom1, create a rectangle, assign steel, "
            "create SolidMechanics, add Fixed and BoundaryLoad features, create mesh1, std1/stat, and "
            "a PlotGroup2D surface plot for solid.mises. "
            "Use locally verified setup-only API patterns: material('mat_steel').propertyGroup('def').set("
            "'youngsmodulus'/'poissonsratio'/'density', ...), BoundaryLoad FperArea, and "
            "study('std1').feature('stat').set('activate', ['solid', 'on']). "
            "Do not create solver nodes, call model.sol(...), solve, or run plot groups; the next tool chain "
            "will validate, execute setup code, solve, evaluate, and plot."
        ),
        required_tools=("simulation_plan_generated_code",),
        successful_tools=("simulation_plan_generated_code",),
    )


def build_generated_code_execution_prompt(
    *,
    java_code: str,
    archive_path: str,
    artifact_dir: str,
    plot_path: str,
    model_name: str,
    template_name: str,
) -> DemoPrompt:
    """Ask the agent to validate, run, solve, plot, and save generated raw code."""
    params = {
        "L": "50[mm]",
        "H": "10[mm]",
        "E_steel": "210[GPa]",
        "nu_steel": "0.30",
        "rho_steel": "7850[kg/m^3]",
        "edge_load": "2[MPa]",
    }
    return DemoPrompt(
        name="generated_code_execute",
        prompt=(
            "Use the exact raw COMSOL Java/API code below as LLM-generated code. "
            "Do not search templates and do not rewrite the code unless validation fails. "
            "Run this deterministic tool chain in order: simulation_validate_template, "
            "simulation_run_template, comsol_solve, comsol_evaluate, comsol_plot, "
            "simulation_save_template, comsol_close_model. "
            f"Use params={params!r}. "
            f"Validate with name={template_name!r}, java_code=<raw code>, params=params, "
            f"archive_path={archive_path!r}. "
            f"Run with simulation_run_template name={template_name!r}, java_code=<raw code>, params=params, "
            f"create_model_name={model_name!r}, close_model=false, "
            f"artifact_dir={artifact_dir!r}, artifact_name='agent_generated_code_execution', "
            f"archive_path={archive_path!r}. "
            "After the run succeeds, call comsol_solve, evaluate expression 'solid.mises', "
            f"plot expression 'solid.mises' to {plot_path!r}, save the generated code as a reusable "
            f"template using simulation_save_template with name={template_name!r}, domain='structural', "
            f"params=params, archive_path={archive_path!r}, then close the model without saving. "
            "Report the template_execution run_id, JSON path, plot path, saved template name, and stress max. "
            "RAW_GENERATED_CODE:\n"
            f"{java_code}"
        ),
        required_tools=(
            "simulation_validate_template",
            "simulation_run_template",
            "comsol_solve",
            "comsol_evaluate",
            "comsol_plot",
            "simulation_save_template",
            "comsol_close_model",
        ),
        successful_tools=(
            "simulation_validate_template",
            "simulation_run_template",
            "comsol_solve",
            "comsol_evaluate",
            "comsol_plot",
            "simulation_save_template",
            "comsol_close_model",
        ),
    )


async def run_generated_code_demo(args: argparse.Namespace) -> int:
    """Run the P7 generated-code demo against the configured LLM and COMSOL runtime."""
    artifact_root = Path(args.artifact_root)
    artifact_dir = artifact_root / "template_runs"
    archive_path = Path(args.archive_path)
    artifact_dir.mkdir(parents=True, exist_ok=True)
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
    tool_events: list[tuple[str, dict[str, Any]]] = []
    agent = AgentLoop(
        llm_provider=provider,
        config=config,
        on_tool_call=lambda name, call_args: tool_events.append((name, call_args)),
        archive_store=archive_store,
    )

    draft_prompt = build_code_generation_prompt(archive_path=str(archive_path))
    draft_summary = await _run_prompt(agent, draft_prompt, tool_events)
    generated_code = extract_generated_code(draft_summary["response"])
    if not generated_code:
        print("Could not extract generated code between GENERATED_CODE_START and GENERATED_CODE_END.")
        print("Draft response:")
        print(draft_summary["response"])
        return 1
    draft_quality = validate_generated_code_draft(generated_code)
    if not draft_quality["success"]:
        print("Generated code did not pass the setup-only draft quality gate.")
        print(json.dumps(draft_quality, ensure_ascii=False, indent=2))
        if args.print_generated_code:
            print("Extracted generated code:")
            print(generated_code)
        return 1

    if args.print_generated_code:
        print("Extracted generated code:")
        print(generated_code)

    if args.skip_comsol:
        print("Generated-code draft summary:")
        print(json.dumps(_compact_summaries([draft_summary]), ensure_ascii=False, indent=2, default=str))
        return 0 if draft_summary["success"] else 1

    client = COMSOLClient.get_instance()
    try:
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        execute_prompt = build_generated_code_execution_prompt(
            java_code=generated_code,
            archive_path=str(archive_path),
            artifact_dir=str(artifact_dir),
            plot_path=str(artifact_root / "generated_code_von_mises.png"),
            model_name=args.model_name,
            template_name=args.template_name,
        )
        execute_summary = await _run_prompt(agent, execute_prompt, tool_events)
        summaries = [draft_summary, execute_summary]
        print("Generated-code agent demo summary:")
        print(json.dumps(_compact_summaries(summaries), ensure_ascii=False, indent=2, default=str))
        failures = [summary for summary in summaries if not summary["success"]]
        if failures:
            print(f"Failed generated-code demo stages: {[failure['name'] for failure in failures]}")
            return 1
        print("Agent generated-code demo succeeded.")
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


def extract_generated_code(response: str) -> str | None:
    """Extract generated Java/API code from a model response."""
    marker_match = re.search(
        r"GENERATED_CODE_START\s*(.*?)\s*GENERATED_CODE_END",
        response,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if marker_match:
        return _strip_code_fence(marker_match.group(1)).strip()
    fence_match = re.search(r"```(?:java|text)?\s*(.*?)```", response, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        code = _strip_code_fence(fence_match.group(1)).strip()
        if "model." in code:
            return code
    return response.strip() if "model." in response else None


def validate_generated_code_draft(java_code: str) -> dict[str, Any]:
    """Apply demo-specific setup-only gates before launching COMSOL."""
    errors: list[str] = []
    warnings: list[str] = []
    compact = re.sub(r"\s+", "", _strip_code_fence(java_code))
    blocked_patterns = {
        "model.sol(": "Generated setup code must not create or run solver nodes; comsol_solve owns solving.",
        ".study().feature(": "Generated setup code should not drive solver/study run internals.",
        ".run();": "Generated setup code should not run mesh, solver, or plot groups; downstream tools run them.",
    }
    for pattern, message in blocked_patterns.items():
        if pattern.replace(" ", "") in compact:
            errors.append(message)

    required_patterns = {
        "model.param().set(": "parameters",
        ".component().create(": "component creation",
        ".geom().create(": "geometry creation",
        ".material().create(": "material creation",
        ".propertyGroup('def').set(": "material propertyGroup API",
        ".physics().create(": "physics creation",
        "SolidMechanics": "Solid Mechanics physics",
        "BoundaryLoad": "boundary load feature",
        "FperArea": "locally verified structural boundary-load API",
        ".mesh().create(": "mesh creation",
        ".study().create(": "study creation",
        "PlotGroup2D": "2D plot group",
        "solid.mises": "von Mises expression",
    }
    for pattern, label in required_patterns.items():
        if pattern.replace(" ", "") not in compact:
            errors.append(f"Generated code is missing expected {label}: {pattern}")

    if ".set('property'," in compact or '.set("property",' in compact:
        errors.append("Generated code used material().set('property', ...); use propertyGroup('def').set(...) instead.")
    if "LoadType" in java_code or "Traction" in java_code:
        warnings.append("Generated code mentions traction-style load settings; FperArea is the locally verified structural API.")

    return {
        "success": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    stripped = re.sub(r"^```(?:java|text)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


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


def _compact_summaries(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
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
        }
        for summary in summaries
    ]


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
        item["json_path"] = artifacts.get("json_path")
    if isinstance(artifact, dict) and artifact.get("run_id"):
        item["run_id"] = artifact.get("run_id")
    return {key: value for key, value in item.items() if value not in (None, [], {})}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a P7 agent generated-code demo.")
    parser.add_argument("--cores", type=int, default=1, help="COMSOL core limit.")
    parser.add_argument("--archive-path", default="runtime_smoke/agent_generated_code_demo.sqlite3")
    parser.add_argument("--artifact-root", default="runtime_smoke/agent_generated_code_demo")
    parser.add_argument("--model-name", default="agent_generated_code_model")
    parser.add_argument("--template-name", default="agent_generated_structural_plate_seed")
    parser.add_argument("--max-tool-iterations", type=int, default=24)
    parser.add_argument("--skip-comsol", action="store_true", help="Only run the LLM code-draft stage.")
    parser.add_argument("--print-generated-code", action="store_true")
    parser.add_argument(
        "--print-prompts",
        action="store_true",
        help="Print reproducible prompt fixtures and exit without calling LLM/COMSOL.",
    )
    args = parser.parse_args()

    if args.print_prompts:
        draft = build_code_generation_prompt(archive_path=args.archive_path)
        execute = build_generated_code_execution_prompt(
            java_code="<generated_code>",
            archive_path=args.archive_path,
            artifact_dir=str(Path(args.artifact_root) / "template_runs"),
            plot_path=str(Path(args.artifact_root) / "generated_code_von_mises.png"),
            model_name=args.model_name,
            template_name=args.template_name,
        )
        print(json.dumps([draft.to_dict(), execute.to_dict()], ensure_ascii=False, indent=2))
        return

    raise SystemExit(asyncio.run(run_generated_code_demo(args)))


if __name__ == "__main__":
    main()
