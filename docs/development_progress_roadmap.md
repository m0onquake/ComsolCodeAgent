# Development Progress and Roadmap

Last updated: 2026-06-13

This document records the current pause point for COMSOL Agent development and
the recommended plan for the next development pass.

## Current Pause Point

The project has moved beyond the original architecture skeleton into a working
local agent prototype:

- Product direction: this is a generative COMSOL simulation assistant. Built-in
  templates are reusable starting points and regression/smoke fixtures, not the
  only way the agent should create simulations. When no template fits, the
  agent should be able to generate COMSOL Java/API code directly from the user
  request by injecting a controlled code-generation prompt block with modeling
  intent, constraints, retrieved COMSOL API snippets, output-format rules, and
  validation requirements.
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
# 120 passed, 1 skipped
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
- The intended simulation creation policy is template-first but not
  template-only. The agent should search templates first for reproducibility and
  speed; if no template matches the user's geometry/physics/study requirements,
  it should enter a controlled generated-code path that drafts new COMSOL
  Java/API setup code, validates it offline, optionally saves it as a reusable
  template, executes it against an explicit model, and archives the result.
- The first P7 generated-code fallback tool and smoke script are implemented:
  `simulation_plan_generated_code` builds the controlled prompt scaffold and
  `scripts/run_generated_code_fallback_smoke.py` verifies raw Java/API code can
  flow through validation, execution, solve/evaluate/plot, archive, and template
  promotion without relying on a pre-existing template.
- A lightweight deterministic `RequirementState` now accumulates multi-turn
  user requirements and fills missing `simulation_plan_generated_code`
  `known_params` slots before planning, covering geometry, physics, material,
  boundary/load conditions, contact requirements, entity binding, calibration,
  outputs, and user preferences.
- The bearing-contact agent demo path now supports two built-in bearing
  templates: `bearing_contact_hertz_seed` for the lighter Hertz-style pressure
  workflow, and `bearing_contact_pair_seed` for a more realistic 2D COMSOL
  Contact-pair workflow. It gives the agent a default deep-groove ball-bearing
  contact case, a missing-parameter/default policy, and a reproducible prompt
  fixture for template execution, solving, evaluation, plot export, packaging,
  and reporting.

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
- `simulation_plan_generated_code`

Templates are part of the agent's memory and quality-control system, not a
hard limit on what it can model. Future development should add a generated-code
workflow beside the template workflow:

1. Clarify the physical problem, required outputs, and missing parameters.
2. Retrieve local COMSOL API/docs snippets relevant to the requested domain.
3. Inject a controlled code-generation prompt block asking the LLM to return
   only COMSOL Java/API setup code plus a compact parameter manifest.
4. Run `simulation_validate_template` on the generated code before execution.
5. If validation passes, execute through `simulation_run_template` or
   `comsol_execute_java` against an explicit model; if it fails, use the repair
   loop and retrieved API snippets.
6. Save successful generated code as a reusable template when it is likely to
   be useful again.

Built-in template domains now include two structural bearing-contact seeds:

- `bearing_contact_hertz_seed`: default deep-groove ball-bearing contact setup
  using a tractable 2D plane-strain single-ball/raceway Hertz-style contact cell.
  It is intended to run the agent/tool/archive workflow before escalating to a
  heavier full 3D multi-ball contact model.
- `bearing_contact_pair_seed`: default deep-groove ball-bearing contact setup
  using an explicit COMSOL `Contact` pair between the generated ball and
  raceway boundaries. It is still a tractable 2D single-ball/raceway cell, but
  it exercises COMSOL's real contact-pair API and is the preferred template when
  the user asks for a more realistic contact simulation.

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
.venv/bin/python scripts/run_agent_bearing_contact_demo.py --print-prompts
.venv/bin/python scripts/run_bearing_contact_template_smoke.py --cores 1 --skip-solve
```

Template export path safety follows the same model as file tools:

- default allowed roots: project workspace and `~/.comsol_agent`
- extra trusted roots: `COMSOL_AGENT_ALLOWED_PATHS`

## Verification Record

Confirmed in the latest development pass:

- Python compilation passed for `comsol_agent`, `tests`, and `scripts`.
- Full unit test suite passed with `120 passed, 1 skipped`.
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
- The P5 real fullflow demo passed with DeepSeek, local COMSOL, workspace
  archive records, HTML report export, and artifact inspection.
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

Verified real P5 fullflow command:

```bash
.venv/bin/python scripts/run_agent_fullflow_demo.py --cores 1 \
  --archive-path runtime_smoke/fullflow_demo.sqlite3 \
  --artifact-root runtime_smoke/fullflow_demo \
  --report-dir runtime_smoke/fullflow_demo/reports \
  --max-cases 1
```

Latest successful fullflow records:

- Template run: `agent_fullflow_template_20260612_194538_230532`
- Sweep run: `agent_fullflow_sweep_20260612_194550_032970`
- HTML report: `agent_fullflow_sweep_report_20260612_194559_722856`

If this is run from the Codex sandbox, COMSOL may require elevated execution
because it writes logs under `~/Library/Preferences/COMSOL/...` and probes local
ports.

## Known Constraints and Risks

- The repository is now tracked in Git and pushed to GitHub. Keep committing
  small verified increments and avoid committing runtime archives, `.mph`
  outputs, `.venv`, or local configuration.
- LLM-generated COMSOL code must be treated as untrusted until it passes the
  controlled generated-code pipeline: local API retrieval, prompt-scoped output,
  offline validation, explicit-model execution, artifact capture, and review.
  Do not bypass validation or run generated snippets against an arbitrary loaded
  model.
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
- The bearing-contact default path is implemented and covered by offline tests.
  Real COMSOL smoke testing has reached model setup, template execution,
  stationary solve, nonzero stress evaluation, and PNG stress-image export.
  The DeepSeek-driven agent demo has also completed the deterministic
  template/solve/evaluate/plot/archive/report workflow.
  True contact-pair setup and production-grade boundary/contact selections
  remain the next COMSOL API targets.

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

Status: complete. The real COMSOL/DeepSeek fullflow demo passed and produced
workspace archive/report artifacts.

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

### P6: Bearing Contact Simulation Agent Path

Goal: make the agent capable of handling a realistic bearing-contact request by
asking for missing parameters or using a default demo case, then producing
COMSOL setup code, execution artifacts, and stress/contact-result guidance.

Status: first realistic contact-pair workflow complete for the default 2D
single-ball/raceway case. Real COMSOL smoke validation now reaches template
setup, explicit `Contact` pair creation, stationary solve, nonzero von Mises
stress evaluation, contact-pressure estimate evaluation, PNG plot export, and
result packaging. The real DeepSeek agent demo now follows the intended
high-level tool sequence with `bearing_contact_pair_seed` and exports a
template execution report. A deterministic bearing-contact planning tool now
decides whether the agent should ask follow-up questions or run the default demo
with stated assumptions.

Implemented:

1. Added `bearing_contact` as a structural simulation skill with keywords for
   ball bearings, raceways, Hertz/Hertzian contact, and Chinese user queries
   such as "轴承" and "接触".
2. Added `bearing_contact_hertz_seed`, with default parameters for a deep-groove
   ball bearing: 25 mm inner diameter, 52 mm outer diameter, 15 mm width,
   8 balls, 7.94 mm ball diameter, 1000 N radial load, bearing steel, small
   interference, friction coefficient, and contact mesh-size assumptions.
3. Added `bearing_contact_pair_seed`, a 2D single-ball/raceway template with an
   explicit COMSOL Contact pair `cp_ball_race`, manual source/destination
   boundary selections, Solid Mechanics Contact feature binding through
   `pairs`, stationary solve setup, stress plot group, and result numerical
   features.
4. Updated the system prompt so the agent distinguishes between parameters that
   require follow-up questions and quick-demo requests where defaults are
   acceptable, and uses the planner-selected template (`bearing_contact_pair_seed`
   for more realistic/contact-pair requests; `bearing_contact_hertz_seed` for
   the lighter quick demo).
5. Added `scripts/run_agent_bearing_contact_demo.py`, including `--print-prompts`
   for offline fixture review and a real mode that seeds templates, starts
   COMSOL, runs the agent, keeps the model open for solving/evaluation, archives
   template execution, and exports an HTML template execution report.
6. Added `scripts/run_bearing_contact_template_smoke.py` for direct local COMSOL
   validation without LLM variability.
7. Hardened `comsol_plot` so generated models without MPh's default
   `exports/image` node can still create PNG output through a COMSOL Java
   `Image2D` export node.
8. Added `simulation_plan_bearing_contact`, an offline planning tool that turns
   a natural-language bearing request plus known parameters into:
   `ready_to_run`, missing required parameters, follow-up questions, resolved
   defaults, assumptions, recommended outputs, and next tool steps.
9. Added `simulation_export_bearing_contact_package` to save a solved bearing
   model, re-evaluate `solid.mises` and `contact_pressure_guess`, capture the
   stress PNG path, write summary JSON/Markdown, and index a
   `bearing_contact_package` artifact.
10. Added compact artifact-reader previews for `bearing_contact_package` records.

Default modeling scope:

- The default realistic case is a 2D single-ball/raceway contact cell with an
  explicit COMSOL Contact pair, not a full 3D multi-ball bearing assembly.
- The expected outputs are von Mises stress, displacement, estimated/contact
  pressure, JSON/template-execution artifacts, report paths, and a PNG stress
  image. The contact-pair smoke model now produces nonzero stress and solves
  locally; boundary IDs and mesh/contact convergence still need review before
  production use.

Runtime validation on local COMSOL 6.2:

- `simulation_plan_bearing_contact` returns `ready_to_run=false` with concise
  follow-up questions for underspecified production-like requests, and
  `ready_to_run=true` with defaults for quick/default demos. It recommends
  `bearing_contact_pair_seed` for realistic/contact-pair requests.
- `scripts/list_templates.py --run bearing_contact_hertz_seed ...` now succeeds
  for template setup and archives a `template_execution` artifact.
- `scripts/run_bearing_contact_template_smoke.py --template-name
  bearing_contact_pair_seed --cores 1 ...` succeeds through explicit Contact
  pair setup, stationary solve, evaluation, plot export, and package export.
  Latest observed values:
  - `solid.mises`: maximum about `2.748e8` Pa.
  - `contact_pressure_guess`: about `1.847e6` in SI units.
- `scripts/run_bearing_contact_template_smoke.py --cores 1 --skip-solve`
  succeeds for direct model setup and archival.
- `scripts/run_bearing_contact_template_smoke.py --cores 1` succeeds through
  default stationary solve and evaluates:
  - `solid.mises`: nonzero array result; latest observed maximum is about
    `2.502e8` Pa for the default smoke case.
  - `contact_pressure_guess`: approximately `1.847e6` in SI units for the
    default load-sharing estimate.
- `comsol_plot` now falls back to COMSOL Java image-export nodes when MPh's
  default `export("image", ...)` path is missing. The direct smoke test writes
  `runtime_smoke/bearing_contact_template_smoke/von_mises.png`.
- `scripts/run_agent_bearing_contact_demo.py --cores 1 ...` succeeded with
  DeepSeek and local COMSOL using `bearing_contact_pair_seed`. Latest observed
  records:
  - Template execution run id:
    `agent_bearing_contact_default_20260612_211357_487968`
  - Result package run id:
    `agent_bearing_contact_package_agent_bearing_contact_model_20260612_211414_810946`
  - Stress PNG:
    `runtime_smoke/bearing_contact_demo_pair_plotfix/bearing_contact_von_mises.png`
  - Saved `.mph` model:
    `runtime_smoke/bearing_contact_demo_pair_plotfix/result_packages/agent_bearing_contact_package_agent_bearing_contact_model_20260612_211414_810946/agent_bearing_contact_model.mph`
  - Package Markdown:
    `runtime_smoke/bearing_contact_demo_pair_plotfix/result_packages/agent_bearing_contact_package_agent_bearing_contact_model_20260612_211414_810946/report.md`
  - HTML report:
    `runtime_smoke/bearing_contact_demo_pair_plotfix/reports/agent_bearing_contact_report_20260612_211429_965355.html`
  - Agent-observed tool sequence:
    `simulation_plan_bearing_contact -> simulation_search_templates -> simulation_read_template -> simulation_validate_template -> simulation_run_template -> comsol_solve -> comsol_evaluate -> comsol_evaluate -> comsol_plot -> simulation_export_bearing_contact_package -> comsol_close_model`

Next runtime checkpoint:

```bash
.venv/bin/python scripts/run_agent_bearing_contact_demo.py --print-prompts
.venv/bin/python scripts/list_templates.py --seed-builtins --validate bearing_contact_pair_seed
.venv/bin/python scripts/list_templates.py --seed-builtins --validate bearing_contact_hertz_seed
.venv/bin/python scripts/run_bearing_contact_template_smoke.py --cores 1 --template-name bearing_contact_pair_seed
```

Then, with COMSOL permissions available:

```bash
.venv/bin/python scripts/run_agent_bearing_contact_demo.py --cores 1 \
  --archive-path runtime_smoke/bearing_contact_demo.sqlite3 \
  --artifact-root runtime_smoke/bearing_contact_demo \
  --report-dir runtime_smoke/bearing_contact_demo/reports
```

Next implementation details:

1. Replace the current contact-pair smoke boundary IDs with named geometry/contact
   selections so fixed raceway and loaded ball/groove boundaries are robust
   across geometry changes.
2. Add a production-result report that includes contact-pair convergence checks,
   contact pressure extraction, and mesh-sensitivity status.
3. Add a heavier optional 3D multi-ball model path after the 2D contact cell's
   real contact pair produces stable results.

### P7: Generative COMSOL Code Path

Goal: make the agent capable of creating COMSOL simulations that are not already
covered by the template library. Templates remain preferred when they fit, but
the main product direction is a generative COMSOL assistant that can draft,
validate, execute, repair, archive, and optionally promote new Java/API setup
code.

Status: initial implementation complete for the controlled planning layer and a
real raw-code smoke. The lower-level pieces already exist: local docs retrieval,
template validation, `comsol_execute_java`, `simulation_run_template`, repair
reports, archive records, and template saving. The first pass connected them
through `simulation_plan_generated_code`, updated the system prompt, and added
`scripts/run_generated_code_fallback_smoke.py` as a non-template raw-code
workflow smoke.

Required behavior:

1. Done for the planning tool: start every new simulation request by
   classifying the domain, physics,
   geometry, materials, boundary conditions, mesh needs, study type, outputs,
   and missing parameters.
2. Done for the planning tool: search/read existing templates first. If a template fits, use it. If no
   template fits, switch to generated-code mode instead of forcing an unrelated
   template.
3. Done for the planning tool: inject a controlled code-generation prompt block into the LLM context. The
   block includes:
   - the user's modeling intent and resolved/defaulted parameters;
   - relevant local COMSOL API snippets from `simulation_retrieve_api_docs`;
   - allowed operations and an explicit target model policy;
   - required output format: COMSOL Java/API code only, no prose inside code,
     plus a structured parameter manifest when needed;
   - validation rules, including unit-aware parameters, explicit geometry,
     material, physics, mesh, study, and result nodes.
4. Done in smoke script: validate generated code offline with
   `simulation_validate_template`.
5. Done in smoke script for newly created models: execute only against a newly
   created model or a user-confirmed loaded model.
6. On failure, feed structured execution errors plus retrieved docs back into
   the repair loop and retry within bounded iterations.
7. Done for template-execution artifacts: persist generated code, validation output, execution payload, model paths,
   plots, and reports as archive artifacts.
8. Done in smoke script: offer to save successful generated code as a reusable template with a domain,
   parameter manifest, assumptions, and verification notes.

Runtime validation on local COMSOL 6.2:

- Offline generated-code smoke:

```bash
python3 scripts/run_generated_code_fallback_smoke.py --skip-comsol \
  --archive-path runtime_smoke/generated_code_fallback_skip.sqlite3
```

- Real generated-code COMSOL smoke:

```bash
.venv/bin/python scripts/run_generated_code_fallback_smoke.py --cores 1 \
  --archive-path runtime_smoke/generated_code_fallback.sqlite3 \
  --artifact-dir runtime_smoke/generated_code_fallback/template_runs \
  --plot-path runtime_smoke/generated_code_fallback/von_mises.png
```

Latest observed real-smoke result:

- Plan mode: `generated_code_fallback`, `ready_to_generate=true`, domain
  `structural`.
- Raw generated-code template execution run id:
  `generated_code_structural_smoke_20260612_220134_447451`.
- Solve succeeded in about `1.6` seconds.
- `solid.mises` evaluated with maximum about `2.206e6` Pa.
- Stress PNG exported to `runtime_smoke/generated_code_fallback/von_mises.png`.
- Successful raw code was saved as reusable template
  `generated_structural_plate_seed` in the workspace smoke archive.

Remaining P7 work:

1. Continue hardening free-form DeepSeek generated multi-roller geometry. The
   complete demo now supports bounded fallback from a failed generated snippet
   to a verified real-bearing contact cell, but production-grade generated
   geometry still needs robust named selections instead of fixture boundary IDs.
2. Done: generated-code runs now persist as first-class
   `generated_code_execution` artifacts and export
   `generated_code_execution_report` reports instead of reusing only
   `template_execution` artifacts.
3. Promote robust named geometry/contact selections for generated multi-roller
   bearing code so boundary IDs are not fixture-specific.
4. Add richer prompt-time extraction of code parameters versus modeling
   decisions so validation payloads are automatically clean.

### P8: Multi-Roller Bearing Real-Contact Demo

Goal: demonstrate a realistic bearing-specific generated-code workflow where
the model remains a bearing problem: inner raceway, outer raceway, multiple
rolling elements, explicit roller/raceway Contact pairs, meaningful load and
support conditions, stress output, artifact packaging, and follow-up result
questions answered from archive data.

Status: first end-to-end execution path complete. A deterministic verified
generated-code fixture, an Agent-orchestrated verified-code execution path, and
a free LLM generated-code path with bounded runtime fallback all run against
local COMSOL 6.2. The first free-generated snippet may still fail on
fixture-specific boundary/contact details, but the bounded repair path now
returns to a verified real-bearing contact cell and completes solve, plot,
package export, and artifact Q&A.

Implemented:

1. Added `simulation_plan_multiroller_bearing` for cylindrical-roller,
   needle-roller, and multi-roller bearing requests. It asks follow-up
   questions for bearing type, inner/outer diameter, width, roller count,
   roller diameter/length, radial load, contact model, and cage inclusion unless
   defaults are explicitly allowed.
2. Updated the system prompt so multi-roller bearing requests cannot be
   satisfied by unrelated plates, beams, or blocks. The model must preserve
   roller/raceway contact physics.
3. Added `simulation_answer_artifact_question`, which answers follow-up
   questions about max stress, approximate location, highest-risk contact
   region, contact-pair status, model parameters, and plot/model paths from
   archived artifact/package evidence.
4. Added `scripts/run_agent_multiroller_bearing_demo.py` with:
   - prompt fixture printing;
   - LLM generated-code drafting and quality gates;
   - bounded draft repair for syntax/API style failures;
   - bounded runtime fallback to a verified real-bearing contact cell;
   - a verified generated-code fixture;
   - direct fixture COMSOL smoke;
   - Agent-orchestrated validate/run/solve/evaluate/plot/package/question flow.
5. Extended bearing package export to support `contact_pressure_est` fallback
   when a generated model does not define the older `contact_pressure_guess`
   variable.
6. Extended artifact previews and package reports with model parameters,
   result interpretation, approximate max-stress region, contact status, and
   multi-roller assumptions.

Runtime validation on local COMSOL 6.2:

```bash
python3 -m compileall -q comsol_agent tests scripts
python3 -m pytest -q
python3 scripts/run_agent_fullflow_demo.py --print-prompts
python3 scripts/run_agent_generated_code_demo.py --print-prompts
.venv/bin/python scripts/run_agent_multiroller_bearing_demo.py --use-verified-fixture --cores 1
.venv/bin/python scripts/run_agent_multiroller_bearing_demo.py --cores 1
```

Latest successful full free-generation multi-roller records:

- Template execution run id:
  `agent_multiroller_bearing_execution_20260628_172644_894940`
- Result package run id:
  `agent_multiroller_bearing_package_agent_multiroller_bearing_model_1_20260628_172700_698799`
- Stress PNG:
  `runtime_smoke/multiroller_bearing_demo/multiroller_von_mises.png`
- Package JSON:
  `runtime_smoke/multiroller_bearing_demo/result_packages/agent_multiroller_bearing_package_agent_multiroller_bearing_model_1_20260628_172700_698799/summary.json`
- Package Markdown:
  `runtime_smoke/multiroller_bearing_demo/result_packages/agent_multiroller_bearing_package_agent_multiroller_bearing_model_1_20260628_172700_698799/report.md`
- Observed max von Mises stress: about `3.253e8` Pa.
- Artifact answer correctly reports the max stress, approximate roller/raceway
  contact-patch location, and explicit roller-to-raceway Contact pair status.
- Observed repair behavior: the first free-generated setup failed at
  `simulation_run_template`, then the bounded repair path used the verified
  fallback contact cell and completed the full tool chain.

Modeling scope and risks:

- The verified first-run model is a 2D plane-strain contact fixture with inner
  and outer raceway segments, two rollers, and four explicit Contact pairs.
- It is a real bearing-contact smoke, but not a full 3D complete bearing with
  cage, end effects, full roller count, and convergence certification.
- Cage geometry is intentionally omitted and recorded as a follow-up extension.
- Boundary IDs are fixture-specific; production-grade generation should move to
  named selections or verified geometry probes.

Non-goals and guardrails:

- Do not make the template library the only modeling mechanism.
- Do not execute arbitrary natural-language-generated snippets without
  validation and explicit model targeting.
- Do not treat the bearing-contact workflow as the product itself; it is a
  representative high-complexity validation case for the broader generative
  COMSOL assistant.

### P9: 3D Full Roller Bearing with Cage

Goal: upgrade the bearing workflow from the 2D multiroller contact smoke to a
main 3D full-bearing generated-code path. The main demo must not be satisfied by
the 2D fixture: it must create 3D geometry, include a real cage, keep
roller/raceway contact features, execute in COMSOL, export a von Mises stress
artifact, and preserve repair evidence for generated-code failures.

Status: 12-roller 3D verified fixture and direct COMSOL execution are now
working. The script `scripts/run_agent_3d_bearing_full_demo.py` provides prompt
fixtures, a 3D quality gate, a verified 3D fallback code block, a direct COMSOL
smoke, result package metadata injection, artifact Q&A, and execution-context
lineage. The current verified fixture builds a full 360-degree 3D model with
inner ring, outer ring, twelve cylindrical rollers, a cage ring with twelve real
cylindrical Boolean pocket cutouts, per-roller local contact patch selections,
24 explicit roller/raceway Contact Pair features, assembly finalization,
stationary Solid Mechanics, and `PlotGroup3D` stress output.

Implemented in this pass:

1. Added a 3D full-bearing demo script with:
   - prompt fixture printing;
   - verified 3D full-bearing fallback code;
   - offline quality gate that rejects 2D, cage-omitted, plate/block/beam, and
     insufficient-roller drafts;
   - direct COMSOL fixture smoke;
   - repair-history capture for generated-code/runtime failures;
   - 3D package metadata injection for cage status, repair history, and 3D
     assumptions.
2. Added tests for the 3D prompt fixture, quality gate, bounded repairs,
   runtime preflight repairs, artifact Q&A, and lineage/report fields.
3. Updated the Agent system prompt so explicit full-3D/cage-included requests
   cannot be satisfied by the 2D smoke path.
4. Upgraded the verified 3D fixture from a six-roller simplified-cage smoke to a
   twelve-roller full-bearing smoke:
   - `roller_count=12`;
   - twelve `cage_pocket_N` cylindrical cutters;
   - the cage solid is a real `Difference` using the cage annulus as `input` and
     all twelve pocket cutters as `input2`;
   - the quality gate requires the twelfth roller, the twelfth cage pocket, and
     Boolean cage pocket evidence.
5. Stabilized 3D contact execution after the previous COMSOL `NullPointerException`:
   - ring and roller geometry features enable boundary-level `selresult`;
   - each contact side uses `Intersection` selections of object boundary
     selections with local Box patches, avoiding broad/mixed contact faces;
   - each Contact Pair uses `manualSelection(True)` and local per-roller raceway
     destination patches;
   - Solid Mechanics Contact features use penalty formulation (`pfm='penalty'`)
     for the smoke solve.
6. Strengthened package Q&A evidence:
   - 3D result packages expose top-level stress/contact metrics;
   - repair history includes code excerpts for generated code and bounded
     repairs;
   - artifact answers report maximum stress, approximate location, highest-risk
     roller/contact region, cage modeling status, contact status, parameters,
     and plot/model paths.
7. Added a production selection contract:
   - result packages record `selection_plan` with target named selections for
     raceway contact patches, each roller body/contact patch, cage body, support
     surface, load region, and per-roller probes;
   - the 3D quality gate has `require_named_selections=True`, which fails broad
     `.all()` contact/load/support selections and also requires per-roller
     body/contact/raceway selections, probes, and scoped probe evidence.
8. Added generated-code artifact lineage:
   - `simulation_run_template` accepts `execution_context`;
   - archived template execution artifacts persist workflow, quality-gate
     status, repair-history count, last repair stage, and
     `require_free_generated_code`;
   - Markdown/HTML reports include workflow and repair counts so failed and
     repaired generated-code runs are auditable.

Validation:

```bash
python3 -m compileall -q comsol_agent tests scripts
python3 -m pytest -q tests/test_core.py
python3 scripts/run_agent_3d_bearing_full_demo.py --print-prompts
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py --use-verified-fixture --skip-comsol
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py --skip-comsol --require-free-generated-code
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py --direct-fixture-run --cores 1
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py --require-free-generated-code --cores 1
```

Latest successful 12-roller direct fixture records:

- Template execution run id:
  `direct_3d_bearing_fixture_20260704_181424_590737`
- Result package run id:
  `direct_3d_bearing_package_agent_3d_bearing_model_20260704_181513_005517`
- Stress PNG:
  `runtime_smoke/bearing_3d_full_demo/bearing_3d_von_mises.png`
- Package JSON:
  `runtime_smoke/bearing_3d_full_demo/result_packages/direct_3d_bearing_package_agent_3d_bearing_model_20260704_181513_005517/summary.json`
- Package Markdown:
  `runtime_smoke/bearing_3d_full_demo/result_packages/direct_3d_bearing_package_agent_3d_bearing_model_20260704_181513_005517/report.md`
- Model:
  `runtime_smoke/bearing_3d_full_demo/result_packages/direct_3d_bearing_package_agent_3d_bearing_model_20260704_181513_005517/agent_3d_bearing_model.mph`
- Observed max von Mises stress: about `3.172e6` Pa.
- Contact pressure estimate: about `1.953e6` Pa.
- Maximum displacement: about `3.361e-3` m.
- Runtime selection entity-count probe: `65/65` required selections bound.
- Physical quality gate: `production_physics_gate` with nonzero stress,
  displacement, and contact pressure.
- Contact convergence report: `contact_runtime_convergence_checked` with 24
  expected contact pairs.
- Highest-risk roller estimate: `roller_1`; in the current symmetric smoke all
  twelve rollers report the same scoped maximum, so `roller_1` is first by
  stable ranking rather than a unique physical hotspot.
- Cage status: real cage ring with twelve cylindrical Boolean pocket cutouts.
- Contact status: 24 explicit roller/raceway Contact Pair features using local
  per-roller Intersection contact patches.
- Report lineage: workflow `bearing_3d_direct_fixture`, quality gate
  `true/smoke`, repair history count `1`, and
  `require_free_generated_code=false`.

Current strict DeepSeek/API free-generation attempt against the 12-roller
Boolean-cage contract failed before code extraction because the API connection
closed after three retries. Strict mode therefore skipped the complete verified
fallback and preserved the structured failure artifact:

- Failure artifact:
  `runtime_smoke/bearing_3d_full_demo/strict_generation_failure.json`
- Recorded workflow: `bearing_3d_free_generation`
- Recorded `draft_quality.quality_level`: `generation_failed`
- Recorded `repair_history[0].stage`: `llm_generation_failure`
- Recorded `deterministic_runtime_fallback`: `null`

Earlier strict DeepSeek `deepseek-v4-pro` free-generation evidence remains
recorded for the six-roller 3D smoke without complete verified fallback:

- Template execution run id:
  `agent_3d_bearing_execution_v2_20260701_053449_685816`
- Result package run id:
  `agent_3d_bearing_package_agent_3d_bearing_model_20260701_053659_501236`
- Observed max von Mises stress: about `3.691e6` Pa.
- Repair stages: `draft`, `offline_syntax_normalization`, and
  `offline_runtime_preflight_repair`; `deterministic_runtime_fallback: null`.

Remaining P9 risks:

- The 12-roller Boolean-cage fixture is now solved directly, but the strict
  DeepSeek/API free-generation path is blocked by API connection failures before
  code extraction, so it has not yet been revalidated end-to-end against the new
  12-roller Boolean-cage contract.
- Production quality still needs stronger contact convergence checks, better
  non-symmetric load cases, mesh sensitivity checks, and clearer criteria for
  when bounded repair may rewrite generated contact selections.
- The 2D multiroller demo remains only a fast regression smoke and must not be
  used as the answer for explicit full-3D/cage-included requests.

### P10: Stable Generated 3D Bearing Agent

Goal: move from a verified 3D bearing smoke to a stable generated-code Agent
capability. The Agent should use DeepSeek/API-generated code as the primary
source, apply only bounded and auditable repairs, execute the repaired model in
COMSOL, export result artifacts, answer follow-up questions from evidence, and
make every generation/repair/fallback decision traceable through archived
lineage.

Target acceptance criteria:

1. Strict 12-roller 3D bearing run succeeds with
   `--require-free-generated-code --cores 1` without replacing the draft with
   the complete verified fallback.
2. Generated code satisfies the production gate: twelve rollers, twelve Boolean
   cage pockets, local per-roller contact patch selections, 24 Contact Pairs,
   scoped per-roller probes, and 3D stress plot output.
3. Bounded repairs are small and named: syntax normalization, known COMSOL API
   idiom fixes, selection tightening, or solver/contact stabilization. Any
   full-code fallback must be explicit, non-strict, and recorded as fallback.
4. Result packages contain stress metrics, plot/model/report paths, artifact Q&A,
   repair history, draft quality, workflow, and `require_free_generated_code`.
5. Reports expose lineage fields in Markdown/HTML so a reviewer can see which
   code was generated, what was repaired, and why the run is trustworthy.
6. Regression keeps the 2D multiroller smoke as a fast check while making the
   3D generated path the main answer for full-bearing requests.

Current implementation direction on branch `codex/segmented-3d-generation`:

- Added `--segmented-generation` to `scripts/run_agent_3d_bearing_full_demo.py`
  so DeepSeek no longer has to emit the complete 12-roller COMSOL setup in one
  long response.
- The draft phase is split into four manifest-checked segments:
  `A_base_geometry`, `B_cage_pockets_and_rollers`,
  `C_selections_contacts_physics`, and `D_mesh_study_results`.
- Each segment returns `SEGMENT_MANIFEST_START/END` JSON plus
  `GENERATED_CODE_START/END` code. The local driver validates dependencies,
  duplicate tags, forbidden snippets, preferred tag namespaces, Python/MPh
  syntax, and the final full-bearing quality gate before COMSOL execution.
- Segment calls have independent retry and wall-clock timeout controls:
  `--segment-max-retries`, `--segment-timeout-seconds`, and
  `--segment-llm-max-tokens`.
- Segment artifacts are written under
  `runtime_smoke/bearing_3d_full_demo/segmented_generation/`; strict-mode
  failure writes `segmented_generation_failure.json` and does not replace the
  draft with the verified fallback.
- Initial proxy tests showed short DeepSeek calls, long non-tool text, and a
  minimal tool call succeed, while the original monolithic 3D draft and first
  segmented calls still hit connection stalls/interruptions. The new timeout
  and per-segment retry path keeps those failures bounded and auditable.
- Shared 3D bearing contracts now live in `comsol_agent/simulation/bearing_3d.py`
  instead of being only demo-script helpers. The module owns the segmented
  generation contract, generated-code extraction/normalization, full-bearing
  quality gate, selection binding contract, code/runtime selection audit,
  reusable generated/template execution context builder, nonzero
  physical-result audit, artifact Q&A helpers, and an explicit contact
  convergence report structure. The 3D demo now re-exports these shared
  contracts for compatibility instead of carrying local duplicate definitions.
- 3D result packages now record `selection_binding_contract`,
  `selection_binding_audit`, `physical_result_audit`, and
  `contact_convergence_report`. The current contact report is honest about
  smoke-level evidence: without solver residual/contact iteration data it marks
  convergence as `contact_smoke_convergence_unverified` rather than production
  verified.
- Generated-code/template execution artifact readers and Markdown/HTML reports
  now surface quality-gate, selection-binding, physical-result, and contact
  convergence fields when they are present in `execution_context`, including
  runtime selection-probe status, production physics readiness, and runtime
  contact verification.
- Next real-COMSOL smoke should run the direct 3D fixture path and confirm:
  runtime selection entity-count probes are nonzero for all required contact,
  load, support, cage, and per-roller selections; `solid.mises`, `solid.disp`,
  and contact-pressure evidence are all nonzero; the exported package/report
  captures `selection_binding_runtime_checked`,
  `physical_result_production_ready`, and `contact_runtime_verified` (or a
  precise unverified/failure reason).

## Resume Checklist

### P11: General-Purpose Modeling Expansion

Goal: evolve the agent beyond bearing-specific modeling into a general COMSOL
modeling assistant for multiple engineering objects, including but not limited
to bearings, eccentric shafts, gears, and circuit boards.

The detailed plan is maintained in
`docs/general_modeling_expansion_plan.md`. In short, the next pass should:

1. generalize requirement decomposition into model-family-neutral slots;
2. add a high-level `simulation_plan_modeling_request` gateway;
3. introduce a model-family registry for bearing, eccentric shaft, gear pair,
   PCB, and future object types;
4. add starter templates and quality gates for eccentric shaft, PCB thermal,
   and simplified gear contact cases;
5. generalize result packaging from `bearing_contact_package` to a reusable
   modeling result package with domain-specific metrics.

Acceptance criteria: the agent can handle at least one eccentric-shaft request,
one PCB thermal/electrothermal request, and one simplified gear-contact request
without substituting a bearing template, while still preserving the existing
bearing quality path.

When continuing development:

1. Read this file and `docs/comsol_runtime.md`.
   Also read `docs/general_modeling_expansion_plan.md` before changing the
   requirement-decomposition or generated-code planning path.
2. Run:

```bash
python3 -m compileall -q comsol_agent tests scripts
python3 -m pytest -q
```

3. Rerun the real template execution smoke with COMSOL when changing template
   execution or Java/API wrapping.
4. Rerun `scripts/run_agent_fullflow_demo.py` when changing AgentLoop,
   high-level simulation tools, archive records, or reporting.
5. If either smoke fails, inspect the generated runtime artifact JSON first and
   repair the lowest-level failure.

## Pause Decision

Development can pause here. The project has a tested offline state and a
verified real COMSOL/DeepSeek fullflow smoke. The next substantial development
pass should define a new roadmap item, such as first-class artifacts for
example-model runs and raw Java/API calls, richer report analytics, or a
frontend/GUI layer.
