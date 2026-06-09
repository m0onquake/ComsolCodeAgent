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
- `simulation_list_artifacts`: list recent archived simulation artifacts
- `simulation_search_artifacts`: search by run id, model name, source, paths, or metadata
- `simulation_read_artifact`: read a compact preview of a specific archived run or report
- `simulation_compare_artifacts`: compare archived sweep CSV metrics and rank cases
- `simulation_export_artifact_report`: export a Markdown report from archived sweep comparisons
- `simulation_retrieve_api_docs`: retrieve compact, cited local documentation snippets for API repair/code generation

For isolated tests or project-specific archives, pass `archive_path` to
`simulation_run_parameter_sweep` and to the list/search tools.

Inside the interactive CLI, use slash commands for quick artifact review:

```text
/templates
/templates domain thermal
/templates search heat thermal
/templates show thermal_heat_transfer_seed
/templates validate thermal_heat_transfer_seed
/templates run thermal_heat_transfer_seed create template_smoke_model
/templates export thermal_heat_transfer_seed runtime_smoke/templates/thermal_heat_transfer_seed.java
/templates save custom_thermal thermal runtime_smoke/templates/custom_thermal.java runtime_smoke/templates/custom_thermal.params.json
/artifacts
/artifacts search agent_sweep_smoke
/artifacts show agent_sweep_smoke_20260608_194443_628426
/artifacts compare agent_sweep_smoke mean T max
/artifacts report agent_sweep_smoke mean T max
/artifacts report agent_sweep_smoke mean T max html
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

Template export uses the same local path safety model as file tools. Output
paths are allowed under the project workspace and `~/.comsol_agent` by default.
For an additional trusted directory, set:

```bash
export COMSOL_AGENT_ALLOWED_PATHS=/path/to/extra/workdir
```

`/templates run` and `scripts/list_templates.py --run` start or use a real
COMSOL session through the normal tool layer. Use `create <model_name>` /
`--create-model-name` for isolated smoke checks, or `model <model_name>` /
`--model-name` only when you intend to modify an already loaded model.

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
write `<report_id>.html`. Reports are indexed in the archive as
`comparison_report` artifacts, so they can be found later with
`/artifacts search <report_name>`.

Replay an archived sweep through the real COMSOL runtime:

```bash
.venv/bin/python scripts/rerun_sweep_artifact.py \
  agent_sweep_smoke_20260608_194443_628426 \
  --parameter L=0.75[mm] \
  --expression T \
  --max-cases 1 \
  --artifact-name replay_agent_sweep
```

The Agent-facing tool is `simulation_rerun_artifact`. It reads the archived JSON
record, reconstructs the original model source, parameter axes, and output
expressions, then applies optional `parameter_overrides` and
`expression_overrides` before calling `simulation_run_parameter_sweep` again.
Artifacts from the replay are persisted and indexed as a new run.

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
