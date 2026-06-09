# Development Progress and Roadmap

Last updated: 2026-06-09

This document records the current pause point for COMSOL Agent development and
the recommended plan for the next development pass.

## Current Pause Point

The project has moved beyond the original architecture skeleton into a working
local agent prototype:

- DeepSeek is configured through the OpenAI-compatible provider path. The API
  key is stored in local user configuration and must not be copied into source,
  docs, tests, or scripts.
- Local COMSOL 6.2 integration is available through the MPh bridge and the
  project COMSOL tool layer.
- Core CLI, AgentLoop, tool registry, repair reporting, memory/archive records,
  simulation artifacts, parameter sweeps, report export, template management,
  template validation, template execution artifacts, and template execution
  replay/reporting are implemented.
- The latest full offline test run passed:

```bash
python3 -m compileall -q comsol_agent tests scripts
python3 -m pytest -q
# 107 passed, 1 skipped
```

The current working directory is now a Git repository on branch `main`, tracking
`origin/main` at `git@github.com:m0onquake/ComsolCodeAgent.git`.

## Implemented Capabilities

### Runtime and Diagnostics

- `scripts/doctor_runtime.py` supports shallow runtime checks and explicit deep
  checks for LLM and COMSOL.
- `/doctor`, `/doctor --deep`, `/doctor --llm-only`, and `/doctor --comsol-only`
  are available in the interactive CLI.
- COMSOL runtime probes and smoke scripts exist for tool-layer operations,
  model solve/evaluate, examples, sweeps, and agent-driven COMSOL workflows.

### LLM Provider Layer

- DeepSeek is supported through the existing OpenAI-compatible provider path.
- Routing includes DeepSeek-aware defaults.
- Tool-call behavior has dedicated smoke scripts.
- Sensitive API material is intentionally excluded from project files.

### COMSOL Tool Layer

- Model operations:
  - `comsol_load_model`
  - `comsol_create_model`
  - `comsol_set_parameter`
  - `comsol_list_parameters`
  - `comsol_list_models`
  - `comsol_save_model`
  - `comsol_close_model`
- Solve and evaluation:
  - `comsol_solve`
  - `comsol_evaluate`
  - `comsol_get_model_summary`
  - `comsol_execute_java`
- Export and plotting:
  - `comsol_export_results`
  - `comsol_plot`

Recent maintenance note: `COMSOLClient.execute_java()` now indents multi-line
Java/API snippets before embedding them in its Python `try:` wrapper. This fixes
the syntax failure seen when executing multi-line templates.

### Simulation Workflows

- Offline parameter sweep planning is implemented.
- Real parameter sweep execution is implemented through
  `simulation_run_parameter_sweep`.
- Built-in example model execution is implemented through
  `simulation_run_example_model`.
- Sweep rerun support is implemented through `simulation_rerun_artifact`.
- Sweep and template execution rerun support is implemented through
  `simulation_rerun_artifact`.
- Sweep comparison plus Markdown/HTML report export are implemented.
- Template execution Markdown/HTML report export is implemented.

### Archive and Memory

- SQLite archive storage tracks:
  - sessions
  - memories
  - reusable simulation templates
  - simulation artifacts
- CLI commands are available for sessions, artifacts, archive export, and
  cleanup.
- Archive export and cleanup scripts are available.
- For sandboxed tests and smoke runs, prefer workspace archives such as
  `runtime_smoke/*.sqlite3` instead of the default user archive.

### Template System

Implemented template capabilities:

- `simulation_list_templates`
- `simulation_search_templates`
- `simulation_read_template`
- `simulation_save_template`
- `simulation_export_template`
- `simulation_validate_template`
- `simulation_run_template`

Interactive commands:

```text
/templates
/templates domain thermal
/templates search heat thermal
/templates show thermal_heat_transfer_seed
/templates validate thermal_heat_transfer_seed
/templates export thermal_heat_transfer_seed runtime_smoke/templates/thermal_heat_transfer_seed.java
/templates run thermal_heat_transfer_seed create template_smoke_model
/templates save custom_thermal thermal runtime_smoke/templates/custom_thermal.java runtime_smoke/templates/custom_thermal.params.json
```

Script entry points:

```bash
.venv/bin/python scripts/list_templates.py --seed-builtins --domain thermal
.venv/bin/python scripts/list_templates.py --validate thermal_heat_transfer_seed
.venv/bin/python scripts/list_templates.py \
  --validate-file runtime_smoke/templates/thermal_heat_transfer_seed.java \
  --params-json '{"power": "10[W]", "T_ambient": "293.15[K]"}'
.venv/bin/python scripts/list_templates.py \
  --run thermal_heat_transfer_seed \
  --create-model-name template_smoke_model \
  --artifact-dir runtime_smoke/template_runs \
  --cores 1
```

Template export path safety follows the same model as file tools:

- default allowed roots: project workspace and `~/.comsol_agent`
- extra trusted roots: `COMSOL_AGENT_ALLOWED_PATHS`

## Verification Record

Confirmed in the latest development pass:

- Python compilation passed for `comsol_agent`, `tests`, and `scripts`.
- Full unit test suite passed with `107 passed, 1 skipped`.
- `scripts/list_templates.py --validate thermal_heat_transfer_seed` passed
  earlier against a workspace archive.
- `scripts/list_templates.py --validate-file ...` passed earlier against the
  exported Java template.
- A real COMSOL template-run smoke passed with elevated permissions. COMSOL
  startup, model creation, Java/API template execution, model close, artifact
  writing, and archive indexing all succeeded.
- The generated artifact was read back through `scripts/read_artifact.py`, and
  `simulation_search_artifacts("template_smoke_model")` found the
  `template_execution` archive record with `execution_success: true`.
- During this pass, two Java/API execution wrapping issues were fixed:
  multi-line snippets are now indented before `exec`, and Java-style `//` line
  comments are stripped before execution.

Verified real template execution command:

```bash
.venv/bin/python scripts/list_templates.py \
  --archive-path runtime_smoke/template_run_real.sqlite3 \
  --seed-builtins \
  --run thermal_heat_transfer_seed \
  --create-model-name template_smoke_model \
  --artifact-dir runtime_smoke/template_runs \
  --cores 1
```

If this is run from the Codex sandbox, COMSOL may require elevated execution
because it writes logs under `~/Library/Preferences/COMSOL/...` and probes local
ports.

## Known Constraints and Risks

- The repository is now tracked in Git and pushed to GitHub. Keep committing
  small verified increments and avoid committing runtime archives, `.mph`
  outputs, `.venv`, or local configuration.
- Real COMSOL runs may fail in a restricted sandbox unless COMSOL can write to
  user preference/log directories and probe local ports.
- `simulation_validate_template` is intentionally a conservative offline lint,
  not a Java compiler and not a physics validator.
- `simulation_run_template` executes Java/API seed code against an explicit
  loaded model or a newly created model. It should remain explicit about the
  target model to avoid modifying the wrong COMSOL model.
- The default archive under `~/.comsol_agent` can be inconvenient in sandboxed
  tests. Continue using workspace archive paths for smoke tests.
- Template execution is verified for the current built-in thermal seed template.
  More complex geometry/physics templates still need real COMSOL validation.

## Next Development Plan

### P0: Re-verify Template Execution Against Real COMSOL

Goal: prove the full `template -> validate -> run -> artifact -> archive`
workflow after the multi-line execution fix.

Status: complete for `thermal_heat_transfer_seed` on a newly created smoke
model.

Tasks:

1. Done: reran the real template smoke command listed above.
2. Done: confirmed that `simulation_run_template` returns `success: true`.
3. Done: confirmed that a `template_execution` artifact is indexed in the workspace
   archive.
4. Done: confirmed `simulation_search_artifacts("template_smoke_model")` and
   `scripts/read_artifact.py <run_id>` can read the generated artifact.
5. Optional: add or update a dedicated real smoke script if the generic
   `scripts/list_templates.py --run` command feels too overloaded.

Exit criteria:

- Real COMSOL execution succeeds.
- JSON and manifest artifacts are written under `runtime_smoke/template_runs`.
- Archive lookup can read the generated `template_execution` record.

### P1: Harden Java/API Execution

Goal: make `comsol_execute_java` safer, easier to debug, and better aligned
with the repair system.

Status: core tool hardening complete. Future repair-specific prompt tuning can
build on the new structured fields.

Tasks:

1. Done: added focused unit tests for multi-line Java/API execution wrapping.
2. Done: return structured fields from `comsol_execute_java`, such as `stdout`,
   `error`, and `exception_type`, instead of only a single output string.
3. Done: record whether execution marked the model as modified.
4. Done: added optional dry-run validation that reuses `simulation_validate_template`.
5. Done: improved error classification so repair reports can identify syntax, API, and
   runtime failures separately.

Exit criteria:

- Multi-line snippets are covered by tests.
- Failure payloads are structured enough for the repair analyzer.
- Existing COMSOL template smoke still passes with the structured execution payload.

### P2: Build Local COMSOL Docs RAG

Goal: upgrade the current local keyword search into a practical COMSOL API
retrieval layer for repair and code generation.

Status: deterministic offline retrieval foundation complete. A future pass can
replace or augment keyword scoring with embeddings/vector storage.

Tasks:

1. Done: index local Markdown documentation and exported snippets inside the workspace.
2. Done: store chunk metadata with source file, API symbols, version mentions, and
   domain.
3. Done: add `simulation_retrieve_api_docs`, which returns compact, cited API snippets.
4. Done: repair prompts now use compact cited snippets from the local retrieval layer.
5. Done: add offline tests for metadata extraction and deterministic retrieval.

Exit criteria:

- The agent can retrieve relevant local COMSOL API references without network
  access.
- Repair prompts include source-grounded API context.

### P3: Strengthen Reproducible Experiment Records

Goal: make every meaningful COMSOL action reproducible from archive records.

Status: template execution records are now reproducible from archive snapshots.
Example-model runs and direct Java/API calls still need dedicated artifact types
before they can be replayed with the same fidelity.

Tasks:

1. Done for template runs: artifact metadata now records template name/domain,
   params, validation counts, execution error classification, and tool sequence.
   Deferred: define first-class artifact records for example-model runs and raw
   Java/API calls.
2. Done: added replay support for `template_execution` artifacts through
   `simulation_rerun_artifact`.
3. Done: report export handles `template_execution` artifacts as Markdown/HTML
   reports and archives them as `template_execution_report`.
4. Done: added compact CLI views through `/artifacts template-runs <query>` and
   `/artifacts report-template <query> [markdown|html|both]`.

Exit criteria:

- A template execution can be rerun or inspected from its archive record.
- Reports can summarize both sweep and template execution records.

### P4: Improve CLI Product Shape

Goal: make the CLI easier to use during real engineering work.

Status: core CLI usability pass complete. Future work can still add richer
interactive confirmations, but risky loaded-model template execution is now
explicitly flagged.

Tasks:

1. Done: added detailed `/help templates` and `/templates help` subcommand help.
2. Done: `/templates run ... model <model_name>` now requires
   `--allow-modify-loaded` before modifying an existing loaded COMSOL model.
3. Done: template validation findings and artifact paths render as structured
   CLI tables.
4. Done: startup status panel shows LLM provider/model, COMSOL configuration,
   archive path, session path, and secret presence without printing secrets.

Exit criteria:

- Common commands are discoverable from `/help`.
- Risky model-modifying actions are visibly explicit.

### P5: End-to-End Agent Demonstrations

Goal: demonstrate that DeepSeek can orchestrate the implemented workflow.

Status: reproducible P5 demo script and offline prompt fixture are implemented.
The real COMSOL/DeepSeek run remains an environment-dependent smoke check.

Tasks:

1. Done: `scripts/run_agent_fullflow_demo.py` asks the agent to find a thermal
   template, validate it, run it on a new model, and report the artifact path.
2. Done: the same script asks the agent to run a small parameter sweep and
   export an HTML report.
3. Done: the script extracts the sweep artifact run id and asks the agent to
   inspect it with `simulation_read_artifact` before recommending next steps.
4. Done: `--print-prompts` emits the reproducible prompt fixture without
   starting DeepSeek or COMSOL.

Exit criteria:

- DeepSeek tool calling, COMSOL runtime, archive records, and reporting all work
  together in repeatable demos.

## Resume Checklist

When continuing development:

1. Read this file and `docs/comsol_runtime.md`.
2. Run:

```bash
python3 -m compileall -q comsol_agent tests scripts
python3 -m pytest -q
```

3. Rerun the real template execution smoke with COMSOL.
4. If the smoke passes, proceed with P1.
5. If it fails, inspect the generated `runtime_smoke/template_runs/*.json`
   artifact and repair the lowest-level failure first.

## Pause Decision

Development can pause here. The project has a tested offline state and a clear
next real-runtime verification step. The most important unfinished verification
is the post-patch real COMSOL template execution smoke.
