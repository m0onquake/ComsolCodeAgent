# COMSOL Runtime Setup

The project uses the MPh Python bridge to control a local COMSOL session.

## Runtime probe

Install the runtime dependencies into the project virtual environment:

```bash
.venv/bin/pip install "MPh>=1.2.0"
```

Run a non-invasive doctor check for local configuration, Python dependencies,
COMSOL discovery, proxy/NO_PROXY, and archive writability:

```bash
.venv/bin/python scripts/doctor_runtime.py
```

Inside the interactive CLI, the same check is available as:

```text
/doctor
```

Run explicit deep checks when you want to call the configured LLM API and/or
start a local COMSOL session:

```bash
.venv/bin/python scripts/doctor_runtime.py --deep --json
.venv/bin/python scripts/doctor_runtime.py --llm-only --json
.venv/bin/python scripts/doctor_runtime.py --comsol-only --cores 1 --create-smoke --json
```

Inside the interactive CLI:

```text
/doctor --deep
/doctor --llm-only
/doctor --comsol-only --cores 1 --create-smoke
```

Run a non-invasive probe:

```bash
.venv/bin/python scripts/test_comsol_runtime.py
```

This checks:

- configured COMSOL executable path
- configured COMSOL version
- MPh importability
- MPh backend discovery
- backend JVM and server metadata

Run a real startup probe:

```bash
.venv/bin/python scripts/test_comsol_runtime.py --start --cores 1
```

Run a minimal model lifecycle smoke test:

```bash
.venv/bin/python scripts/test_comsol_runtime.py --start --cores 1 --create-smoke
```

The model lifecycle smoke test creates and saves
`runtime_smoke/comsol_agent_smoke.mph`, then removes the model from the live
COMSOL client.

Run the project tool-layer smoke test:

```bash
.venv/bin/python scripts/run_comsol_tool_smoke.py --cores 1
```

This starts COMSOL through `COMSOLClient` and exercises:

- `comsol_create_model`
- `comsol_set_parameter`
- `comsol_list_parameters`
- `comsol_list_models`
- `comsol_save_model`
- `comsol_close_model`

Run the full DeepSeek + AgentLoop + COMSOL smoke test:

```bash
.venv/bin/python scripts/run_agent_comsol_smoke.py --cores 1
```

This validates the architecture's main loop end to end:

1. DeepSeek emits tool calls through the OpenAI-compatible provider.
2. `AgentLoop` validates and dispatches the tool calls.
3. The COMSOL tools operate on a real local MPh/COMSOL session.
4. The agent consumes tool results and returns a final summary.

Recovered intermediate tool failures are reported but accepted when the agent
subsequently succeeds with the same required tool. This covers the repair-loop
behavior described in `docs/architecture.md`.

Run a real example-model solve/evaluate smoke test:

```bash
.venv/bin/python scripts/run_comsol_model_smoke.py --cores 1
```

Evaluate multiple expressions or set parameters before solve:

```bash
.venv/bin/python scripts/run_comsol_model_smoke.py --cores 1 \
  --expressions T ht.qx \
  --parameter L=1[mm]
```

The default model is COMSOL's built-in heat-conduction slab example:

```text
/Applications/COMSOL62/Multiphysics/applications/Heat_Transfer_Module/Tutorials,_Conduction/heat_conduction_in_slab.mph
```

This exercises:

- `comsol_load_model`
- `comsol_get_model_summary`
- `comsol_solve`
- `comsol_evaluate`
- `comsol_close_model`

The default evaluated expression is `T`.

Run the full DeepSeek + high-level example tool smoke test:

```bash
.venv/bin/python scripts/run_agent_example_smoke.py --cores 1
```

The high-level tool accepts:

- `parameters`: mapping of parameter names to unit-aware values, set before solve
- `expressions`: list of COMSOL expressions evaluated after solve
- `solve`: whether to solve before evaluation
- `close_model`: whether to close the model after evaluation

This asks the agent to call `simulation_run_example_model` directly and then
summarize the evaluation statistics. It verifies that the high-level example
tool is visible to the LLM and works against a real local COMSOL session.

Run a bounded high-level parameter sweep against a real COMSOL example:

```bash
.venv/bin/python scripts/run_comsol_sweep_smoke.py --cores 1 \
  --parameter L=0.5[mm],1[mm] \
  --expression T
```

This exercises the runtime counterpart to `simulation_plan_parameter_sweep`:

- expand sweep axes into cases
- load a built-in example model or a custom `.mph` file
- set each case's parameters
- solve the selected/default study
- evaluate one or more expressions
- return compact per-case statistics and samples instead of full arrays
- persist JSON, CSV, and manifest artifacts for experiment review

The Agent-facing runtime tool is `simulation_run_parameter_sweep`. It accepts:

- `model_name`: run against an already loaded model
- `example_name`: load a known built-in model, such as `thermal_slab`
- `model_file`: load a custom `.mph` file
- `parameters`: mapping of parameter names to lists of unit-aware values
- `expressions`: list of COMSOL expressions to evaluate after each case
- `max_cases`: safety cap for executed cases
- `close_model`: defaults to closing models loaded by the tool while preserving already loaded models
- `persist_results`: defaults to writing artifacts
- `artifact_dir`: optional output directory, defaulting to `runtime_smoke/sweeps`
- `artifact_name`: optional filename prefix for a named run

Each persisted sweep writes:

- `<run_id>.json`: full structured tool result
- `<run_id>.csv`: one row per case/expression with flattened parameters and statistics
- `<run_id>.manifest.json`: small index record with source, model, paths, and case count

By default, persisted sweep artifacts are also indexed in:

```text
~/.comsol_agent/archive/archive.sqlite3
```

The archive index enables later retrieval without scanning artifact folders. The
Agent-facing tools are:

- `simulation_list_templates`: list archived simulation/code templates by domain
- `simulation_search_templates`: keyword search over template names, domains, code, and params
- `simulation_read_template`: read one template's seed Java/API code and parameters
- `simulation_validate_template`: offline-check archived or raw Java/API seed code before execution
- `simulation_run_template`: validate and execute a template against an explicit loaded or newly created model
- `simulation_export_template`: export a template to an editable `.java` seed file
- `simulation_save_template`: save or update a reusable COMSOL Java/API template
- `simulation_plan_generated_code`: plan the controlled generated-code fallback
  path, including template candidates, local API snippets, a strict code-output
  prompt block, validation params, and next tool chain
- `simulation_list_artifacts`: list recent archived simulation artifacts
- `simulation_search_artifacts`: search by run id, model name, source, paths, or metadata
- `simulation_read_artifact`: read a compact preview of a specific archived run or report
- `simulation_compare_artifacts`: compare archived sweep CSV metrics and rank cases
- `simulation_export_artifact_report`: export a Markdown/HTML report from archived sweep comparisons or template execution runs
- `simulation_rerun_artifact`: replay archived sweep or template execution artifacts with bounded overrides
- `simulation_retrieve_api_docs`: retrieve compact, cited local documentation snippets for API repair/code generation
- `simulation_plan_bearing_contact`: decide whether a bearing-contact request
  needs follow-up questions or can use the default demo parameters
- `simulation_export_bearing_contact_package`: save a solved bearing model,
  stress PNG, metrics, summary JSON, Markdown report, and archive index record

For isolated tests or project-specific archives, pass `archive_path` to
`simulation_run_parameter_sweep` and to the list/search tools.

## Template-First, Generated-Code Fallback

The agent should not be limited to the current template library. The runtime
policy is template-first, generated-code fallback:

1. Parse the user's simulation intent: geometry, material, physics, boundary
   conditions, mesh, study type, outputs, and missing parameters.
2. Search/read existing templates. Use a template when it fits the problem.
3. If no template fits, retrieve local COMSOL API snippets with
   `simulation_retrieve_api_docs` and inject a controlled code-generation prompt
   block into the LLM context.
4. Ask the LLM to return COMSOL Java/API setup code directly, with explicit
   parameters and no surrounding prose inside the code block.
5. Validate the generated code with `simulation_validate_template`.
6. Execute only against a newly created model or a loaded model that the user has
   explicitly chosen.
7. If execution fails, feed the structured error plus retrieved API snippets into
   the repair loop.
8. Archive the generated code, validation result, execution result, plots,
   saved `.mph`, and report. Offer to save successful generated code as a
   reusable template.

This generated-code path is the main way the assistant grows beyond the bundled
examples. Bearing contact remains a representative validation case, not the
overall product boundary.

Run the current generated-code fallback smoke without starting COMSOL:

```bash
python3 scripts/run_generated_code_fallback_smoke.py --skip-comsol \
  --archive-path runtime_smoke/generated_code_fallback_skip.sqlite3
```

Run the real local COMSOL smoke. This uses raw Java/API code embedded in the
script as a stand-in for LLM code output, then exercises the same validation,
execution, solve/evaluate/plot, archive, and template-promotion path:

```bash
.venv/bin/python scripts/run_generated_code_fallback_smoke.py --cores 1 \
  --archive-path runtime_smoke/generated_code_fallback.sqlite3 \
  --artifact-dir runtime_smoke/generated_code_fallback/template_runs \
  --plot-path runtime_smoke/generated_code_fallback/von_mises.png
```

Inside the interactive CLI, use slash commands for quick artifact review:

```text
/templates
/templates domain thermal
/templates search heat thermal
/templates show thermal_heat_transfer_seed
/templates validate thermal_heat_transfer_seed
/templates run thermal_heat_transfer_seed create template_smoke_model
/templates run thermal_heat_transfer_seed model loaded_model --allow-modify-loaded
/templates export thermal_heat_transfer_seed runtime_smoke/templates/thermal_heat_transfer_seed.java
/templates save custom_thermal thermal runtime_smoke/templates/custom_thermal.java runtime_smoke/templates/custom_thermal.params.json
/artifacts
/artifacts search agent_sweep_smoke
/artifacts show agent_sweep_smoke_20260608_194443_628426
/artifacts compare agent_sweep_smoke mean T max
/artifacts report agent_sweep_smoke mean T max
/artifacts report agent_sweep_smoke mean T max html
/artifacts template-runs template_smoke_model
/artifacts report-template template_smoke_model html
```

Local documentation retrieval for repair/code generation is available through
the Agent-facing tool `simulation_retrieve_api_docs`. It works offline by
chunking workspace Markdown files, extracting lightweight metadata such as
domain, COMSOL version mentions, and API symbols, and returning cited compact
snippets. This is the deterministic precursor to a future embedding/vector RAG
layer.

```text
simulation_retrieve_api_docs(query="model.param().set Java API", directory="docs")
```

Template records can also be inspected non-interactively:

```bash
.venv/bin/python scripts/list_templates.py --seed-builtins --domain thermal
.venv/bin/python scripts/list_templates.py --query heat --domain thermal
.venv/bin/python scripts/list_templates.py --show thermal_heat_transfer_seed
.venv/bin/python scripts/list_templates.py --validate thermal_heat_transfer_seed
.venv/bin/python scripts/list_templates.py \
  --export thermal_heat_transfer_seed \
  --output runtime_smoke/templates/thermal_heat_transfer_seed.java
.venv/bin/python scripts/list_templates.py \
  --validate-file runtime_smoke/templates/thermal_heat_transfer_seed.java \
  --params-json '{"power": "10[W]", "T_ambient": "293.15[K]"}'
.venv/bin/python scripts/list_templates.py \
  --run thermal_heat_transfer_seed \
  --create-model-name template_smoke_model \
  --artifact-dir runtime_smoke/template_runs
.venv/bin/python scripts/list_templates.py \
  --save custom_thermal \
  --domain thermal \
  --java-file runtime_smoke/templates/custom_thermal.java \
  --params-json '{"power": "25[W]"}'
```

The built-in structural bearing-contact seeds can be inspected and smoke-tested
in the same template system. Use `bearing_contact_pair_seed` for the more
realistic 2D COMSOL Contact-pair workflow, or `bearing_contact_hertz_seed` for
the lighter Hertz-style pressure workflow:

```bash
.venv/bin/python scripts/list_templates.py --seed-builtins --validate bearing_contact_pair_seed
.venv/bin/python scripts/list_templates.py --seed-builtins --validate bearing_contact_hertz_seed
.venv/bin/python scripts/run_bearing_contact_template_smoke.py --cores 1 \
  --template-name bearing_contact_pair_seed \
  --model-name bearing_contact_pair_template_smoke \
  --archive-path runtime_smoke/bearing_contact_pair_template_smoke.sqlite3 \
  --artifact-dir runtime_smoke/bearing_contact_pair_template_smoke \
  --plot-path runtime_smoke/bearing_contact_pair_template_smoke/von_mises.png \
  --package-dir runtime_smoke/bearing_contact_pair_template_smoke/packages
```

The full bearing smoke creates a default 2D ball/raceway model, creates an
explicit COMSOL Contact pair for `bearing_contact_pair_seed`, runs the default
stationary study, evaluates `solid.mises` and `contact_pressure_guess`, and
exports a von Mises PNG plus a bearing-contact result package. This is a
workflow smoke case, not yet a production-grade 3D multi-ball contact model.

Before running a bearing-contact model, the agent can plan missing parameters
offline:

```text
simulation_plan_bearing_contact(
  user_request="建立一个轴承接触仿真，尽量真实",
  provided_params={"radial_load": "1000[N]"},
  allow_defaults=false
)
```

For underspecified production-like requests, the tool returns follow-up
questions for dimensions, ball size, load, and contact model assumptions. For a
quick/default demo, use `allow_defaults=true`; the tool resolves the default
deep-groove bearing parameters. It recommends `bearing_contact_pair_seed` when
the request mentions a realistic/contact-pair model, and
`bearing_contact_hertz_seed` for the lighter quick demo.

After solving and plotting, package the result:

```text
simulation_export_bearing_contact_package(
  model_name="agent_bearing_contact_model",
  template_run_id="<template_execution_run_id>",
  plot_path="runtime_smoke/bearing_contact_demo/bearing_contact_von_mises.png",
  output_dir="runtime_smoke/bearing_contact_demo/result_packages",
  archive_path="runtime_smoke/bearing_contact_demo.sqlite3"
)
```

The package writes `summary.json`, `report.md`, a saved `.mph` model, and an
archive record of kind `bearing_contact_package`.

## Multi-Roller Bearing Generated-Code Demo

The multi-roller bearing demo is the current real-contact generated-code
validation path. It is intentionally not a plate/block surrogate: the smoke
model contains an inner raceway segment, an outer raceway segment, two rolling
elements, and four explicit COMSOL Contact pairs for roller-to-raceway
interfaces. Cage geometry is omitted in the first run and recorded as a
follow-up assumption.

Inspect the reproducible prompt fixtures without calling LLM or COMSOL:

```bash
python3 scripts/run_agent_multiroller_bearing_demo.py --print-prompts
```

Check the verified generated-code fixture without starting COMSOL:

```bash
.venv/bin/python scripts/run_agent_multiroller_bearing_demo.py \
  --use-verified-fixture --skip-comsol
```

Run the deterministic tool-chain smoke without LLM variability:

```bash
.venv/bin/python scripts/run_agent_multiroller_bearing_demo.py \
  --direct-fixture-run --cores 1
```

Run the Agent-orchestrated execution path with the same verified generated code:

```bash
.venv/bin/python scripts/run_agent_multiroller_bearing_demo.py \
  --use-verified-fixture --cores 1
```

Run the complete free-generation path, including bounded repair fallback when
the first generated snippet is not directly executable:

```bash
.venv/bin/python scripts/run_agent_multiroller_bearing_demo.py --cores 1
```

The Agent path validates the generated code, executes it on a new model, solves
the stationary Solid Mechanics study, evaluates `solid.mises`, exports
`runtime_smoke/multiroller_bearing_demo/multiroller_von_mises.png`, writes a
result package, and answers a follow-up artifact question such as "最大应力是多少，
最大应力位置在哪里，滚子和外圈有没有接触？" from the archived package.

Latest verified local COMSOL 6.2 result for the full free-generation chain:

- Template execution run id:
  `agent_multiroller_bearing_execution_20260628_172644_894940`
- Result package run id:
  `agent_multiroller_bearing_package_agent_multiroller_bearing_model_1_20260628_172700_698799`
- von Mises stress maximum: about `3.253e8` Pa
- Contact pressure estimate: about `1.042e7` Pa
- Stress PNG:
  `runtime_smoke/multiroller_bearing_demo/multiroller_von_mises.png`
- Package JSON:
  `runtime_smoke/multiroller_bearing_demo/result_packages/agent_multiroller_bearing_package_agent_multiroller_bearing_model_1_20260628_172700_698799/summary.json`
- Package Markdown:
  `runtime_smoke/multiroller_bearing_demo/result_packages/agent_multiroller_bearing_package_agent_multiroller_bearing_model_1_20260628_172700_698799/report.md`
- Observed behavior: the first free-generated setup was rejected during runtime
  execution, then the bounded repair path replaced it with the verified
  bearing contact-cell fallback and completed solve/plot/package/Q&A.

Known modeling limits:

- The first verified model is a 2D plane-strain contact smoke with two rollers,
  not a full 3D complete bearing.
- Boundary IDs are generated for this fixture geometry and must be reviewed
  before production design.
- The cage is omitted and kept as an explicit extension point.
- Free-generated snippets can still fail on boundary or contact API details;
  the demo now uses a bounded repair fallback to a verified real-bearing
  contact-cell model while named-selection generation is improved.

Template export uses the same local path safety model as file tools. Output
paths are allowed under the project workspace and `~/.comsol_agent` by default.
For an additional trusted directory, set:

```bash
export COMSOL_AGENT_ALLOWED_PATHS=/path/to/extra/workdir
```

`/templates run` and `scripts/list_templates.py --run` start or use a real
COMSOL session through the normal tool layer. Use `create <model_name>` /
`--create-model-name` for isolated smoke checks, or `model <model_name>` /
`--model-name` only when you intend to modify an already loaded model. In the
interactive CLI, loaded-model execution requires the explicit
`--allow-modify-loaded` flag.

Use session archive commands to inspect saved conversation snapshots and memory
cards without opening the JSON files manually:

```text
/sessions
/sessions search thermal
/sessions show session_20260608_194443_628426
/sessions show session_20260608_194443_628426 50
```

`/sessions show` displays the archive summary, recent memory cards, and a compact
timeline reconstructed from the JSON snapshot, including user/assistant messages,
tool calls, tool results, and repair reports.

The same archive can be inspected non-interactively:

```bash
.venv/bin/python scripts/list_sessions.py --query thermal
.venv/bin/python scripts/list_sessions.py --show session_20260608_194443_628426
.venv/bin/python scripts/list_sessions.py --show session_20260608_194443_628426 --max-events 50
```

Export the archive index and memory records as one JSON bundle:

```text
/archive
/archive export runtime_smoke/archive_exports/latest.json 100 timelines
/archive cleanup 100
/archive cleanup 100 apply
```

```bash
.venv/bin/python scripts/export_archive.py \
  --output runtime_smoke/archive_exports/latest.json \
  --limit 100 \
  --include-timelines

.venv/bin/python scripts/cleanup_archive.py --limit 100
.venv/bin/python scripts/cleanup_archive.py --limit 100 --apply
```

Archive cleanup is conservative: it only removes SQLite artifact index rows whose
recorded JSON/CSV/manifest files are already missing. It defaults to dry-run and
does not delete existing artifact files.

Compare archived sweep records without invoking COMSOL:

```bash
.venv/bin/python scripts/compare_sweep_artifacts.py \
  --query agent_sweep_smoke \
  --metric mean \
  --expression T \
  --direction max
```

This reads the archived CSV summaries, ranks rows by the selected numeric metric,
and reports the best/worst cases plus parameter differences across the ranked
rows.

Export the same comparison as a Markdown report:

```bash
.venv/bin/python scripts/export_sweep_report.py \
  --query agent_sweep_smoke \
  --metric mean \
  --expression T \
  --direction max \
  --report-name agent_sweep_summary
```

Export a companion self-contained HTML report for browser review:

```bash
.venv/bin/python scripts/export_sweep_report.py \
  --query agent_sweep_smoke \
  --metric mean \
  --expression T \
  --direction max \
  --report-name agent_sweep_summary \
  --format html
```

Exported reports write both `<report_id>.md` and
`<report_id>.manifest.json`. With `--format html` or `--format both`, they also
write `<report_id>.html`. Sweep reports are indexed in the archive as
`comparison_report` artifacts, and template execution reports are indexed as
`template_execution_report` artifacts. Raw generated-code execution reports are
indexed as `generated_code_execution_report` artifacts, so they can be found later with
`/artifacts search <report_name>`.

Export a template execution report instead of a sweep comparison:

```bash
.venv/bin/python scripts/export_sweep_report.py \
  --kind template_execution \
  --query template_smoke_model \
  --output-dir runtime_smoke/reports \
  --report-name template_smoke_summary \
  --format html
```

Replay an archived sweep through the real COMSOL runtime:

```bash
.venv/bin/python scripts/rerun_sweep_artifact.py \
  agent_sweep_smoke_20260608_194443_628426 \
  --parameter L=0.75[mm] \
  --expression T \
  --max-cases 1 \
  --artifact-name replay_agent_sweep
```

The Agent-facing tool is `simulation_rerun_artifact`. For sweep artifacts, it
reads the archived JSON record, reconstructs the original model source,
parameter axes, and output expressions, then applies optional
`parameter_overrides` and `expression_overrides` before calling
`simulation_run_parameter_sweep` again. For `template_execution` and
`generated_code_execution` artifacts, it reconstructs `simulation_run_template`
from the archived code/parameter snapshot when available, or from the archived
template name for older records. Use `params_overrides`, `model_name`, or
`create_model_name` to adjust the replay target. Artifacts from the replay are
persisted and indexed as a new run.

Run the full DeepSeek + AgentLoop + high-level parameter sweep smoke test:

```bash
.venv/bin/python scripts/run_agent_sweep_smoke.py --cores 1 \
  --parameter L=0.5[mm] \
  --expression T \
  --max-cases 1
```

This verifies that the LLM can see and select `simulation_run_parameter_sweep`,
that the Agent loop dispatches it through the registry, and that the real COMSOL
runtime completes the requested sweep case.

Run the P5 end-to-end demo sequence:

```bash
.venv/bin/python scripts/run_agent_fullflow_demo.py --cores 1 \
  --archive-path runtime_smoke/fullflow_demo.sqlite3 \
  --artifact-root runtime_smoke/fullflow_demo \
  --report-dir runtime_smoke/fullflow_demo/reports \
  --max-cases 1
```

This asks the agent to:

1. search, validate, and run the thermal template on a newly created model;
2. run a small parameter sweep and export an HTML report;
3. inspect the archived sweep artifact and recommend next steps.

For offline review without calling DeepSeek or COMSOL, print the reproducible
prompt fixture:

```bash
.venv/bin/python scripts/run_agent_fullflow_demo.py --print-prompts
```

Run the bearing-contact agent demo fixture:

```bash
.venv/bin/python scripts/run_agent_bearing_contact_demo.py --print-prompts
.venv/bin/python scripts/run_agent_bearing_contact_demo.py --cores 1 \
  --archive-path runtime_smoke/bearing_contact_demo.sqlite3 \
  --artifact-root runtime_smoke/bearing_contact_demo \
  --report-dir runtime_smoke/bearing_contact_demo/reports
```

## 3D Full Roller Bearing + Cage Demo

The 3D full-bearing demo is the next-stage generated-code path beyond the 2D
multiroller smoke. The main verified fixture is 3D, includes an inner ring, an
outer ring, six cylindrical rollers, a simplified cage ring with six
pocket/constraint point markers, explicit roller/raceway Contact pair features,
assembly finalization, a radial smoke load, a stationary Solid Mechanics study,
and a `PlotGroup3D` von Mises result.

Inspect the reproducible 3D prompt fixtures without calling LLM or COMSOL:

```bash
python3 scripts/run_agent_3d_bearing_full_demo.py --print-prompts
```

Check the verified 3D full-bearing fixture without starting COMSOL:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --use-verified-fixture --skip-comsol
```

Run the free-generation 3D draft path without COMSOL. The draft step now extracts
the first fenced `model.*` code block inside `GENERATED_CODE_START/END`, ignores
prose outside the fence, normalizes common Java-ish literals such as `true`, quoted `{...}` arrays,
and `new double[]`/`new String[]`/`new int[]` array literals into Python/MPh syntax, and records that as
`offline_syntax_normalization`. In strict mode the script fails rather than
replacing the generated draft with the complete verified fallback:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --skip-comsol --require-free-generated-code
```

Run the direct 3D fixture smoke against local COMSOL:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run --cores 1
```

Latest verified local COMSOL 6.2 Agent execution with scoped per-roller probes
using DeepSeek `deepseek-v4-pro` free-generated code plus bounded repairs, with
no deterministic full-code fallback:

- Template execution run id:
  `agent_3d_bearing_execution_v2_20260701_053449_685816`
- Result package run id:
  `agent_3d_bearing_package_agent_3d_bearing_model_20260701_053659_501236`
- von Mises stress maximum: about `3.691e6` Pa
- Contact pressure estimate: about `3.906e6` Pa
- Stress PNG:
  `runtime_smoke/bearing_3d_full_demo/bearing_3d_von_mises.png`
- Package JSON:
  `runtime_smoke/bearing_3d_full_demo/result_packages/agent_3d_bearing_package_agent_3d_bearing_model_20260701_053659_501236/summary.json`
- Package Markdown:
  `runtime_smoke/bearing_3d_full_demo/result_packages/agent_3d_bearing_package_agent_3d_bearing_model_20260701_053659_501236/report.md`
- Package HTML:
  `runtime_smoke/bearing_3d_full_demo/result_packages/agent_3d_bearing_package_agent_3d_bearing_model_20260701_053659_501236/report.html`
- Model:
  `runtime_smoke/bearing_3d_full_demo/result_packages/agent_3d_bearing_package_agent_3d_bearing_model_20260701_053659_501236/agent_3d_bearing_model.mph`
- Latest direct fixture with the same named-selection code:
  `direct_3d_bearing_package_agent_3d_bearing_model_20260630_082155_984572`
- Observed free-generation repair is recorded in the latest full draft chain:
  the LLM draft called the required planning and generated-code tools. The
  extractor kept fenced `model.*` code, `offline_syntax_normalization` converted
  Java-style literals to Python/MPh syntax, and
  `offline_runtime_preflight_repair` made only small generated-code repairs:
  removed 18 unsupported cylinder `ax` property setters, converted one
  standalone `geom.finalize('assembly')` call to the verified `fin` assembly
  action, and converted one generated `Finish` feature create/run block to the
  same verified assembly idiom. The package summary records
  `deterministic_runtime_fallback: null`; the full verified fallback code was
  not used for this latest strict run.
- Artifact Q&A evidence now includes verified scoped per-roller stress probes
  using component `Maximum` coupling operators bound to roller-body selections.
  The 3D package writes an `artifact_qa` block into `summary.json` and mirrors
  the answers in `report.md`/`report.html` for common follow-up questions about
  maximum stress, stress location, highest-risk roller, cage modeling, contact
  status, parameters, and plot/model paths.
  The stress PNG is a non-empty projection rendered from solved COMSOL
  `x`/`y`/`solid.mises` field samples (`stress_plot_method`: `mph_evaluate_xy_projection_png`),
  which avoids sparse/blank COMSOL GUI image exports while preserving solved-field provenance.
  `roller_1` is the first highest-risk roller in the current symmetric smoke
  ranking; all six rollers currently report the same scoped maximum because the
  smoke load/support setup is intentionally symmetric at this stage.
- The package also records `selection_plan`: target named selections for
  inner/outer raceway contacts, each roller body/contact patch, cage body,
  outer support surface, inner load region, and per-roller max-stress probes.
  `validate_3d_bearing_code_draft(require_named_selections=True)` is the
  production gate. The current fixture has
  named Box selections for each roller body/contact region, twelve per-roller
  roller/raceway Contact Pairs, and per-roller max-stress numerical probe
  nodes backed by component Maximum coupling operators.

Current 3D modeling limits:

- The model is a full 360-degree 3D smoke with six rollers and included cage,
  but the cage pockets are point/constraint markers rather than cut pocket
  windows in the cage solid.
- Contact/load/support now use named Box region selections rather than `.all()`,
  and each roller body/contact region has a named Box selection plus scoped
  max-stress probe. Production still needs stronger contact convergence checks
  and non-symmetric load cases before design use.
- The 2D multiroller demo remains only a fast regression smoke and is not the
  final answer for requests that explicitly require full 3D plus cage.

## Current verified local environment

- COMSOL version: 6.2
- MPh version: 1.3.1
- Configured executable: `/Applications/COMSOL62/Multiphysics/bin/comsol`
- Discovered backend root: `/Applications/COMSOL62/multiphysics`
- Discovered server: `/Applications/COMSOL62/multiphysics/bin/macarm64/comsol mphserver`

## Sandbox note

Starting COMSOL from a restricted sandbox can fail because COMSOL writes logs
under `~/Library/Preferences/COMSOL/...` and probes local ports. The
non-invasive probe can run in the sandbox, but `--start` and `--create-smoke`
should be run without filesystem/network sandbox restrictions.
