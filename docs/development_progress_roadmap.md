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
  template validation, and initial template execution artifacts are implemented.
- The latest full offline test run passed:

```bash
python3 -m compileall -q comsol_agent tests scripts
python3 -m pytest -q
# 96 passed, 1 skipped
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
- Sweep comparison and Markdown/HTML report export are implemented.

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
- Full unit test suite passed with `96 passed, 1 skipped`.
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

Tasks:

1. Add a focused unit test for multi-line Java/API execution wrapping.
2. Return structured fields from `comsol_execute_java`, such as `stdout`,
   `error`, and `exception_type`, instead of only a single output string.
3. Record whether execution modified the model.
4. Add optional dry-run validation that reuses `simulation_validate_template`.
5. Improve error classification so repair reports can identify syntax, API, and
   runtime failures separately.

Exit criteria:

- Multi-line snippets are covered by tests.
- Failure payloads are structured enough for the repair analyzer.
- Existing COMSOL smoke scripts still pass.

### P2: Build Local COMSOL Docs RAG

Goal: upgrade the current local keyword search into a practical COMSOL API
retrieval layer for repair and code generation.

Tasks:

1. Index local COMSOL documentation, examples, and exported snippets.
2. Store chunk metadata with source file, API class/function, version, and
   domain.
3. Add a retrieval tool that returns compact, cited API snippets.
4. Feed retrieved docs into repair prompts for API errors.
5. Add offline tests for indexing and deterministic retrieval.

Exit criteria:

- The agent can retrieve relevant local COMSOL API references without network
  access.
- Repair prompts include source-grounded API context.

### P3: Strengthen Reproducible Experiment Records

Goal: make every meaningful COMSOL action reproducible from archive records.

Tasks:

1. Extend artifact metadata for template runs, example runs, and Java/API runs.
2. Add replay support for `template_execution` artifacts.
3. Make report export handle template execution artifacts, not just sweeps.
4. Add a compact CLI view for template run results.

Exit criteria:

- A template execution can be rerun or inspected from its archive record.
- Reports can summarize both sweep and template execution records.

### P4: Improve CLI Product Shape

Goal: make the CLI easier to use during real engineering work.

Tasks:

1. Add detailed help for `/templates` subcommands.
2. Add confirmation prompts or explicit flags for operations that modify loaded
   COMSOL models.
3. Add richer rendering for validation findings and artifact paths.
4. Add a startup status panel that shows LLM provider, COMSOL configuration, and
   archive path without printing secrets.

Exit criteria:

- Common commands are discoverable from `/help`.
- Risky model-modifying actions are visibly explicit.

### P5: End-to-End Agent Demonstrations

Goal: demonstrate that DeepSeek can orchestrate the implemented workflow.

Tasks:

1. Ask the agent to find a thermal template, validate it, run it on a new model,
   and report the artifact path.
2. Ask the agent to run a small parameter sweep and export an HTML report.
3. Ask the agent to inspect a previous artifact and recommend next steps.
4. Save each demo as a smoke script or reproducible prompt fixture.

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
