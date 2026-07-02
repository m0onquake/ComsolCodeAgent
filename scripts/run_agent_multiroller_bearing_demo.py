"""Run a reproducible agent demo for real multi-roller bearing contact generation."""

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
from comsol_agent.agent.tool_registry import clear as clear_tools
from comsol_agent.agent.tools_bootstrap import register_all_tools
from comsol_agent.cli.config import load_config
from comsol_agent.llm.router import create_provider
from comsol_agent.memory.archive_store import ArchiveStore
from comsol_agent.simulation.skills import seed_builtin_templates
from comsol_agent.tools.comsol.client import COMSOLClient
from comsol_agent.tools.comsol.evaluate import comsol_plot
from comsol_agent.tools.comsol.model_ops import comsol_close_model
from comsol_agent.tools.comsol.solve import comsol_evaluate, comsol_solve
from comsol_agent.tools.simulation import (
    simulation_answer_artifact_question,
    simulation_export_bearing_contact_package,
    simulation_run_template,
)


VERIFIED_MULTIROLLER_CONTACT_CODE = """model.param().set('inner_race_span', '28[mm]');
model.param().set('outer_race_span', '28[mm]');
model.param().set('race_height', '3[mm]');
model.param().set('race_gap', '8[mm]');
model.param().set('bearing_width', '18[mm]');
model.param().set('roller_count', '2');
model.param().set('roller_diameter', '8[mm]');
model.param().set('roller_radius', 'roller_diameter/2');
model.param().set('roller_spacing', '10[mm]');
model.param().set('radial_load', '3000[N]');
model.param().set('load_per_roller', 'radial_load/roller_count');
model.param().set('friction_coefficient', '0.05');
model.param().set('contact_interference', '2[um]');
model.param().set('contact_pressure_est', 'load_per_roller/(bearing_width*roller_diameter)');
model.param().set('E_steel', '210[GPa]');
model.param().set('nu_steel', '0.30');
model.param().set('rho_steel', '7850[kg/m^3]');
model.param().set('mesh_contact_size', '0.08[mm]');
model.param().set('mesh_bulk_size', '0.8[mm]');
model.component().create('comp1', True);
model.component('comp1').geom().create('geom1', 2);
model.component('comp1').geom('geom1').lengthUnit('mm');
model.component('comp1').geom('geom1').create('inner_raceway', 'Rectangle');
model.component('comp1').geom('geom1').feature('inner_raceway').set('size', ['inner_race_span', 'race_height']);
model.component('comp1').geom('geom1').feature('inner_raceway').set('base', 'center');
model.component('comp1').geom('geom1').feature('inner_raceway').set('pos', ['0', '-race_gap/2-race_height/2']);
model.component('comp1').geom('geom1').create('outer_raceway', 'Rectangle');
model.component('comp1').geom('geom1').feature('outer_raceway').set('size', ['outer_race_span', 'race_height']);
model.component('comp1').geom('geom1').feature('outer_raceway').set('base', 'center');
model.component('comp1').geom('geom1').feature('outer_raceway').set('pos', ['0', 'race_gap/2+race_height/2']);
model.component('comp1').geom('geom1').create('roller1', 'Circle');
model.component('comp1').geom('geom1').feature('roller1').set('r', 'roller_radius');
model.component('comp1').geom('geom1').feature('roller1').set('pos', ['-roller_spacing/2', '0']);
model.component('comp1').geom('geom1').create('roller2', 'Circle');
model.component('comp1').geom('geom1').feature('roller2').set('r', 'roller_radius');
model.component('comp1').geom('geom1').feature('roller2').set('pos', ['roller_spacing/2', '0']);
model.component('comp1').geom('geom1').run();
model.component('comp1').material().create('mat_steel', 'Common');
model.component('comp1').material('mat_steel').label('Bearing steel');
model.component('comp1').material('mat_steel').propertyGroup('def').set('youngsmodulus', 'E_steel');
model.component('comp1').material('mat_steel').propertyGroup('def').set('poissonsratio', 'nu_steel');
model.component('comp1').material('mat_steel').propertyGroup('def').set('density', 'rho_steel');
model.component('comp1').physics().create('solid', 'SolidMechanics', 'geom1');
model.component('comp1').physics('solid').create('fix_outer', 'Fixed', 1);
model.component('comp1').physics('solid').feature('fix_outer').selection().set([6]);
pair_r1_inner = model.component('comp1').pair().create('cp_r1_inner', 'Contact');
pair_r1_inner.manualSelection(True);
pair_r1_inner.source().geom('geom1', 1);
pair_r1_inner.destination().geom('geom1', 1);
pair_r1_inner.source().set([9]);
pair_r1_inner.destination().set([3]);
pair_r1_outer = model.component('comp1').pair().create('cp_r1_outer', 'Contact');
pair_r1_outer.manualSelection(True);
pair_r1_outer.source().geom('geom1', 1);
pair_r1_outer.destination().geom('geom1', 1);
pair_r1_outer.source().set([9]);
pair_r1_outer.destination().set([7]);
pair_r2_inner = model.component('comp1').pair().create('cp_r2_inner', 'Contact');
pair_r2_inner.manualSelection(True);
pair_r2_inner.source().geom('geom1', 1);
pair_r2_inner.destination().geom('geom1', 1);
pair_r2_inner.source().set([10]);
pair_r2_inner.destination().set([3]);
pair_r2_outer = model.component('comp1').pair().create('cp_r2_outer', 'Contact');
pair_r2_outer.manualSelection(True);
pair_r2_outer.source().geom('geom1', 1);
pair_r2_outer.destination().geom('geom1', 1);
pair_r2_outer.source().set([10]);
pair_r2_outer.destination().set([7]);
model.component('comp1').physics('solid').create('contact_r1_inner', 'Contact', 1);
model.component('comp1').physics('solid').feature('contact_r1_inner').set('pairs', ['cp_r1_inner']);
model.component('comp1').physics('solid').feature('contact_r1_inner').set('pfm', 'penalty');
model.component('comp1').physics('solid').create('contact_r1_outer', 'Contact', 1);
model.component('comp1').physics('solid').feature('contact_r1_outer').set('pairs', ['cp_r1_outer']);
model.component('comp1').physics('solid').feature('contact_r1_outer').set('pfm', 'penalty');
model.component('comp1').physics('solid').create('contact_r2_inner', 'Contact', 1);
model.component('comp1').physics('solid').feature('contact_r2_inner').set('pairs', ['cp_r2_inner']);
model.component('comp1').physics('solid').feature('contact_r2_inner').set('pfm', 'penalty');
model.component('comp1').physics('solid').create('contact_r2_outer', 'Contact', 1);
model.component('comp1').physics('solid').feature('contact_r2_outer').set('pairs', ['cp_r2_outer']);
model.component('comp1').physics('solid').feature('contact_r2_outer').set('pfm', 'penalty');
model.component('comp1').physics('solid').create('inner_load', 'BoundaryLoad', 1);
model.component('comp1').physics('solid').feature('inner_load').selection().set([3]);
model.component('comp1').physics('solid').feature('inner_load').set('FperArea', ['0', 'contact_pressure_est', '0']);
model.component('comp1').mesh().create('mesh1');
model.component('comp1').mesh('mesh1').autoMeshSize(3);
model.study().create('std1');
model.study('std1').create('stat', 'Stationary');
model.study('std1').feature('stat').set('activate', ['solid', 'on']);
model.result().numerical().create('max_von_mises', 'MaxVolume');
model.result().numerical('max_von_mises').set('expr', 'solid.mises');
model.result().numerical().create('max_contact_pressure_estimate', 'EvalGlobal');
model.result().numerical('max_contact_pressure_estimate').set('expr', 'contact_pressure_est');
model.result().create('pg_stress', 'PlotGroup2D');
model.result('pg_stress').label('von Mises stress - multi-roller bearing contact');
model.result('pg_stress').create('surf_stress', 'Surface');
model.result('pg_stress').feature('surf_stress').set('expr', 'solid.mises');
output.write('Verified-style multi-roller bearing contact setup built: inner raceway segment, outer raceway segment, two rollers, four explicit Contact pairs, outer raceway fixed, inner raceway loaded. Cage geometry is omitted and preserved as a follow-up extension.');
"""


@dataclass(frozen=True)
class DemoPrompt:
    """One multi-roller demo prompt and its validation gates."""

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


def build_multiroller_code_generation_prompt(*, archive_path: str) -> DemoPrompt:
    """Ask the agent to plan a real multi-roller bearing and return setup code."""
    known_params = {
        "bearing_type": "cylindrical_roller_bearing",
        "inner_diameter": "40[mm]",
        "outer_diameter": "80[mm]",
        "bearing_width": "18[mm]",
        "roller_count": "4",
        "roller_diameter": "8[mm]",
        "roller_length": "16[mm]",
        "radial_load": "3000[N]",
        "material": "bearing_steel",
        "friction_coefficient": "0.05",
        "cage_included": "false",
        "contact_model": "2d_plane_strain_multiroller_contact_pair",
    }
    return DemoPrompt(
        name="multiroller_code_draft",
        prompt=(
            "A user asks for a real multi-roller/cylindrical roller bearing COMSOL simulation. "
            "This must not be replaced by a plate, beam, or block stress example. The model must "
            "contain an inner ring/raceway, an outer ring/raceway, and multiple rollers that contact "
            "the raceways. First call simulation_plan_multiroller_bearing with allow_defaults=true, "
            f"archive_path={archive_path!r} is not an argument to that planner, and provided_params="
            f"{known_params!r}. Then search existing templates for multi-roller contact coverage; "
            "if no true multi-roller template fits, call simulation_plan_generated_code with "
            "domain='structural', allow_defaults=false, archive_path="
            f"{archive_path!r}, user_request describing the same real bearing contact model, and "
            "known_params containing the planner's resolved_params plus contact requirements. "
            "Use the returned controlled prompt/API context to draft setup-only COMSOL Java/API code. "
            "Do not call validation, execution, COMSOL runtime, file tools, or save-template tools in this step. "
            "Return the generated code between literal markers GENERATED_CODE_START and GENERATED_CODE_END. "
            "Inside the markers return only executable COMSOL Java/API code for an existing `model` object. "
            "Use the verified first-run geometry pattern: a 2D plane-strain unfolded bearing contact cell with "
            "one rectangular inner raceway segment, one rectangular outer raceway segment, and two roller circles "
            "between them. This is a reduced bearing sector/contact-cell model, not a generic plate/block. "
            "Do not create annular rings with Difference/Union features in this first demo. "
            "The code must create unit-aware parameters, comp1/geom1, rectangular inner and outer raceway "
            "segments, at least two roller geometry features, SolidMechanics, explicit Contact Pair/Contact "
            "features for each roller-to-inner-raceway and roller-to-outer-raceway interface, meaningful "
            "radial load/support, mesh refinement near contact, stationary study, and a PlotGroup2D for solid.mises. "
            "Use the Python/MPh-compatible COMSOL API snippet style used by this project: no Java control-flow "
            "loops, no typed variables, no `new int[]`, no Markdown comments inside the code, and unroll repeated "
            "roller/contact operations explicitly. Use Python-list syntax such as [1, 2] and ['solid', 'on']. "
            "Create pairs with model.component('comp1').pair().create('cp_tag', 'Contact'), then bind them "
            "with Solid Mechanics Contact features using feature(...).set('pairs', ['cp_tag']). "
            "Use boundary-selection style from the verified contact fixture: pair variables are allowed, "
            "manualSelection(True), source().geom('geom1', 1), destination().geom('geom1', 1), and source/destination "
            "selection lists such as [9], [10], [3], [7]. "
            "Do not create IdentityPair physics interfaces. Use output.write(...) for messages. "
            "If cage geometry is omitted, write an output message saying cage is omitted and preserved as a follow-up. "
            "Do not solve or run plot groups in the generated setup code."
        ),
        required_tools=(
            "simulation_plan_multiroller_bearing",
            "simulation_search_templates",
            "simulation_plan_generated_code",
        ),
        successful_tools=(
            "simulation_plan_multiroller_bearing",
            "simulation_plan_generated_code",
        ),
    )


def build_multiroller_draft_repair_prompt(*, java_code: str, quality_errors: list[str]) -> DemoPrompt:
    """Ask the agent to repair generated code before launching COMSOL."""
    return DemoPrompt(
        name="multiroller_code_draft_repair",
        prompt=(
            "Repair the generated multi-roller bearing COMSOL setup code below. "
            "Keep it a real bearing model with inner ring, outer ring, multiple rollers, "
            "and explicit roller-to-inner/outer raceway Contact pairs. Do not replace it "
            "with a plate, beam, block, or single-roller placeholder. "
            f"The local quality gate reported these errors: {quality_errors!r}. "
            "First call simulation_retrieve_api_docs for Contact pair syntax if useful. "
            "Return repaired code between GENERATED_CODE_START and GENERATED_CODE_END only. "
            "Use model.component('comp1').pair().create('cp_tag', 'Contact') and "
            "feature(...).set('pairs', ['cp_tag']); use Python list syntax, no Java loops, "
            "no typed variables, no `new int[]`, no Difference/Union annular geometry, no IdentityPair "
            "physics interface, no solver run. Prefer rectangular inner/outer raceway segments with two "
            "roller circles and explicit Contact pairs. "
            "RAW_CODE_TO_REPAIR:\n"
            f"{java_code}"
        ),
        required_tools=(),
        successful_tools=(),
    )


def build_multiroller_execution_prompt(
    *,
    java_code: str,
    archive_path: str,
    artifact_dir: str,
    plot_path: str,
    model_name: str,
    template_name: str,
    package_dir: str,
) -> DemoPrompt:
    """Ask the agent to validate, repair if needed, execute, solve, plot, package, and answer."""
    params = {
        "inner_diameter": "40[mm]",
        "outer_diameter": "80[mm]",
        "bearing_width": "18[mm]",
        "roller_count": "4",
        "roller_diameter": "8[mm]",
        "roller_length": "16[mm]",
        "radial_load": "3000[N]",
        "E_steel": "210[GPa]",
        "nu_steel": "0.30",
        "rho_steel": "7850[kg/m^3]",
        "friction_coefficient": "0.05",
        "contact_interference": "2[um]",
    }
    return DemoPrompt(
        name="multiroller_execute_package_answer",
        prompt=(
            "Use the exact raw COMSOL Java/API code below as generated multi-roller bearing setup code. "
            "Run this deterministic chain: simulation_validate_template, simulation_run_template, "
            "comsol_solve, comsol_evaluate, comsol_plot, simulation_export_bearing_contact_package, "
            "simulation_answer_artifact_question, comsol_close_model. "
            "If validation or execution fails, perform at most two repair attempts using the structured error "
            "and simulation_retrieve_api_docs; keep the repaired code a real bearing model with rings, multiple "
            "rollers, and contact pairs. Do not replace it with a plate/block. "
            "During repair, do not call COMSOL introspection/probing APIs such as getInfo, getBoundaries, "
            "getNDObjects, getEdgeX, getIntProperty, or getProperties; these are not available in the current "
            "MPh/COMSOL bridge. If boundary selection or geometry creation fails, replace the setup code with "
            "the exact VERIFIED_FALLBACK_CODE shown below. Count that replacement as one of the two repair "
            "attempts. The fallback is still a reduced real bearing contact-cell model: rectangular inner "
            "raceway, rectangular outer raceway, two roller circles, boundary IDs [3], [7], [9], [10], four "
            "Contact pairs, outer fixed boundary [6], and inner load boundary [3]. "
            f"Use params={params!r}. Validate with name={template_name!r}, java_code=<raw code>, "
            f"params=params, archive_path={archive_path!r}. Run with simulation_run_template name={template_name!r}, "
            f"java_code=<raw code>, params=params, create_model_name={model_name!r}, close_model=false, "
            f"artifact_dir={artifact_dir!r}, artifact_name='agent_multiroller_bearing_execution', "
            f"archive_path={archive_path!r}. After run succeeds, solve the model, evaluate solid.mises, "
            f"plot solid.mises to {plot_path!r}, export a result package with "
            "simulation_export_bearing_contact_package using package_name='agent_multiroller_bearing_package', "
            f"output_dir={package_dir!r}, archive_path={archive_path!r}, and template_run_id from the template run. "
            "Then ask simulation_answer_artifact_question: '最大应力是多少，最大应力位置在哪里，滚子和外圈有没有接触？' "
            "using the package run_id. Close the model without saving. Report the stress PNG, package summary, "
            "Markdown report path, max stress, approximate max-stress location, contact status, and assumptions. "
            "RAW_GENERATED_CODE:\n"
            f"{java_code}\n\n"
            "VERIFIED_FALLBACK_CODE:\n"
            f"{VERIFIED_MULTIROLLER_CONTACT_CODE}"
        ),
        required_tools=(
            "simulation_validate_template",
            "simulation_run_template",
            "comsol_solve",
            "comsol_evaluate",
            "comsol_plot",
            "simulation_export_bearing_contact_package",
            "simulation_answer_artifact_question",
            "comsol_close_model",
        ),
        successful_tools=(
            "simulation_validate_template",
            "simulation_run_template",
            "comsol_solve",
            "comsol_evaluate",
            "comsol_plot",
            "simulation_export_bearing_contact_package",
            "simulation_answer_artifact_question",
            "comsol_close_model",
        ),
    )


async def run_multiroller_demo(args: argparse.Namespace) -> int:
    """Run the multi-roller bearing demo against the configured LLM and COMSOL runtime."""
    artifact_root = Path(args.artifact_root)
    artifact_dir = artifact_root / "template_runs"
    package_dir = artifact_root / "result_packages"
    archive_path = Path(args.archive_path)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    package_dir.mkdir(parents=True, exist_ok=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    config = load_config()
    config.agent.max_tool_iterations = max(config.agent.max_tool_iterations, args.max_tool_iterations)
    clear_tools()
    register_all_tools()
    archive_store = ArchiveStore(archive_path)
    seed_builtin_templates(archive_store)
    if args.use_verified_fixture and args.skip_comsol:
        draft_quality = validate_multiroller_code_draft(VERIFIED_MULTIROLLER_CONTACT_CODE)
        print(json.dumps({"fixture_quality": draft_quality}, ensure_ascii=False, indent=2))
        return 0 if draft_quality["success"] else 1
    if args.direct_fixture_run:
        return run_direct_fixture_smoke(args)
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

    draft_summary = None
    repair_summaries = []
    if args.use_verified_fixture:
        generated_code = VERIFIED_MULTIROLLER_CONTACT_CODE
        draft_quality = validate_multiroller_code_draft(generated_code)
        if not draft_quality["success"]:
            print("Verified fixture failed the real-bearing quality gate.")
            print(json.dumps(draft_quality, ensure_ascii=False, indent=2))
            return 1
    else:
        draft_prompt = build_multiroller_code_generation_prompt(archive_path=str(archive_path))
        draft_summary = await _run_prompt(agent, draft_prompt, tool_events)
        generated_code = extract_generated_code(draft_summary["response"])
        if not generated_code:
            print("Could not extract generated code between GENERATED_CODE_START and GENERATED_CODE_END.")
            print(draft_summary["response"])
            return 1
        draft_quality = validate_multiroller_code_draft(generated_code)
        for _ in range(args.max_draft_repairs):
            if draft_quality["success"]:
                break
            repair_prompt = build_multiroller_draft_repair_prompt(
                java_code=generated_code,
                quality_errors=draft_quality["errors"],
            )
            repair_summary = await _run_prompt(agent, repair_prompt, tool_events)
            repair_summaries.append(repair_summary)
            repaired_code = extract_generated_code(repair_summary["response"])
            if not repaired_code:
                continue
            generated_code = repaired_code
            draft_quality = validate_multiroller_code_draft(generated_code)
        if not draft_quality["success"]:
            print("Generated multi-roller code failed the real-bearing quality gate after bounded draft repair.")
            print(json.dumps(draft_quality, ensure_ascii=False, indent=2))
            if args.print_generated_code:
                print(generated_code)
            return 1
    if args.print_generated_code:
        print(generated_code)
    if args.skip_comsol:
        print("Multi-roller draft summary:")
        summaries = [summary for summary in [draft_summary, *repair_summaries] if summary is not None]
        print(json.dumps(_compact_summaries(summaries), ensure_ascii=False, indent=2, default=str))
        return 0 if all(summary["success"] for summary in summaries) else 1

    client = COMSOLClient.get_instance()
    try:
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        execute_prompt = build_multiroller_execution_prompt(
            java_code=generated_code,
            archive_path=str(archive_path),
            artifact_dir=str(artifact_dir),
            plot_path=str(artifact_root / "multiroller_von_mises.png"),
            model_name=args.model_name,
            template_name=args.template_name,
            package_dir=str(package_dir),
        )
        execute_summary = await _run_prompt(agent, execute_prompt, tool_events)
        summaries = [
            summary
            for summary in [draft_summary, *repair_summaries, execute_summary]
            if summary is not None
        ]
        print("Multi-roller bearing demo summary:")
        print(json.dumps(_compact_summaries(summaries), ensure_ascii=False, indent=2, default=str))
        failures = [summary for summary in summaries if not summary["success"]]
        return 1 if failures else 0
    finally:
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def run_direct_fixture_smoke(args: argparse.Namespace) -> int:
    """Run the verified-style fixture through tools without LLM variability."""
    artifact_root = Path(args.artifact_root)
    artifact_dir = artifact_root / "template_runs"
    package_dir = artifact_root / "result_packages"
    archive_path = Path(args.archive_path)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    package_dir.mkdir(parents=True, exist_ok=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    config = load_config()
    client = COMSOLClient.get_instance()
    model_name: str | None = None
    summary: dict[str, Any] = {"fixture_quality": validate_multiroller_code_draft(VERIFIED_MULTIROLLER_CONTACT_CODE)}
    try:
        client.start(
            cores=args.cores,
            version=config.comsol.version,
            executable_path=config.comsol.executable_path,
        )
        run = simulation_run_template(
            name=args.template_name,
            java_code=VERIFIED_MULTIROLLER_CONTACT_CODE,
            params={
                "inner_race_span": "28[mm]",
                "outer_race_span": "28[mm]",
                "race_height": "3[mm]",
                "race_gap": "8[mm]",
                "roller_count": "2",
                "roller_diameter": "8[mm]",
                "radial_load": "3000[N]",
            },
            create_model_name=args.model_name,
            close_model=False,
            artifact_dir=str(artifact_dir),
            artifact_name="direct_multiroller_bearing_fixture",
            archive_path=str(archive_path),
        )
        summary["template_run"] = _compact_runtime_result(run)
        if not run.get("success"):
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
            return 1
        model_name = str(run["model_name"])
        solve = comsol_solve(model_name)
        summary["solve"] = _compact_runtime_result(solve)
        if not solve.get("success"):
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
            return 1
        stress = comsol_evaluate(model_name, "solid.mises")
        pressure = comsol_evaluate(model_name, "contact_pressure_est")
        plot = comsol_plot(
            model_name,
            expression="solid.mises",
            plot_type="surface",
            filename=str(artifact_root / "multiroller_von_mises.png"),
        )
        summary["evaluations"] = [_compact_runtime_result(stress), _compact_runtime_result(pressure)]
        summary["plot"] = _compact_runtime_result(plot)
        if not plot.get("success"):
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
            return 1
        package = simulation_export_bearing_contact_package(
            model_name=model_name,
            template_run_id=(run.get("artifacts") or {}).get("run_id"),
            plot_path=str(artifact_root / "multiroller_von_mises.png"),
            output_dir=str(package_dir),
            package_name="direct_multiroller_bearing_package",
            archive_path=str(archive_path),
        )
        summary["package"] = _compact_runtime_result(package)
        if package.get("success"):
            summary["artifact_answer"] = simulation_answer_artifact_question(
                "最大应力是多少，最大应力位置在哪里，滚子和外圈有没有接触？",
                run_id=package.get("run_id"),
                archive_path=str(archive_path),
            )
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0 if package.get("success") else 1
    finally:
        if model_name:
            summary["close"] = _compact_runtime_result(comsol_close_model(model_name, save=False))
        if client.is_running:
            client.stop()
        COMSOLClient.reset_instance()


def _compact_runtime_result(result: dict | None) -> dict | None:
    if result is None:
        return None
    keys = (
        "success",
        "model_name",
        "template_name",
        "status",
        "stage",
        "expression",
        "statistics",
        "value",
        "filepath",
        "plot_type",
        "export_method",
        "run_id",
        "json_path",
        "markdown_path",
        "model_path",
        "plot_path",
        "metrics",
        "error",
        "error_type",
        "exception_type",
    )
    compact = {key: result.get(key) for key in keys if key in result}
    artifacts = result.get("artifacts")
    if isinstance(artifacts, dict):
        compact["run_id"] = artifacts.get("run_id")
        compact["json_path"] = artifacts.get("json_path")
    return compact


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
    return {
        "name": prompt.name,
        "success": not missing_calls and not missing_successes,
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


def validate_multiroller_code_draft(java_code: str) -> dict[str, Any]:
    """Apply demo-specific real-bearing gates before launching COMSOL."""
    compact = re.sub(r"\s+", "", _strip_code_fence(java_code)).lower()
    lowered = java_code.lower()
    errors: list[str] = []
    warnings: list[str] = []
    blocked = ("rectangle steel plate", "structural plate", "cantilever", "beam")
    for pattern in blocked:
        if pattern in lowered:
            errors.append(f"Generated code appears to be an unrelated structure: {pattern}")
    required_patterns = {
        "solidmechanics": "Solid Mechanics physics",
        "contact": "Contact Pair/Contact setup",
        "pair().create": "COMSOL pair creation",
        "inner": "inner ring/raceway naming",
        "outer": "outer ring/raceway naming",
        "roller": "multiple roller naming",
        "solid.mises": "von Mises stress output",
        "model.param().set": "unit-aware parameters",
        "mesh": "mesh setup",
        "stationary": "stationary study",
    }
    for pattern, label in required_patterns.items():
        if pattern not in compact:
            errors.append(f"Generated code is missing expected {label}: {pattern}")
    roller_mentions = len(re.findall(r"roller[_a-z0-9]*", lowered))
    if roller_mentions < 2:
        errors.append("Generated code must create or reference at least two rollers.")
    if "cage" not in lowered:
        warnings.append("Generated code does not mention cage omission or cage follow-up.")
    blocked_runtime_patterns = ("model.sol(", "study().run", "result().run", ".solve(")
    if any(pattern in compact for pattern in blocked_runtime_patterns):
        errors.append("Generated setup code must not solve or run plot/solver nodes; downstream tools own solving.")
    unsupported_snippets = (
        "for(",
        "for (",
        "new int",
        "string ",
        "model.output()",
        "identitypair",
        "getinfo",
        "getboundaries",
        "getndobjects",
        "getedgex",
        "getintproperty",
        "getproperties",
    )
    for pattern in unsupported_snippets:
        if pattern in lowered:
            errors.append(f"Generated code uses unsupported execution-wrapper syntax: {pattern}")
    unstable_geometry_patterns = ("'difference'", '"difference"', "'union'", '"union"', "annular", "annulus")
    for pattern in unstable_geometry_patterns:
        if pattern in lowered:
            errors.append(f"Generated code uses unstable free-form geometry for this demo: {pattern}")
    if "rectangle" not in lowered:
        warnings.append("Expected unfolded raceway segments to use Rectangle geometry in the first-run demo.")
    return {"success": not errors, "errors": errors, "warnings": warnings}


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
    artifacts = payload.get("artifacts") or {}
    item = {
        "tool": result["name"],
        "run_id": payload.get("run_id") or artifact.get("run_id") or artifacts.get("run_id"),
        "json_path": payload.get("json_path") or artifacts.get("json_path"),
        "markdown_path": payload.get("markdown_path"),
        "plot_path": payload.get("plot_path"),
        "report_id": report.get("report_id"),
        "html_path": report.get("html_path"),
    }
    return {key: value for key, value in item.items() if value not in (None, "", [], {})}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a generated multi-roller bearing contact demo.")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--archive-path", default="runtime_smoke/multiroller_bearing_demo.sqlite3")
    parser.add_argument("--artifact-root", default="runtime_smoke/multiroller_bearing_demo")
    parser.add_argument("--model-name", default="agent_multiroller_bearing_model")
    parser.add_argument("--template-name", default="agent_multiroller_bearing_generated_seed")
    parser.add_argument("--max-tool-iterations", type=int, default=32)
    parser.add_argument("--max-draft-repairs", type=int, default=2)
    parser.add_argument("--skip-comsol", action="store_true")
    parser.add_argument("--print-generated-code", action="store_true")
    parser.add_argument("--use-verified-fixture", action="store_true")
    parser.add_argument("--direct-fixture-run", action="store_true")
    parser.add_argument("--print-prompts", action="store_true")
    args = parser.parse_args()

    if args.print_prompts:
        draft = build_multiroller_code_generation_prompt(archive_path=args.archive_path)
        execute = build_multiroller_execution_prompt(
            java_code="<generated_code>",
            archive_path=args.archive_path,
            artifact_dir=str(Path(args.artifact_root) / "template_runs"),
            plot_path=str(Path(args.artifact_root) / "multiroller_von_mises.png"),
            model_name=args.model_name,
            template_name=args.template_name,
            package_dir=str(Path(args.artifact_root) / "result_packages"),
        )
        print(json.dumps([draft.to_dict(), execute.to_dict()], ensure_ascii=False, indent=2))
        return

    raise SystemExit(asyncio.run(run_multiroller_demo(args)))


if __name__ == "__main__":
    main()
