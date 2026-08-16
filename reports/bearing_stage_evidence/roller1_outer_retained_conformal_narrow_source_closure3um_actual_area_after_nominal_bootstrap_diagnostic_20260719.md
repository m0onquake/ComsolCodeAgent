# Roller 1 Outer Retained Conformal Narrow Source Closure + Actual-Area After Nominal Bootstrap Diagnostic

- Date: 2026-07-19
- Status: failed diagnostic experiment, not production-ready
- Stage mode: `load_side_group_boundary_load_single_solve_0p101_actual_area_after_nominal_bootstrap`
- Geometry mode: `roller1_outer_retained_conformal_narrow_source_closure3um`
- Unique variable: add a second stage that keeps the solved nominal-pressure bootstrap path, then switches only `inner_bore_load_pressure` to `radial_load/(4.863178789249815e-3[m^2])` for a single `0.101 N` actual-area solve.

## Command

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_narrow_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101_actual_area_after_nominal_bootstrap \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_after_nominal_bootstrap \
  --model-name bearing3d_load_side_boundaryload_0p101_actual_area_after_nominal_bootstrap \
  --cores 1
```

The run produced the template JSON and the first-stage nominal bootstrap configured MPH, then stayed in the solve path with no additional output for about 11 minutes. It was interrupted with exit code `133`; COMSOL/JVM reported `Fatal error in exception handling` at `jp_javaframe.cpp JPJavaFrame 49`.

## Inputs Held Constant

- BoundaryLoad target: `0.101[N]`
- Active rollers: `[12, 1, 2]`
- Contact pair retained: `cp_roller_1_outer_raceway`
- Retained conformal target: reused
- Roller 1 source closure: `+3 um`
- Roller 1 outer contact box tangential half-width: `0.9 mm`
- Contact settings: penalty `5e-5*E_steel`, relaxation `0.12`, tolerance `3[um]`
- Cage contact: inactive
- Diagnostic aids still active: weak inner guidance, weak roller foundations, temporary active-roller spring stabilization, inactive-roller fixed stabilization

## Result

- Solve success: fail
- First stage reached: nominal bootstrap configured MPH saved
- Second stage reached: no
- Saved solved MPH: none
- Result package: none
- Native PNG: none
- Displacement and max stress: unavailable; no trustworthy solved field exists
- Active roller distribution: unavailable; no per-roller solved probes were produced

Important interpretation: this run did not evaluate the actual-area-after-bootstrap physics. The only available MPH is the nominal-pressure bootstrap configured model, with `inner_bore_load_pressure = radial_load/(pi*inner_diameter*bearing_width)`.

## No-Solve Stage Diagnostic

Command:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --diagnose-stage-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_after_nominal_bootstrap/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph \
  --diagnose-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_after_nominal_bootstrap/diagnostics_configured_mph \
  --cores 1
```

- Diagnostic success: true
- Configured model: `single_solve_3_roller_boundary_load_0p101n_parametric_configured`
- `radial_load`: `0.101[N]`
- `inner_bore_load_pressure`: `radial_load/(pi*inner_diameter*bearing_width)`
- Pair endpoint consistency: pass for active rollers `[1, 2, 12]`
- Roller 1 outer pair: `cp_roller_1_outer_raceway`
- Roller 1 outer endpoints: source `sel_roller_1_outer_contact`, destination `sel_outer_raceway_1_contact`
- Roller 1 outer source/destination entity counts: `2` / `6`

## BoundaryLoad Probe

Command:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-load-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_after_nominal_bootstrap/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph \
  --load-probe-selection sel_inner_bore_load_surface \
  --load-probe-pressure-expression inner_bore_load_pressure \
  --load-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_after_nominal_bootstrap/load_probe_configured_mph \
  --cores 1
```

- Probe path: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_after_nominal_bootstrap/load_probe_configured_mph/load_probe_summary.json`
- Probe success: false
- Feature audit: success
- Selection: `sel_inner_bore_load_surface`
- Selection entities: `[135, 136, 139, 140, 141, 142, 143, 144]`
- Area: unavailable in this no-solve probe
- Integrated load: unavailable
- Load balance: fail, `missing_integrated_boundary_load`

## Contact And Reaction Evidence

- Contact probe success: false, not run on a solved MPH
- Pair-specific Tn/gap/source/destination result: unavailable
- Source/destination imbalance: unavailable
- External load versus contact/support reaction balance: fail, not evaluated
- Reaction verified: false

## Artifacts

- Summary: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_after_nominal_bootstrap/direct_3d_bearing_summary.json`
- Template JSON: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_after_nominal_bootstrap/template_runs/direct_3d_bearing_fixture_20260718_200739_268481.json`
- Configured stage MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_after_nominal_bootstrap/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`
- Stage diagnostic: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_after_nominal_bootstrap/diagnostics_configured_mph/stage_mph_diagnostic.json`
- BoundaryLoad probe: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_after_nominal_bootstrap/load_probe_configured_mph/load_probe_summary.json`
- Solved MPH: none
- PNG: none

## Gate Decision

- Code closure: pass for mode wiring and static unit coverage.
- Solve closure: fail.
- Contact transfer closure: fail.
- Reaction/load balance closure: fail.
- Engineering physical closure: fail.

Conclusion: the two-stage actual-area-after-nominal-bootstrap path did not reach a solved, probeable actual-area stage. It remains a failed diagnostic experiment and cannot be counted as reaction verified or production ready.
