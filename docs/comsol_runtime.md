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
- `simulation_plan_bearing_modeling_request`: classify bearing-family topology
  (deep-groove ball, angular-contact ball, cylindrical/tapered/needle roller,
  thrust, or general bearing), separate natural-language intent from executable
  COMSOL parameters, choose a contact policy, and reject deep-groove smoke
  substitutions for unsupported bearing topologies
- `simulation_export_bearing_contact_package`: save a solved bearing model,
  stress PNG, metrics, summary JSON, Markdown report, and archive index record

## Bearing Contact Runtime Gates

For 3D roller-bearing work, a solved model is not accepted only because COMSOL
returns from the solver. The runtime gate requires all of the following:

- named load/support/contact selections are present in generated code
- `simulation_probe_3d_selection_binding` reports runtime entity counts
- roller contact source selections are mutually exclusive for each roller
- stress and displacement are nonzero on the expected bearing body, not only in a
  global field
- exported PNGs pass a nonblank/nonmonochrome quality gate
- fallback stress images rendered from solved `solid.mises` field data are
  explicitly reported as field-data projections, not native COMSOL surface plots

The P12 verified 12-roller raceway-contact smoke can be reproduced with:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --contact-stage-mode all_raceway_preload_only \
  --cores 1 \
  --archive-path runtime_smoke/bearing_family_p12_fix/bearing3d_12roller_prestress_physical.sqlite3 \
  --artifact-root runtime_smoke/bearing_family_p12_fix/bearing3d_12roller_prestress_physical \
  --model-name bearing3d_12roller_prestress_physical
```

The accepted stage is a displacement-preload smoke with all 12 rollers active
and true roller/inner-raceway plus roller/outer-raceway Contact features. It is
not production cage-load-transfer physics: cage geometry and cage contact pairs
exist, but the accepted stage keeps cage contact inactive and records that
limitation in `physical_contact_validation.warnings`. Radial load transfer and
full cage-contact stages must be reported as failed unless their own final stage
converges and passes the same body-stress and image gates.

For user requests that explicitly ask for a high-load 12-roller native COMSOL
stress image, use the verified direct high-load visual stage until the
full-cage boundary-load path is independently converged:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --contact-stage-mode legacy_raceway_highload_direct \
  --cores 1 \
  --archive-path runtime_smoke/bearing_family_p12_highload_visual/bearing3d_legacy_raceway_highload_direct_latest.sqlite3 \
  --artifact-root runtime_smoke/bearing_family_p12_highload_visual/bearing3d_legacy_raceway_highload_direct_latest \
  --model-name bearing3d_legacy_raceway_highload_direct_latest
```

The summary writes the user-facing image contract to
`direct_3d_bearing_summary.json.requested_stage_image`. On 2026-07-07 this
stage solved with max von Mises stress `3.1717319e6 Pa`, max displacement
`3.361115e-3 m`, contact-pressure estimate `1.953125e6 Pa`, and a passing
nonblank native COMSOL Volume PNG at
`runtime_smoke/bearing_family_p12_highload_visual/bearing3d_legacy_raceway_highload_direct_latest/stage_plots/legacy_raceway_highload_direct_native_volume.png`.
This stage is still labeled
`visual_fallback_inner_ring_distributed_body_load_not_design_boundary_load`:
it has 24 raceway contact pairs for 12 rollers, but cage-pocket contact and the
final design-grade inner-bore BoundaryLoad high-load transfer are not declared
production-ready.

Boundary-load transfer evidence is tracked separately from the accepted
high-load visual stage. The preferred diagnostic path is now continuous: keep
the named `sel_inner_bore_load_surface` `BoundaryLoad` active from the first
contact-closure stage, retain a small displacement preload while contact closes,
then ramp `radial_load`. Any retained displacement preload or weak inner-ring
guidance must remain visible in `load_application_fidelity`,
`physical_contact_validation.warnings`, and `requested_stage_image`:

Stage evidence across all local 3D bearing runs can be regenerated with:

```bash
python3 scripts/run_agent_3d_bearing_full_demo.py \
  --stage-evidence-matrix \
  --stage-evidence-root runtime_smoke \
  --stage-evidence-output-dir reports/bearing_stage_evidence
```

As of 2026-07-14, the report scans
`runtime_smoke/**/direct_3d_bearing_summary.json` and writes
`reports/bearing_stage_evidence/bearing_stage_evidence_matrix.json` plus
`reports/bearing_stage_evidence/bearing_stage_evidence_matrix.md`. After the
fine `0.101 N` / `0.105 N` useparam-off continuation attempts, the
soft-guidance diagnostic, the reaction `IntSurface` reruns, the contact
penalty diagnostic, the micro-parametric continuation diagnostic, the
fixed-active-roller stabilization diagnostic, and the single-solve `0.101 N`,
`0.12 N`, `0.13 N`, `0.14 N`, `0.145 N`, `0.1475 N`, `0.14875 N`,
`0.149375 N`, fine-continuation `0.15 N`, `0.1625 N`, `0.175 N`,
`0.1875 N`, `0.19375 N`, `0.196875 N`, `0.1984375 N`, fine `0.2 N`,
failed coarse `0.15 N`, and failed coarse `0.2 N` BoundaryLoad
diagnostics plus the `0.101 N` per-roller probe-gate rerun and current
reaction-equivalent audit reruns, the roller-1 contact-pair endpoint swap
diagnostic, the active-roller spring-softening diagnostic, the full-raceway
destination failure, the global `20[um]` interference failure, the explicit
raceway-entity override/rebind diagnostics, the Contact feature introspection
replay, the `source_offset=±3[um]` diagnostics, the valid `offset=±3[um]`
diagnostics, and the `roller_1` patch-shrink geometry-selection diagnostic, the
current matrix scans `127`
summaries and `279`
stage rows, with
`production_ready_count=0`, `reaction_verified_stage_count=0`, and
`converged_native_stage_count=195`; any answer to a high-load design-image
request must say so explicitly. The same matrix now also indexes saved-MPH
reaction replay reports under `runtime_smoke/**/reaction_probe_summary.json`;
the current replay count is `1`, with `saved_reaction_probe_verified_count=0`.
It also indexes `12` saved-MPH contact probe reports; none of them converts the
current BoundaryLoad ladder into a production-ready design-grade result.
It also indexes `9` saved-MPH contact probe reports; `8` of those retain a
source/destination imbalance diagnostic for `roller_1`.
Matrix rows also include a
`physical_plausibility_success` gate, and the highest-trust selector skips
converged native stages that fail the basic stress/displacement plausibility
checks. The matrix also marks `17` converged native 3-roller BoundaryLoad
single-solve rows from `0.101 N` through fine `0.2 N` with
`boundaryload_sequence_stress_plateau=true` and
`physical_plausibility_success=false`, because max von Mises remains pinned
while displacement grows by about `2.97x`; these rows are constraint/
stabilization-dominated diagnostics, not physically accepted load transfer.
BoundaryLoad rows also require scoped per-roller max-stress probe evidence
(`maxop_roller_i(solid.mises)`) before they can pass physical plausibility;
older BoundaryLoad summaries without `per_roller_probe_results` are explicitly
marked with `BoundaryLoad stage is missing per-roller max-stress probe results`.
The physical gate now also writes `active_roller_load_distribution` in new stage
summaries and exposes `active_roller_nonzero_probe_ratio`,
`active_roller_zero_stress_rollers`, and
`active_roller_load_distribution_success` in the matrix. A BoundaryLoad row fails
physical plausibility if any configured active load-side roller has a near-zero
`maxop_roller_i(solid.mises)` value; this prevents a converged native PNG from
being selected when the intended roller set is not actually carrying load.
The real `0.101 N` probe-gate rerun at
`runtime_smoke/bearing_family_p12_boundaryload_probe_gate/bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate`
confirms all 12 roller probes evaluate, but only two of the three active
load-side rollers are nonzero (`roller_1` is near zero), so it remains diagnostic
and is rejected by both the active-roller distribution gate and the stress-plateau
gate.
The matrix now aggregates this under
`boundaryload_distribution_diagnostics`: among `91` BoundaryLoad rows, `85`
historical rows still lack per-roller probes, `17` rows are marked as stress
plateau, and the fully probed zero-carry rows are the `0.101 N` probe-gate,
roller-1 pair-swap, active-spring-softening, and explicit raceway-entity
override/rebind plus gapoffset/source-offset diagnostics with
`zero_carry_rollers={"roller_1": 8}`. The
linked configured-MPH
diagnostic shows `roller_1` has body selection count `5`, inner and outer
contact active, cage contact inactive, weak foundation active, and fixed
stabilization inactive. The refreshed no-solve diagnostic also audits contact
pair endpoints: `cp_roller_1_inner_raceway` maps
`sel_roller_1_inner_contact -> sel_inner_raceway_1_contact` with `2 -> 2`
entities, and `cp_roller_1_outer_raceway` maps
`sel_roller_1_outer_contact -> sel_outer_raceway_1_contact` with `2 -> 2`
entities. The same refreshed diagnostic reads the `sel_roller_1_body` Box bounds
as `xmin=21.500[mm]`, `xmax=32.500[mm]`, `ymin=-5.500[mm]`,
`ymax=5.500[mm]`, so the body center is `(27.0 mm, 0.0 mm)` and its angle is
`0 deg`; the inner-bore BoundaryLoad vector is also along `+X`, giving a
`0 deg` load-angle offset. The same matrix now records the contact patch radial
placement: the inner patch box center is at `23.0 mm`, the outer patch box
center is at `31.0 mm`, giving offsets of `-4.0 mm` and `+4.0 mm` relative to
the `27.0 mm` roller center. Gross inner/outer patch placement is therefore
also correct. The matrix also compares contact feature settings against the
nonzero active rollers `2` and `12`; after ignoring the expected per-roller pair
tag names, `roller_1` matches their `pn_penalty=5e-5*E_steel`,
`useRelaxation=Always`, `irlx=0.12`, `tolcontact=3[um]`, and `zeroInitGap=0`.
The next BoundaryLoad solve should focus on solved contact status, initial
gap/contact normal direction, and weak-guidance/weak-foundation dominance for
`roller_1`, rather than treating body selection, contact activation, pair
endpoints, gross load-angle mapping, gross patch radial placement, or static
contact feature settings as the leading suspects before increasing the
continuation target to `0.5 N` or `1 N`.
The solved result-package MPH was also replayed without re-solving via:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph runtime_smoke/bearing_family_p12_boundaryload_probe_gate/bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate_20260713_195429_133133/bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate.mph \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_probe_gate/bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate/contact_probe_solved_mph \
  --cores 1
```

This saved-MPH contact probe writes
`contact_probe_solved_mph/contact_probe_summary.json` and `.md` and is now
indexed by the stage evidence matrix, including the zero-carry focus row in
`boundaryload_distribution_diagnostics`. It now evaluates both field/traction
candidates and contact-pair status candidates such as
`solid.Tn_cp_roller_i_inner_raceway` and
`solid.Tn_cp_roller_i_outer_raceway`. The refreshed report evaluated `972`
total candidates, with `144` successful evaluations and `90` finite nonzero
results; `912` candidates are contact-status/pair-variable probes, including
`36` `infinite_result` gap evaluations. The report now also writes
`contact_variable_discovery`, splitting generic variables from pair-specific
contact-pair variables so that raceway-surface stress is not mistaken for actual
pair load transfer. The important
diagnostic is asymmetric: for `roller_1`, both roller-side source selections
`sel_roller_1_inner_contact` and `sel_roller_1_outer_contact` evaluate to zero
for the probed `solid.mises`, `solid.disp`, and traction candidates, while the
corresponding raceway-side destination selections are nonzero. Rollers `2` and
`12` have nonzero source and destination contact probes. The pair-specific
normal contact pressure signal further narrows the issue: `roller_1` has
`pair_specific_success_count=2`, `pair_specific_nonzero_count=0`, and
`solid.Tn_cp_roller_1_inner_raceway = 0.0`,
`solid.Tn_cp_roller_1_outer_raceway = 0.0` on the raceway destination surfaces,
whereas `roller_2` and `roller_12` have nonzero pair-specific `Tn` values.
The new discovery matrix shows the distinction explicitly: `roller_1` has
generic `solid.Tn`/`solid.p` finite nonzero values on the raceway destination
surfaces, but `pair_specific_finite_nonzero_count=0` for `Tn`; rollers `2` and
`12` each have `pair_specific_finite_nonzero_count=4` for `Tn`.
The same saved-MPH replay now records `pair_enforcement_diagnostic`: the model
audit successfully captures the six probed raceway Contact Pair nodes and twelve
roller/raceway/cage Contact features for rollers `1/2/12`. For `roller_1`, the
inner and outer pair endpoints are still
`sel_roller_1_*_contact -> sel_*_raceway_1_contact` with `2 -> 2` entities, the
Contact features are active, and their solved-MPH settings match the nonzero
neighboring rollers (`pn_penalty=5e-5*E_steel`, `useRelaxation=Always`,
`irlx=0.12`, `tolcontact=3[um]`, `zeroInitGap=0`). A follow-on normal
orientation probe integrates `1`, `nx`, `ny`, `nz`, and the roller-radial normal
projection over each source/destination selection. For `roller_1`, both inner
and outer source/destination pairs have opposite radial normal signs, matching
the nonzero neighboring rollers. Gross normal sign is therefore no longer the
leading suspect. The saved-MPH contact probe now also writes
`geometry_moments_by_roller`, which integrates `1/x/y/z` and roller-radial
coordinate over each contact selection. On the refreshed `0.101 N` probe-gate
MPH, `roller_1` raceway destination centroids differ from the nonzero neighbors:
its inner and outer source-destination radial deltas are both about `9.811 mm`,
while rollers `2/12` are about `6.006 mm` inner and `2.247 mm` outer. This is
consistent with the Box/Intersection raceway patch selecting whole intersecting
boundary entities rather than a true local contact patch at the `0 deg` load
roller. This remains diagnostic evidence, not verified load closure or a
production-ready BoundaryLoad result.
The latest saved-MPH contact probe refresh also writes
`contact_feature_introspection`, a COMSOL feature-property listing for
`contact_roller_{1,2,12}_{inner,outer}`. The report at
`runtime_smoke/bearing_family_p12_boundaryload_gapoffset/bearing3d_load_side_boundaryload_0p101_roller1_gapoffset_minus3um/contact_probe_solved_mph_introspection/contact_probe_summary.json`
confirms six Contact features were read successfully. COMSOL 6.2 exposes
`offset`, `source_offset`, `pressureOffsetCtrl`, and `zeroInitGap`; the guessed
`gapoffset`, `gapOffset`, `contactOffset`, `offsetValue`, `initialGap`, and
`initgap` properties all return `Unknown parameter`. After normalizing expected
roller-specific tag references in `pairs` and `pn`, `roller_1` contact-feature
properties match the nonzero reference rollers `2/12`. This rules out a hidden
static Contact feature setting mismatch and keeps the next useful path focused
on true local raceway partition/imprint or valid `offset/source_offset`
single-variable contact-state diagnostics. It does not make the current
BoundaryLoad result production-ready.
The follow-on valid-property single-variable run
`runtime_smoke/bearing_family_p12_boundaryload_source_offset/bearing3d_load_side_boundaryload_0p101_roller1_source_offset_minus3um`
sets only `contact_roller_1_inner/outer.source_offset=-3[um]` on the same
`0.101 N` fresh BoundaryLoad ramp. COMSOL accepts the property and solves with a
native Volume PNG, but the requested-stage selector rejects the stage:
`roller_1=0.0 Pa`, `roller_2≈9.77e4 Pa`, `roller_12≈1.10e5 Pa`. Saved-MPH
contact replay confirms `roller_1` still has pair-specific `Tn=0`, pair-specific
gap at the Infinity sentinel, and source/destination imbalance; rollers `2/12`
remain the only pair-specific nonzero references. This rules out a small
negative `source_offset` as a production fix.
The sign-reversed follow-on run
`runtime_smoke/bearing_family_p12_boundaryload_source_offset_plus/bearing3d_load_side_boundaryload_0p101_roller1_source_offset_plus3um`
sets only `contact_roller_1_inner/outer.source_offset=3[um]`. It also solves
and exports a native Volume PNG, but the stage is rejected for the same physical
reason: `roller_1=0.0 Pa`, `roller_2≈9.77e4 Pa`, `roller_12≈1.10e5 Pa`.
Saved-MPH replay again reports `roller_1` pair-specific `Tn=0` and gap at the
Infinity sentinel, while `roller_2/12` remain the pair-specific nonzero
references. Both signs of a small `source_offset` are therefore ruled out as a
roller-1 zero-carry fix.
The next valid-property single-variable runs
`runtime_smoke/bearing_family_p12_boundaryload_offset/bearing3d_load_side_boundaryload_0p101_roller1_offset_minus3um`
and
`runtime_smoke/bearing_family_p12_boundaryload_offset_plus/bearing3d_load_side_boundaryload_0p101_roller1_offset_plus3um`
set only `contact_roller_1_inner/outer.offset` to `-3[um]` or `3[um]` on the
same `0.101 N` fresh BoundaryLoad ramp. COMSOL accepts the property, solves, and
exports native Volume PNGs in both cases, but the requested-stage selector
rejects both as diagnostic only: `roller_1=0.0 Pa`, `roller_2≈9.77e4 Pa`, and
`roller_12≈1.10e5 Pa`. Saved-MPH contact probes confirm `roller_1` still has
zero pair-specific `Tn` transfer and Infinity-sentinel pair gap while
`roller_2/12` have nonzero pair-transfer references. Thus small valid `offset`
and `source_offset` perturbations are both ruled out; the next useful branch is
geometry-level local raceway partition/imprint or another contact-state
formulation, not more static Contact property tweaks. These offset runs are not
production-ready and must not be presented as verified 12-roller high-load
stress evidence.
The follow-on geometry-selection diagnostic
`runtime_smoke/bearing_family_p12_boundaryload_patch_shrink/bearing3d_load_side_boundaryload_0p101_roller1_patch_shrink`
keeps the same `0.101 N` BoundaryLoad stage but shrinks only the `roller_1`
inner/outer contact patch Box selections to `x=22.6..23.4 mm` and
`x=30.6..31.4 mm`, `y=±1 mm`, `z=±4 mm`. COMSOL solves and exports a native
Volume PNG, but the physical gate again rejects the stage because
`roller_1=0.0 Pa` while `roller_2/12≈9.77e4/1.10e5 Pa`. The configured-MPH
diagnostic confirms the shrunk Box bounds were applied, yet the resulting
raceway intersections still bind whole boundary entities (`sel_inner_raceway_1`
and `sel_outer_raceway_1` each retain two destination entities). The solved-MPH
contact probe keeps the same failure signature: `roller_1` pair-specific
`Tn=0`, while `roller_2/12` have nonzero pair-transfer. Geometry moments remain
abnormal for `roller_1` with inner/outer source-destination radial deltas about
`9.811 mm`, versus `6.006 mm` inner and `2.247 mm` outer for the nonzero
neighbors. This rules out simple Box shrink as a production fix and points to
true raceway partition/imprint or another way to create real local contact
surfaces.
The follow-on single-variable run
`runtime_smoke/bearing_family_p12_boundaryload_pair_swap/bearing3d_load_side_boundaryload_0p101_roller1_pair_swap`
swapped only `roller_1` raceway Contact Pair source/destination endpoints at
the same `0.101 N` load. It solved and exported a native Volume PNG, but the
requested-stage selector still rejected it because active load-side distribution
remained incomplete: `roller_1` maxop stress was `1.1406713e-05 Pa`, while
`roller_2` and `roller_12` were about `9.77e4 Pa` and `1.10e5 Pa`. The saved-MPH
contact replay for the swapped model shows `roller_1` still has
`Tn.pair_specific_finite_nonzero_count=0`; the swap removes the old
source/destination imbalance flag but does not create pair-specific load
transfer. Therefore the next branch should inspect actual contact state/gap
activation or stabilization/contact enforcement dominance, not merely flip pair
endpoints again.
The next single-variable stabilization run
`runtime_smoke/bearing_family_p12_boundaryload_stabilization/bearing3d_load_side_boundaryload_0p101_active_spring1e9`
kept the same `0.101 N` fresh single-solve ramp and changed only
`active_roller_stabilization_k` from `1e10[N/m^3]` to `1e9[N/m^3]`. It also
solved and exported a native Volume PNG, but physical selection again rejected
it because `roller_1` stayed at `0.0 Pa` while `roller_2` and `roller_12` were
about `7.06e4 Pa` and `7.42e4 Pa`. Its saved-MPH contact replay still reports
`roller_1 Tn.pair_specific_finite_nonzero_count=0`, with rollers `2/12` at `4`.
This rules out a simple tenfold active-spring stiffness dominance explanation;
the remaining likely path is actual contact-state/gap closure or pair
enforcement activation for `roller_1`.

The explicit raceway-entity diagnostic
`load_side_group_boundary_load_single_solve_0p101_entity_raceway_override` was
then added to avoid treating the Box/Intersection raceway patch as a true local
contact surface. It rebuilds the active load-side raceway destination selections
as `Explicit` boundary selections from the saved-MPH geometry-moment evidence
(`sel_inner_raceway_1_contact=[132,133]`,
`sel_outer_raceway_1_contact=[8,9]`,
`sel_inner_raceway_2_contact=[133,134]`,
`sel_outer_raceway_2_contact=[9]`,
`sel_inner_raceway_12_contact=[131,132]`,
`sel_outer_raceway_12_contact=[8]`) while keeping the same `0.101 N` fresh
single-solve ramp, active rollers `12/1/2`, BoundaryLoad, weak guidance, weak
roller foundation, active-roller spring, penalty, and relaxation. The first real
run at
`runtime_smoke/bearing_family_p12_boundaryload_entity_raceway_override/bearing3d_load_side_boundaryload_0p101_entity_raceway_override`
solved and exported a native Volume PNG, but the active distribution gate still
failed with `roller_1=0.0 Pa`, `roller_2≈9.77e4 Pa`, and
`roller_12≈1.10e5 Pa`. Its saved-MPH contact probe showed
`roller_1` pair-specific `Tn` still zero; however, replacing the selection
temporarily left the Contact Pair destination reported as unnamed, so the
diagnostic was repeated after the setup code was changed to rebind each
overridden raceway selection back to the corresponding pair destination via
`.destination().named(selection_tag)`.

The rebind run at
`runtime_smoke/bearing_family_p12_boundaryload_entity_raceway_override_rebind/bearing3d_load_side_boundaryload_0p101_entity_raceway_override_rebind`
also solved and exported a native Volume PNG, but remained diagnostic only:
`roller_1=0.0 Pa`, `roller_2≈9.77e4 Pa`, `roller_12≈1.10e5 Pa`, max von Mises
`6.526523e6 Pa`, inner-ring max `1.1007336e7 Pa`, and max displacement
`2.213222e-3 m`. The saved-MPH contact probe confirmed the pair destinations
were named again (`sel_roller_1_inner_contact -> sel_inner_raceway_1_contact`
and `sel_roller_1_outer_contact -> sel_outer_raceway_1_contact`, both `2 -> 2`
entities), but `roller_1` still had `pair_specific_nonzero_count=0`, generic
raceway `solid.Tn` could be nonzero, and pair-specific gaps remained infinite.
Therefore explicit reuse/rebinding of those raceway entities is not a production
fix; the next useful branch is a true geometry-level partition/imprint of local
raceway contact surfaces or a contact-state/gap-closure formulation change.

A follow-on single-variable destination diagnostic was added as
`load_side_group_boundary_load_single_solve_0p101_full_raceway_destination`. It
keeps the same `0.101 N` fresh single-solve ramp, active rollers `12/1/2`,
contact penalty/relaxation, weak guidance, weak roller foundation, and active
roller spring, but changes only the six active roller/raceway Contact Pair
destinations from per-roller local raceway patch selections to the full
`sel_inner_raceway_contact` / `sel_outer_raceway_contact` surfaces. The real run
is saved at
`runtime_smoke/bearing_family_p12_boundaryload_destination/bearing3d_load_side_boundaryload_0p101_full_raceway_destination`.
It did not export a native PNG and the summary records
`Solve failed: java.lang.NullPointerException`; physical validation correctly
rejects the stage. The configured MPH is preserved at
`stage_models/single_solve_3_roller_boundary_load_0p101n_full_raceway_destination_configured.mph`,
and no-solve diagnostics in `diagnostics_0p101n_full_raceway_destination/`
confirm that the full-raceway destination overrides were applied. This branch
shows that simply broadening the raceway destination is not a production fix; the
next useful path is to create true partitioned/local raceway contact surfaces or
a lower-risk geometry-gap/interference diagnostic before increasing load.

The lower-risk global interference diagnostic was then run with the existing
fresh `0.101 N` single-solve mode plus `--contact-interference '20[um]'`, keeping
the same active rollers `12/1/2`, BoundaryLoad ramp, contact penalty/relaxation,
weak guidance, weak roller foundation, and active-roller spring. The run is
saved at
`runtime_smoke/bearing_family_p12_boundaryload_interference/bearing3d_load_side_boundaryload_0p101_interference20um`.
It failed at the initial parameter solve with the COMSOL message
`找不到初始参数的解` / `不收敛，相对步长太小`, exported no native PNG, and was
rejected by the physical gate. Both configured and failed MPH files were saved:
`stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`
and `failed_3d_contact_model.mph`. The no-solve diagnostic in
`diagnostics_0p101n_interference20um/` now includes `parameter_audit`, confirming
`contact_interference=20[um]`, `radial_load=0.101[N]`, and
`inner_radial_displacement=0[um]`. This shows that simply forcing global geometric
interference is not a stable fix for the `roller_1` zero-carry problem.

Reaction verification is only counted when a candidate evaluates to a
nonzero reaction force; historical zero-force candidates are not counted.

On 2026-07-14, `load_side_group_boundary_load_single_solve_0p101` was added to
separate solver-history effects from the post-bootstrap continuation failures:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101 \
  --cores 1 \
  --archive-path runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p101.sqlite3 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p101 \
  --model-name bearing3d_load_side_boundaryload_single_solve_0p101
```

This mode uses one fresh solver sequence and ramps the inner-bore
`BoundaryLoad` directly through `0.001 0.005 0.01 0.05 0.1 0.1005 0.101 N`
with only rollers `12/1/2` active, cage contact inactive, active-roller spring
stabilization enabled, weak roller foundation enabled, and weak inner-ring
guidance enabled. The real COMSOL run converged and exported
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p101/stage_plots/single_solve_3_roller_boundary_load_0p101n_parametric_native_volume.png`.
It reported max von Mises `6.526523284e6 Pa`, inner-ring max von Mises
`1.100733554e7 Pa`, max displacement `2.214274858e-3 m`, and contact-pressure
estimate `65.75520833 Pa`. The configured MPH is saved at
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p101/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`,
with no-solve diagnostics in
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p101/diagnostics_0p101n_single_solve/`.
The diagnostic confirms `useparam=on`, `pname=['radial_load']`,
`plistarr=['0.001 0.005 0.01 0.05 0.1 0.1005 0.101']`, active
`load_inner_bore`, active roller contacts for rollers `1/2/12`, inactive cage
contacts, active weak guidance, and inactive displacement preload. It remains
diagnostic only: not all 12 rollers participate, cage contact is off, temporary
stabilization and weak guidance are active, and no reaction closure was
verified.

The same fresh-solver formulation was extended to `0.12 N` in
`load_side_group_boundary_load_single_solve_0p12`. Unlike the earlier fixed
single-point `0.12 N` post-bootstrap stage, this run also converged and exported
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p12/stage_plots/single_solve_3_roller_boundary_load_0p12n_parametric_native_volume.png`.
It reported max von Mises `6.526523284e6 Pa`, inner-ring max von Mises
`1.100733554e7 Pa`, max displacement `2.727367048e-3 m`, and contact-pressure
estimate `78.125 Pa`. The configured MPH and no-solve diagnostics are saved at
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p12/stage_models/single_solve_3_roller_boundary_load_0p12n_parametric_configured.mph`
and
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p12/diagnostics_0p12n_single_solve/`.
The increasing displacement/contact-pressure between `0.101 N` and `0.12 N`
is useful continuation evidence, but the repeated stress maximum shows that
stabilization or contact-state dominance still needs diagnosis before any
high-load or production-ready claim.

Finer fresh-solver continuation showed that the same diagnostic setup also
converges at `0.13 N`, `0.14 N`, `0.145 N`, `0.1475 N`, `0.14875 N`,
`0.149375 N`, fine `0.15 N`, `0.1625 N`, `0.175 N`, `0.1875 N`,
`0.19375 N`, `0.196875 N`, `0.1984375 N`, and fine `0.2 N`:

- `load_side_group_boundary_load_single_solve_0p13`: max von Mises
  `6.526523284e6 Pa`, inner-ring max von Mises `1.100733554e7 Pa`, max
  displacement `3.122212334e-3 m`, contact-pressure estimate `84.63541667 Pa`,
  native PNG
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p13/stage_plots/single_solve_3_roller_boundary_load_0p13n_parametric_native_volume.png`.
- `load_side_group_boundary_load_single_solve_0p14`: max von Mises
  `6.526523284e6 Pa`, inner-ring max von Mises `1.100733554e7 Pa`, max
  displacement `3.545713204e-3 m`, contact-pressure estimate `91.14583333 Pa`,
  native PNG
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p14/stage_plots/single_solve_3_roller_boundary_load_0p14n_parametric_native_volume.png`.
- `load_side_group_boundary_load_single_solve_0p145`: max von Mises
  `6.526523284e6 Pa`, inner-ring max von Mises `1.100733554e7 Pa`, max
  displacement `3.763421798e-3 m`, contact-pressure estimate `94.40104167 Pa`,
  native PNG
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p145/stage_plots/single_solve_3_roller_boundary_load_0p145n_parametric_native_volume.png`.
- `load_side_group_boundary_load_single_solve_0p1475`: max von Mises
  `6.526523284e6 Pa`, inner-ring max von Mises `1.100733554e7 Pa`, max
  displacement `3.878676165e-3 m`, contact-pressure estimate `96.02864583 Pa`,
  native PNG
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p1475/stage_plots/single_solve_3_roller_boundary_load_0p1475n_parametric_native_volume.png`.
- `load_side_group_boundary_load_single_solve_0p14875`: max von Mises
  `6.526523284e6 Pa`, inner-ring max von Mises `1.100733554e7 Pa`, max
  displacement `3.936759582e-3 m`, contact-pressure estimate `60.62825521 Pa`,
  native PNG
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p14875/stage_plots/single_solve_3_roller_boundary_load_0p14875n_parametric_native_volume.png`.
- `load_side_group_boundary_load_single_solve_0p149375`: max von Mises
  `6.526523284e6 Pa`, inner-ring max von Mises `1.100733554e7 Pa`, max
  displacement `3.965742682e-3 m`, native PNG
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p149375/stage_plots/single_solve_3_roller_boundary_load_0p149375n_parametric_native_volume.png`.
- `load_side_group_boundary_load_single_solve_0p15_fine`: max von Mises
  `6.526523284e6 Pa`, inner-ring max von Mises `1.100733554e7 Pa`, max
  displacement `3.994913732e-3 m`, native PNG
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p15_fine/stage_plots/single_solve_3_roller_boundary_load_0p15n_fine_parametric_native_volume.png`.
- `load_side_group_boundary_load_single_solve_0p1625`: max von Mises
  `6.526523284e6 Pa`, inner-ring max von Mises `1.100733554e7 Pa`, max
  displacement `4.610957949e-3 m`, native PNG
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p1625/stage_plots/single_solve_3_roller_boundary_load_0p1625n_parametric_native_volume.png`.
- `load_side_group_boundary_load_single_solve_0p175`: max von Mises
  `6.526523284e6 Pa`, inner-ring max von Mises `1.100733554e7 Pa`, max
  displacement `5.280893802e-3 m`, native PNG
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p175/stage_plots/single_solve_3_roller_boundary_load_0p175n_parametric_native_volume.png`.
- `load_side_group_boundary_load_single_solve_0p1875`: max von Mises
  `6.526523284e6 Pa`, inner-ring max von Mises `1.100733554e7 Pa`, max
  displacement `6.017368225e-3 m`, native PNG
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p1875/stage_plots/single_solve_3_roller_boundary_load_0p1875n_parametric_native_volume.png`.
- `load_side_group_boundary_load_single_solve_0p19375`: max von Mises
  `6.526523284e6 Pa`, inner-ring max von Mises `1.100733554e7 Pa`, max
  displacement `6.411106625e-3 m`, native PNG
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p19375/stage_plots/single_solve_3_roller_boundary_load_0p19375n_parametric_native_volume.png`.
- `load_side_group_boundary_load_single_solve_0p196875`: max von Mises
  `6.526523284e6 Pa`, inner-ring max von Mises `1.100733554e7 Pa`, max
  displacement `6.534775763e-3 m`, native PNG
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p196875/stage_plots/single_solve_3_roller_boundary_load_0p196875n_parametric_native_volume.png`.
- `load_side_group_boundary_load_single_solve_0p1984375`: max von Mises
  `6.526523284e6 Pa`, inner-ring max von Mises `1.100733554e7 Pa`, max
  displacement `6.552863781e-3 m`, native PNG
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p1984375/stage_plots/single_solve_3_roller_boundary_load_0p1984375n_parametric_native_volume.png`.
- `load_side_group_boundary_load_single_solve_0p2_fine`: max von Mises
  `6.526523284e6 Pa`, inner-ring max von Mises `1.100733554e7 Pa`, max
  displacement `6.570435359e-3 m`, native PNG
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p2_fine/stage_plots/single_solve_3_roller_boundary_load_0p2n_fine_parametric_native_volume.png`.

Both configured MPHs were audited with no-solve diagnostics:
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p13/diagnostics_0p13n_single_solve/`
and
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p14/diagnostics_0p14n_single_solve/`
and
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p145/diagnostics_0p145n_single_solve/`
and
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p1475/diagnostics_0p1475n_single_solve/`,
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p14875/diagnostics_0p14875n_single_solve/`,
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p149375/diagnostics_0p149375n_single_solve/`, and
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p15_fine/diagnostics_0p15n_fine_single_solve/`,
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p1625/diagnostics_0p1625n_single_solve/`, and
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p175/diagnostics_0p175n_single_solve/`, and
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p1875/diagnostics_0p1875n_single_solve/`, and
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p19375/diagnostics_0p19375n_single_solve/`, and
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p196875/diagnostics_0p196875n_single_solve/`,
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p1984375/diagnostics_0p1984375n_single_solve/`, and
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p2_fine/diagnostics_0p2n_fine_single_solve/`.
The diagnostics confirm the expected `radial_load` parametric sweeps, active
inner-bore `BoundaryLoad`, inactive displacement preload, active `1/2/12`
roller contacts, inactive cage contacts, weak guidance, and weak roller
foundations. These are still diagnostic stages: three rollers only, cage off,
temporary stabilization active, weak guidance active, matrix-level stress
plateau rejection active, missing historical per-roller stress-probe evidence,
and no verified reaction.

The coarse barrier-localization step,
`load_side_group_boundary_load_single_solve_0p15`, was run to determine whether
the `0.2 N` failure occurred before or after `0.15 N`. It saved the configured
MPH but did not produce a native PNG; after a long silent solve it was
interrupted and the summary recorded `Solve failed:
java.lang.NullPointerException`. Artifacts:

- summary:
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p15/direct_3d_bearing_summary.json`
- configured MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p15/stage_models/single_solve_3_roller_boundary_load_0p15n_parametric_configured.mph`
- no-solve diagnostic:
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p15/diagnostics_0p15n_single_solve/stage_mph_diagnostic.json`

The diagnostic confirms `useparam=on`, `pname=['radial_load']`, and
`plistarr=['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.15']`, with
the same active `BoundaryLoad`, active `1/2/12` roller contacts, inactive cage
contacts, active weak guidance, and inactive displacement preload. A subsequent
`load_side_group_boundary_load_single_solve_0p15_fine` rerun added
`0.13 0.14 0.145 0.1475 0.14875 0.149375` before the final `0.15 N` step and
did converge, so the old `0.15 N` failure is now treated as continuation-step
sensitivity evidence rather than an absolute load-amplitude barrier.

The earlier coarse
`load_side_group_boundary_load_single_solve_0p2` step was also run. It saved the
configured MPH but did not produce a native PNG; after a long silent solve it
was interrupted and the summary likewise recorded `Solve failed:
java.lang.NullPointerException`. This is now retained as coarse-ramp failure
evidence, not proof that `0.2 N` is unreachable. Artifacts:

- summary:
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p2/direct_3d_bearing_summary.json`
- configured MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p2/stage_models/single_solve_3_roller_boundary_load_0p2n_parametric_configured.mph`
- no-solve diagnostic:
  `runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_single_solve_0p2/diagnostics_0p2n_single_solve/stage_mph_diagnostic.json`

The `0.2 N` diagnostic confirms the intended stage setup: `useparam=on`,
`pname=['radial_load']`,
`plistarr=['0.001 0.005 0.01 0.05 0.1 0.1005 0.101 0.105 0.12 0.15 0.2']`,
active `load_inner_bore`, inactive displacement preload, active contacts for
rollers `1/2/12`, inactive cage contacts, active weak guidance, and active weak
roller foundations. The current fresh-solver BoundaryLoad path is numerically
validated through fine `0.2 N`, using the additional
`0.19375 0.196875 0.1984375 0.2` continuation tail. Do not run or report `1 N`
as a meaningful solved design stage until the stress-plateau/constraint-dominance
issue, large displacement, temporary active-roller spring, weak guidance, and
missing verified reaction are repaired.

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --contact-stage-mode all_raceway_continuous_boundary_load \
  --cores 1 \
  --archive-path runtime_smoke/bearing_family_p12_continuous_boundary_load/bearing3d_continuous_boundary_load.sqlite3 \
  --artifact-root runtime_smoke/bearing_family_p12_continuous_boundary_load/bearing3d_continuous_boundary_load \
  --model-name bearing3d_continuous_boundary_load
```

If this mode converges through `continuous_boundary_load_high_ramp_retained_preload`,
that native COMSOL PNG is the highest-trust BoundaryLoad-continuation image, but
it is still not design-grade while displacement preload or weak guidance remain
active. If it fails, preserve the failed model/error and keep
`legacy_raceway_highload_direct` as a labeled raceway-only visual fallback.

The 2026-07-07 run at
`runtime_smoke/bearing_family_p12_continuous_boundary_load/bearing3d_continuous_boundary_load`
failed at the first stage,
`continuous_boundary_load_contact_closure_1n`, before any native stage PNG was
available. COMSOL reported that the initial parameter solution could not be
found, the segregated iteration limit was reached, and the returned solution did
not converge. The failed MPH was saved to
`runtime_smoke/bearing_family_p12_continuous_boundary_load/bearing3d_continuous_boundary_load/failed_3d_contact_model.mph`.
This is evidence that keeping `BoundaryLoad` active is not enough when the same
inner-bore surface also carries prescribed displacement. The next repair should
split contact-closure control from the bore load surface, or use a
displacement-controlled preload plus reaction/contact-pressure extraction path.
The script includes a split-control diagnostic for that next step:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --contact-stage-mode all_raceway_split_control_boundary_load \
  --cores 1 \
  --archive-path runtime_smoke/bearing_family_p12_split_control_boundary_load/bearing3d_split_control_boundary_load.sqlite3 \
  --artifact-root runtime_smoke/bearing_family_p12_split_control_boundary_load/bearing3d_split_control_boundary_load \
  --model-name bearing3d_split_control_boundary_load
```

This mode keeps the bore `BoundaryLoad` active but rebinds the displacement
closure feature to `sel_inner_raceway_contact`. Its summary records
`displacement_preload_selection` so the remaining stabilization is explicit.

The 2026-07-07 split-control run at
`runtime_smoke/bearing_family_p12_split_control_boundary_load/bearing3d_split_control_boundary_load`
also failed at the first stage,
`split_control_boundary_load_contact_closure_0p1n`, before any native stage PNG
was available. The failed MPH was saved to
`runtime_smoke/bearing_family_p12_split_control_boundary_load/bearing3d_split_control_boundary_load/failed_3d_contact_model.mph`.
The residual dropped compared with the same-surface attempt, but COMSOL still
reported no initial parameter solution and a segregated-iteration limit. Treat
full all-12 BoundaryLoad contact closure as unproven; the next practical path is
either displacement-controlled high-preload with reaction/contact-pressure
extraction, or a load-side/group-ramped BoundaryLoad closure before returning to
the full all-12 high-load stage.

The displacement-control reaction-equivalent diagnostic can be run with:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --contact-stage-mode all_raceway_high_preload_reaction_equivalent \
  --cores 1 \
  --archive-path runtime_smoke/bearing_family_p12_reaction_equivalent/bearing3d_high_preload_reaction_equivalent.sqlite3 \
  --artifact-root runtime_smoke/bearing_family_p12_reaction_equivalent/bearing3d_high_preload_reaction_equivalent \
  --model-name bearing3d_high_preload_reaction_equivalent
```

This mode keeps the proven all-12 displacement-preload raceway contact path,
exports native COMSOL stage plots, and creates an integration probe on
`sel_inner_bore_load_surface`. It tries multiple reaction-force expression names
and records all candidate failures in `reaction_equivalent.evaluations`. The
current probe also writes `reaction_equivalent.setup_audit`, groups failures in
`reaction_equivalent.candidate_audit`, and tries a selection-bound Java
`IntSurface` numerical integration fallback for `solid.RFx/RFy/RFz`,
`solid.T_stress*`, and stress-tensor traction expressions such as
`solid.sx*nx+solid.sxy*ny+solid.sxz*nz`. This means an unknown component-coupling
operator no longer prevents every real reaction or traction candidate from being
attempted. Only a successful nonzero candidate may be used as equivalent load
evidence; otherwise the summary must say the equivalent force was not verified.

On 2026-07-07, rerun
`runtime_smoke/bearing_family_p12_reaction_equivalent/bearing3d_high_preload_reaction_equivalent_rerun`
converged through `raceway_contact_high_preload_reaction_equivalent` and
exported the native COMSOL Volume PNG
`runtime_smoke/bearing_family_p12_reaction_equivalent/bearing3d_high_preload_reaction_equivalent_rerun/stage_plots/raceway_contact_high_preload_reaction_equivalent_native_volume.png`.
The stage reported max von Mises `9283.9437 Pa`, inner-ring max von Mises
`10590.748 Pa`, max displacement `2.3097057e-4 m`, and contact-pressure estimate
`1.953125e6 Pa`. It remains a displacement-controlled high-preload diagnostic:
the image scale is `x10^3 Pa`, cage contact is inactive, weak roller foundation
is active, and `reaction_equivalent.success` is false. The probe setup created
the integration coupling, set `opname`, and bound `sel_inner_bore_load_surface`,
but both `mph.evaluate(...)` and Java `EvalGlobal/getReal()` reported
`Unknown function or operator` for `intop_displacement_reaction_probe(...)`.
Do not use this run as equivalent high-load evidence until a real reaction
expression evaluates successfully.

On 2026-07-13, the `IntSurface` fallback was tested in
`runtime_smoke/bearing_family_p12_reaction_equivalent/bearing3d_high_preload_reaction_equivalent_intsurface_nonzero_gate`.
The same high-preload raceway stage solved and exported a native COMSOL Volume
PNG, but reaction verification still did not pass: 28 candidates were recorded,
6 selection-bound `java_intsurface` candidates evaluated successfully, and all
six returned `0.0 N` on `sel_inner_bore_load_surface`. The summary therefore
sets `reaction_equivalent.success=false`,
`evaluated_candidate_success_count=6`, `successful_candidate_count=0`, and
warns that no nonzero reaction was found. This artifact proves the operator
fallback is recorded, but it is not verified load-closure evidence.

On 2026-07-14, no-solve diagnostics were refreshed for the same run. The
pre-solve configured MPH
`runtime_smoke/bearing_family_p12_reaction_equivalent/bearing3d_high_preload_reaction_equivalent_intsurface_nonzero_gate/stage_models/raceway_contact_high_preload_reaction_equivalent_configured.mph`
does not contain `intop_displacement_reaction_probe`, because that coupling is
created after the solve when reaction candidates are evaluated. The saved result
package MPH does contain the coupling; diagnostic artifact
`runtime_smoke/bearing_family_p12_reaction_equivalent/bearing3d_high_preload_reaction_equivalent_intsurface_nonzero_gate/diagnostics_reaction_equivalent_package_model_current/stage_mph_diagnostic.json`
shows type `Integration`, `opname=intop_displacement_reaction_probe`, and
selection `sel_inner_bore_load_surface` bound to 8 boundary entities. Future
reaction-equivalent runs now also save a `post_reaction_probe_model_save` MPH so
the exact post-probe coupling state can be replayed without relying only on the
final package model.

The clean 2026-07-14 rerun
`runtime_smoke/bearing_family_p12_reaction_equivalent/bearing3d_high_preload_reaction_equivalent_current_audit3`
converged through `raceway_contact_high_preload_reaction_equivalent` and exported
native PNG
`stage_plots/raceway_contact_high_preload_reaction_equivalent_native_volume.png`.
It reports max von Mises `9283.943687400591 Pa`, inner-ring max
`10590.748020054052 Pa`, and max displacement `2.30970568117654e-4 m`.
`reaction_equivalent.setup_audit.success=true`: the coupling exists, type is
`Integration`, `opname=intop_displacement_reaction_probe`, and
`sel_inner_bore_load_surface` is bound to 8 entities. Reaction verification still
fails: `candidate_count=40`, `evaluated_candidate_success_count=9`,
`successful_candidate_count=0`, with candidate classes
`unknown_operator=23`, `zero_result=9`, and `selection_error=8`. The replay MPH
`stage_models/raceway_contact_high_preload_reaction_equivalent_post_reaction_probe_configured.mph`
and diagnostic
`diagnostics_post_reaction_probe_mph/stage_mph_diagnostic.json` confirm the same
post-probe coupling/opname/selection state. A no-solve saved-MPH replay is
recorded at `reaction_probe_post_mph/reaction_probe_summary.json` and
`reaction_probe_post_mph/reaction_probe_summary.md`; it repeats the same
non-verified result (`candidate_count=40`, `successful_candidate_count=0`,
`unknown_operator=23`, `zero_result=9`, `selection_error=8`). This is strong
diagnostic evidence, not verified reaction/load-closure evidence.

The load-side group-ramped BoundaryLoad diagnostic can be run with:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --contact-stage-mode load_side_group_boundary_load \
  --cores 1 \
  --archive-path runtime_smoke/bearing_family_p12_group_boundary_load/bearing3d_group_boundary_load_free.sqlite3 \
  --artifact-root runtime_smoke/bearing_family_p12_group_boundary_load/bearing3d_group_boundary_load_free \
  --model-name bearing3d_group_boundary_load_free
```

This mode keeps the inner-bore `BoundaryLoad` active from the first stage and
ramps contact participation from load-side 3 rollers to 6 rollers to all 12
rollers. The first implementation used raceway displacement closure and failed
at `load_side_3_roller_boundary_closure_0p1n` with "relative step too small".
The free-closure implementation removed prescribed displacement preload and
converged the first 3-roller 0.1 N bootstrap stage with temporary active-roller
fixation and weak inner guidance. That run exported native COMSOL PNG
`runtime_smoke/bearing_family_p12_group_boundary_load/bearing3d_group_boundary_load_free/stage_plots/load_side_3_roller_boundary_closure_0p1n_native_volume.png`
and reported max von Mises `6.526523e6 Pa`, inner-ring max von Mises
`1.1007336e7 Pa`, max displacement `2.060695e-3 m`, and contact-pressure
estimate `65.104 Pa`. The next stage,
`load_side_3_roller_boundary_low_ramp`, failed after removing temporary
active-roller fixation and ramping toward 50 N. Treat this as useful
BoundaryLoad bootstrap evidence only; it is not a converged all-12 high-load
stage and not a production design gate.

A follow-up release-stage attempt inserted a no-fix 0.001-0.1 N release stage
before the 50 N ramp. It ran for an extended period and was manually
interrupted, leaving an interrupted summary at
`runtime_smoke/bearing_family_p12_group_boundary_load/bearing3d_group_boundary_load_release/direct_3d_bearing_summary.json`.
Because the process was interrupted before the normal failed-MPH packaging
block, do not use that run as solver success evidence.

The next local repair keeps the same `load_side_group_boundary_load` CLI mode
but splits the release path into smaller auditable stages:
`load_side_3_roller_boundary_spring_decay_5e9_0p1n` and
`load_side_3_roller_boundary_spring_decay_2e9_0p1n` weaken the roller
foundation without changing mesh or increasing load,
`load_side_3_roller_boundary_release_active_spring_0p1n` releases temporary
active-roller spring stabilization while staying at 0.1 N, then
`load_side_3_roller_boundary_foundation_decay_0p1n` continues the foundation
decay before `load_side_3_roller_boundary_low_ramp_5n` ramps only to 5 N. Only
then does
`load_side_3_roller_boundary_low_ramp_50n` attempt 50 N. This is intended to
avoid the previous abrupt jump from temporary-stabilized 0.1 N directly to an
unstabilized 50 N continuation. Until a real COMSOL run converges through the
all-12 stage, this remains diagnostic BoundaryLoad evidence, not a design gate.

On 2026-07-09, the first version of this repair was tested in
`runtime_smoke/bearing_family_p12_group_boundary_load/bearing3d_group_boundary_load_release_v2`.
The first 3-roller 0.1 N closure stage again solved and exported a native PNG,
but the next stage, which dropped `weak_roller_foundation_k` directly from
`1e10[N/m^3]` to `1e9[N/m^3]`, ran for several minutes without producing a
second-stage image and was manually interrupted. The saved summary records the
best available image as
`stage_plots/load_side_3_roller_boundary_closure_0p1n_native_volume.png` and
does not mark the BoundaryLoad path as successful. The current code therefore
uses the smaller `5e9 -> 2e9 -> release -> 1e9` continuation described above.

The current stable first-path implementation avoids cross-stage physics edits
after a successful solve. It runs a single COMSOL solve with load-side rollers
`[12, 1, 2]` active, inner-bore `BoundaryLoad` active, no displacement preload,
and a parametric load ramp from `0.001 N` to `5 N`. On 2026-07-09,
`runtime_smoke/bearing_family_p12_group_boundary_load/bearing3d_group_boundary_load_release_v8`
completed with exit code 0, exported
`stage_plots/load_side_3_roller_boundary_single_solve_ramp_5n_native_volume.png`,
and saved the model package. The solved metrics were max von Mises
`6.526523e6 Pa`, inner-ring max von Mises `1.1007336e7 Pa`, max displacement
`3.6537803e-2 m`, and contact-pressure estimate `3255.208 Pa`. This is the
first stable BoundaryLoad path, but remains a bootstrap diagnostic because
temporary active-roller spring stabilization, weak roller foundation, weak
inner-ring guidance, and inactive cage contact are still present.

On 2026-07-13, the current `load_side_group_boundary_load` ladder was updated to
make the continuation auditable one variable at a time: 3 active load-side
rollers at `0.1 N -> 0.12 N -> 0.15 N -> 0.2 N -> 0.5 N -> 1 N -> 5 N -> 20 N -> 50 N`,
then 6 rollers at `50 N`, then all 12 rollers at `50 N`. The required
milestones `0.1 N -> 1 N -> 5 N -> 20 N -> 50 N` are preserved; `0.12 N`,
`0.15 N`, `0.2 N`, and `0.5 N` are diagnostic refinement points after the 1 N
solve proved fragile. A real COMSOL run was started at
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder`.
The first stage, `load_side_3_roller_boundary_load_0p1n`, converged with
inner-bore `BoundaryLoad` active, no displacement preload, 3 active rollers,
temporary active-roller spring stabilization, weak roller foundation, weak
inner guidance, and cage contact inactive. It exported a native COMSOL Volume
PNG:

```text
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder/stage_plots/load_side_3_roller_boundary_load_0p1n_native_volume.png
```

The stage metrics were max von Mises `6.526523e6 Pa`, inner-ring max von Mises
`1.1007336e7 Pa`, max displacement `2.0064229e-3 m`, and contact-pressure
estimate `65.104 Pa`. The second stage,
`load_side_3_roller_boundary_load_1n`, failed with
`Solve failed: java.lang.NullPointerException` before exporting a second native
PNG. The script wrote
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder/direct_3d_bearing_summary.json`;
`failed_model_save` also failed because the interrupted COMSOL server was no
longer connected, so no failed MPH exists for this specific run. Treat the
0.1 N image as BoundaryLoad bootstrap evidence only, not high-load or
production-ready evidence. After this run, the post-0.1 N stages were changed
from reused parametric sweeps to single-point fixed-load solves with fresh
solver sequences to diagnose whether the `NullPointerException` came from
solver/continuation reuse rather than the physical 1 N state itself.

The checkpoint-enabled rerun at
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_checkpoint`
confirmed that the next fixed-load stage is already fragile at `0.2 N`, before
the requested `1 N` milestone. `load_side_3_roller_boundary_load_0p1n` again
converged and exported a native Volume PNG, while
`load_side_3_roller_boundary_load_0p2n` failed with
`Solve failed: java.lang.NullPointerException`. Unlike the earlier run, this
rerun saved pre-solve configured MPH checkpoints:

```text
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_checkpoint/stage_models/load_side_3_roller_boundary_load_0p1n_configured.mph
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_checkpoint/stage_models/load_side_3_roller_boundary_load_0p2n_configured.mph
```

Use the `0p2n_configured.mph` checkpoint for the next COMSOL diagnosis. The
likely next branches are: reduce the first post-bootstrap load step below
`0.2 N`, soften or remove weak inner guidance in a controlled single-variable
test, or inspect the 0.2 N configured model for solver-sequence/contact-pair
state corruption before solving. This remains diagnostic evidence only.

The follow-up fine continuation run at
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine012`
reduced the first post-bootstrap step to `0.12 N` while keeping the same
3 load-side rollers, BoundaryLoad, contact penalty, weak inner guidance, and
temporary spring policy. `load_side_3_roller_boundary_load_0p1n` again
converged and exported a native Volume PNG, with max von Mises
`6.526523e6 Pa` and max displacement `2.0064229e-3 m`.
`load_side_3_roller_boundary_load_0p12n` saved its configured MPH but failed
with `Solve failed: java.lang.NullPointerException` before exporting a native
PNG. `failed_model_save` failed after COMSOL disconnected, so the reproducible
artifact for this stage is the configured MPH:

```text
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine012/stage_models/load_side_3_roller_boundary_load_0p12n_configured.mph
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine012/direct_3d_bearing_summary.json
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine012/diagnostics_0p12n/stage_mph_diagnostic.json
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine012/diagnostics_0p12n/stage_mph_diagnostic.md
```

The no-solve diagnostic confirms that the `0.12 N` checkpoint has
`load_inner_bore` active as `BoundaryLoad` on `sel_inner_bore_load_surface`
with `FperArea=['inner_bore_load_pressure','0','0']`, active inner/outer
Contact features for rollers `1`, `2`, and `12` using
`pn_penalty=5e-5*E_steel`, `irlx=0.12`, `tolcontact=3[um]`, and
`zeroInitGap=0`, plus active weak inner guidance and inactive displacement
preload. The next single-variable diagnostic cleared stale stationary study
parametric fields and inserted `0.105 N` as the first post-bootstrap load
point. The first clean-study attempt at
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0105_cleanstudy`
saved `failed_3d_contact_model.mph`, but the no-solve diagnostic showed COMSOL
had re-enabled `useparam=on` when the single-point `plistarr=['0.105']` was
written. The code was then changed to write `useparam=off` after
`createAutoSequences('sol')` and after `pname/plistarr/punit`.

The rerun at
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0105_useparamoff_last`
confirmed the configured MPH has `useparam=off`, `pname=['radial_load']`,
`plistarr=['0.105']`, and `punit=['N']`. The `0.105 N` solve still failed with
solid-mechanics nonconvergence (`relative step size too small`) and did not
export a native PNG, but it saved both pre-solve and failed MPH artifacts:

```text
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0105_useparamoff_last/stage_models/load_side_3_roller_boundary_load_0p105n_configured.mph
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0105_useparamoff_last/failed_3d_contact_model.mph
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0105_useparamoff_last/direct_3d_bearing_summary.json
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0105_useparamoff_last/diagnostics_0p105n/stage_mph_diagnostic.json
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0105_useparamoff_last/diagnostics_0p105n/stage_mph_diagnostic.md
```

The next run at
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0101`
reduced only the first post-bootstrap load to `0.101 N`. The configured MPH
diagnostic again confirmed `useparam=off`, `pname=['radial_load']`,
`plistarr=['0.101']`, `punit=['N']`, active inner-bore `BoundaryLoad`, active
inner/outer contact for rollers `1`, `2`, and `12`, active weak inner guidance,
and inactive displacement preload. The `0.101 N` solve still failed with
solid-mechanics nonconvergence (`relative step size too small`) and no native
PNG, but saved a failed MPH:

```text
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0101/stage_models/load_side_3_roller_boundary_load_0p101n_configured.mph
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0101/failed_3d_contact_model.mph
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0101/direct_3d_bearing_summary.json
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0101/diagnostics_0p101n/stage_mph_diagnostic.json
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_ladder_fine0101/diagnostics_0p101n/stage_mph_diagnostic.md
```

The next controlled branches should change weak inner guidance stiffness or
contact penalty/relaxation, one main variable at a time; further load-only
reductions below `0.101 N` may be useful only to locate the exact bifurcation
near the `0.1 N` bootstrap. This is still not production-ready.

The soft-guidance diagnostic at
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_soft_guidance_k1e4`
kept the same 3 load-side rollers and inner-bore `BoundaryLoad`. The baseline
`0.1 N` parametric bootstrap again solved with max von Mises
`6.526523e6 Pa` and max displacement `2.0064229e-3 m`. The same-load
single-point stage also returned a solver success and native COMSOL Volume PNG,
but the field values were physically invalid: max von Mises
`1.4365898775071404e13 Pa`, inner-ring max von Mises
`7.590702394553797e13 Pa`, and max displacement `20.100776441512814 m`.
The stage evidence matrix therefore marks
`soft_guidance_3_roller_boundary_load_0p1n_singlepoint` with
`physical_plausibility_success=false` and must not select that PNG as bearing
stress evidence. The following `0.1 N` stage with weak inner guidance softened
to `1e4[N/m^3]` failed with `java.lang.NullPointerException`; the no-solve
configured-MPH diagnostic at
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_soft_guidance_k1e4/diagnostics_0p1n_k1e4/stage_mph_diagnostic.json`
confirms `useparam=off`, `plistarr=['0.1']`, active BoundaryLoad/contact/weak
guidance, and inactive displacement preload. The next single-variable branch
should adjust contact penalty/relaxation or stabilization, not report the
single-point native PNG as physical success.

The next single-variable contact-penalty diagnostic was run at
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_contact_relaxation_penalty1e5`.
It kept 3 load-side rollers, the inner-bore `BoundaryLoad`, weak inner
guidance, weak roller foundation, and active-roller spring stabilization, but
changed the post-bootstrap contact penalty from `5e-5*E_steel` to
`1e-5*E_steel`. The `0.1 N` bootstrap again solved and exported a native PNG.
The `0.1 N` softened-penalty single-point stage also solved and exported a
native PNG, but reproduced the same physically invalid field as the
soft-guidance run: max von Mises `1.4365898775071404e13 Pa` and max
displacement `20.100776441512814 m`; the matrix therefore rejects it by
`physical_plausibility_success=false`. The following `0.101 N` softened-penalty
stage failed with `java.lang.NullPointerException`; no failed MPH was saved
because the run was interrupted after a long second-stage solve, but the
configured MPH and no-solve diagnostic are available:

```text
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_contact_relaxation_penalty1e5/stage_models/contact_relaxation_3_roller_boundary_load_0p101n_penalty1e5_configured.mph
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_contact_relaxation_penalty1e5/diagnostics_0p101n_penalty1e5/stage_mph_diagnostic.json
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_contact_relaxation_penalty1e5/diagnostics_0p101n_penalty1e5/stage_mph_diagnostic.md
```

This branch shows that softening penalty alone does not repair the post-bootstrap
load-control path; the next diagnostic should change stabilization/release
strategy or solve formulation, not present the softened-penalty native PNG as
physical evidence.

The micro-parametric continuation diagnostic was run at
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_micro_continuation_0p101`.
It keeps the same 3 load-side rollers, inner-bore `BoundaryLoad`, weak inner
guidance, weak roller foundation, active-roller spring, contact penalty, contact
relaxation, mesh, and cage-off state as the baseline. The only intended change
after the `0.1 N` bootstrap is solver formulation: instead of a fixed
single-point `0.101 N` solve, it uses a parametric micro-continuation
`0.1 0.1005 0.101`. The bootstrap again solved and exported a native PNG. The
`0.101 N` micro-continuation stage did not export a PNG and was interrupted
after a long solve; the script summary records
`Solve failed: java.lang.NullPointerException`. The configured MPH diagnostic
confirms the study was correctly configured with `useparam=on`,
`pname=['radial_load']`, `plistarr=['0.1 0.1005 0.101']`, and `punit=['N']`,
with active BoundaryLoad and weak guidance:

```text
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_micro_continuation_0p101/stage_models/micro_continuation_3_roller_boundary_load_0p101n_parametric_configured.mph
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_micro_continuation_0p101/diagnostics_0p101n_parametric/stage_mph_diagnostic.json
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_micro_continuation_0p101/diagnostics_0p101n_parametric/stage_mph_diagnostic.md
```

This narrows the failure from stale study settings toward the actual
load-control/contact/stabilization formulation. It still provides only
diagnostic evidence; the sole native PNG from this run is the same `0.1 N`
bootstrap and must not be used as the requested high-load design image.

The fixed-active-roller stabilization diagnostic was run at
`runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_fixed_stabilization_0p101`.
It keeps the same 3 load-side rollers, BoundaryLoad, contact penalty/relaxation,
mesh, weak inner guidance, weak roller foundation, and cage-off state, but
switches the post-bootstrap active-roller stabilization from spring foundation
to fixed roller boundary constraints. The `0.1 N` bootstrap again solved and
exported a native PNG. The `0.1 N` fixed-active stage did not export a native
PNG and was interrupted after a long solve; the summary records
`Solve failed: java.lang.NullPointerException`. The no-solve MPH diagnostic
confirms `useparam=off`, `plistarr=['0.1']`, active `load_inner_bore`
`BoundaryLoad`, and active fixed constraints on rollers `1`, `2`, and `12`:

```text
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_fixed_stabilization_0p101/stage_models/fixed_stabilization_3_roller_boundary_load_0p1n_fixed_active_configured.mph
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_fixed_stabilization_0p101/diagnostics_0p1n_fixed_active/stage_mph_diagnostic.json
runtime_smoke/bearing_family_p12_boundaryload_continuation/bearing3d_load_side_boundaryload_fixed_stabilization_0p101/diagnostics_0p1n_fixed_active/stage_mph_diagnostic.md
```

This shows that replacing active-roller spring stabilization with fixed active
roller constraints does not repair the BoundaryLoad path; it fails earlier at
the same load level and remains diagnostic-only.

The older guided experiments below kept all 12 roller/raceway Contact Pairs
active and used the named `BoundaryLoad`, plus an explicitly labeled weak
inner-ring guidance spring, but they switched from displacement preload to
load control only in the final stage:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --contact-stage-mode all_raceway_guided_probe_1n \
  --cores 1 \
  --archive-path runtime_smoke/bearing_family_p12_guided_boundary_load/bearing3d_guided_probe_1n.sqlite3 \
  --artifact-root runtime_smoke/bearing_family_p12_guided_boundary_load/bearing3d_guided_probe_1n \
  --model-name bearing3d_guided_probe_1n
```

On 2026-07-07, both the guided `1N` probe and the guided `1..100N` low-load
transfer attempt completed the coarse/refined displacement-preload stages and
exported native COMSOL Volume plots, but the subsequent `BoundaryLoad` transfer
stage did not converge before interruption. The relevant summaries are:

- `runtime_smoke/bearing_family_p12_guided_boundary_load/bearing3d_guided_probe_1n/direct_3d_bearing_summary.json`
- `runtime_smoke/bearing_family_p12_guided_boundary_load/bearing3d_guided_low_load/direct_3d_bearing_summary.json`

This proves the current failure is the load-control transition itself, not just
the requested high-load magnitude. Next repairs should keep a continuous
load/constraint path, for example by solving a displacement-controlled contact
stage and extracting reactions, or by activating the boundary load from the
start of the continuation path instead of turning off displacement preload and
turning on `BoundaryLoad` in the final stage.

When answering image questions, read
`direct_3d_bearing_summary.json.requested_stage_image` first. If it reports
`best_available_native_stage_is_not_high_load`, the low-preload native image may
be shown only as diagnostic evidence and must not be described as the requested
high-load stress result.

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
outer ring, twelve cylindrical rollers, a cage ring with twelve real cylindrical
Boolean pocket cutouts, local per-roller roller/raceway contact patches, 24
explicit Contact Pair features, assembly finalization, a radial smoke load, a
stationary Solid Mechanics study, and a `PlotGroup3D` von Mises result.

Inspect the reproducible 3D prompt fixtures without calling LLM or COMSOL:

```bash
python3 scripts/run_agent_3d_bearing_full_demo.py --print-prompts
```

Check the verified 3D full-bearing fixture without starting COMSOL:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --use-verified-fixture --skip-comsol
```

Run the free-generation 3D draft path without COMSOL. The draft step extracts
the first fenced `model.*` code block inside `GENERATED_CODE_START/END`, ignores
prose outside the fence, normalizes common Java-ish literals such as `true`,
quoted `{...}` arrays, and `new double[]`/`new String[]`/`new int[]` array
literals into Python/MPh syntax, and records that as
`offline_syntax_normalization`. In strict mode the script fails rather than
replacing the generated draft with the complete verified fallback:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --skip-comsol --require-free-generated-code
```

When proxy or API gateways are unstable for a single large code-generation
response, use segmented generation. In this mode the model is responsible only
for local segment code, while the Python driver owns the interface contract,
assembly, validation, retry, and failure artifact:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --skip-comsol --require-free-generated-code --segmented-generation \
  --segment-llm-max-tokens 5000 --segment-max-retries 3 \
  --segment-timeout-seconds 90
```

Segmented generation uses four manifest-checked segments:

1. `A_base_geometry`: parameters, `comp1`, `geom1`, inner/outer rings, and
   `cage_annulus`.
2. `B_cage_pockets_and_rollers`: `cage_pocket_1..12`, cage `Difference`, and
   `roller_1..12`.
3. `C_selections_contacts_physics`: named selections, materials, Solid
   Mechanics, inner-bore `BoundaryLoad` audit plus `Displacement2` preload, 36
   Contact Pairs, Contact features for roller/raceway and roller/cage-pocket
   interfaces, per-roller Maximum coupling operators, and a cage Maximum
   coupling operator.
4. `D_mesh_study_results`: assembly finalization, mesh, stationary study,
   `PlotGroup3D`, global numerical outputs, per-roller probes, and cage
   stress/displacement probes.

Each segment must return `SEGMENT_MANIFEST_START/END` JSON plus
`GENERATED_CODE_START/END` code. The local assembler rejects missing
dependencies, duplicate tags, forbidden operations such as recreating `comp1`
or `geom1`, namespace drift, and final code that fails
`validate_3d_bearing_code_draft(require_named_selections=True)`. Segment
artifacts are written to
`runtime_smoke/bearing_3d_full_demo/segmented_generation/`; if a segment fails
after retries or times out, the driver writes
`runtime_smoke/bearing_3d_full_demo/segmented_generation_failure.json` and, in
strict mode, does not replace the draft with the verified fallback.

Run the direct 3D fixture smoke against local COMSOL:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run --cores 1
```

The current verified fixture keeps the radial load on
`sel_inner_bore_load_surface` as a `BoundaryLoad/FperArea` audit feature and
uses a small `Displacement2/U0` inner-bore preload to close the contact chain.
The older inner-ring domain `BodyLoad/FperVol` pattern is rejected by
`validate_3d_bearing_code_draft`. The cage is a Boolean solid with material,
named body selection, scoped stress/displacement probes, and 12 explicit
roller-to-cage-pocket Contact Pairs. Cage-pocket clearance/contact settings
still need design-specific calibration.

Latest verified local COMSOL 6.2 direct fixture using the 12-roller Boolean-cage
code before the inner-bore load/cage-probe contract update:

- Template execution run id:
  `direct_3d_bearing_fixture_20260704_181424_590737`
- Result package run id:
  `direct_3d_bearing_package_agent_3d_bearing_model_20260704_181513_005517`
- von Mises stress maximum: about `3.172e6` Pa
- Contact pressure estimate: about `1.953e6` Pa
- Maximum displacement: about `3.361e-3` m
- Runtime selection binding: `65/65` required selections bound by entity-count
  probe
- Physical quality gate: `production_physics_gate`
- Contact convergence report: `contact_runtime_convergence_checked`
- Stress PNG:
  `runtime_smoke/bearing_3d_full_demo/bearing_3d_von_mises.png`
- Package JSON:
  `runtime_smoke/bearing_3d_full_demo/result_packages/direct_3d_bearing_package_agent_3d_bearing_model_20260704_181513_005517/summary.json`
- Package Markdown:
  `runtime_smoke/bearing_3d_full_demo/result_packages/direct_3d_bearing_package_agent_3d_bearing_model_20260704_181513_005517/report.md`
- Model:
  `runtime_smoke/bearing_3d_full_demo/result_packages/direct_3d_bearing_package_agent_3d_bearing_model_20260704_181513_005517/agent_3d_bearing_model.mph`

Key modeling details:

- Cage geometry is a real solid Boolean: cage annulus minus twelve cylindrical
  `cage_pocket_N` cutters.
- Ring and roller geometry features enable boundary-level `selresult`; contact
  patches are `Intersection` selections between object boundary selections and
  local Box patches.
- Each roller has inner and outer contact selections; each raceway side has a
  local per-roller destination patch; each Contact Pair uses
  `manualSelection(True)`.
- Contact features use penalty formulation for the smoke solve.
- Per-roller `Maximum` coupling operators support scoped
  `maxop_roller_N(solid.mises)` evaluation.
- Stress PNG output is rendered from solved COMSOL `x`/`y`/`solid.mises` field
  samples when the default COMSOL image export is sparse.
- The Markdown/HTML report records lineage for this run:
  `workflow=bearing_3d_direct_fixture`, `quality_gate=true/smoke`,
  `repair_history_count=1`, and `require_free_generated_code=false`.
- The package summary additionally records `selection_binding_runtime_checked=true`,
  `physical_result_production_ready=true`, and `contact_runtime_verified=true`.

Latest strict DeepSeek/API attempt against the 12-roller Boolean-cage contract
failed before generated code extraction because the API connection closed after
three retries. Strict mode skipped complete verified fallback and wrote the
structured failure artifact:

- Failure artifact:
  `runtime_smoke/bearing_3d_full_demo/strict_generation_failure.json`
- Recorded workflow: `bearing_3d_free_generation`
- Recorded `draft_quality.quality_level`: `generation_failed`
- Recorded `repair_history[0].stage`: `llm_generation_failure`
- Recorded `deterministic_runtime_fallback`: `null`

Latest strict DeepSeek `deepseek-v4-pro` evidence with no complete verified
fallback from an earlier successful API window is still the six-roller 3D smoke:

- Template execution run id:
  `agent_3d_bearing_execution_v2_20260701_053449_685816`
- Result package run id:
  `agent_3d_bearing_package_agent_3d_bearing_model_20260701_053659_501236`
- The package summary records `deterministic_runtime_fallback: null`; repair
  stages are `draft`, `offline_syntax_normalization`, and
  `offline_runtime_preflight_repair`.

Artifact lineage and reporting:

- `simulation_run_template` accepts `execution_context` for generated-code runs.
- Archived template execution artifacts persist workflow, quality-gate status,
  repair-history count, last repair stage, and `require_free_generated_code`.
- Markdown/HTML reports expose workflow and repair counts so reviewers can trace
  whether a run used free-generated code, bounded repair, or fallback.
- Result packages include reusable `artifact_qa` answers for maximum stress,
  location, highest-risk roller, cage modeling, contact status, parameters, and
  plot/model paths.

Current 3D modeling limits:

- The 12-roller Boolean-cage fixture solves directly, but the strict
  DeepSeek/API-generated path is currently blocked by API connection failures
  before code extraction and still needs to be revalidated against this stronger
  12-roller Boolean-cage contract.
- Production still needs stronger contact convergence checks, non-symmetric load
  cases, and mesh sensitivity checks before design use.
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
