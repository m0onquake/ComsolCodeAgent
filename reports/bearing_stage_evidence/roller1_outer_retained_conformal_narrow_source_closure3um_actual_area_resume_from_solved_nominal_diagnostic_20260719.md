# Roller 1 Outer Retained Conformal Narrow Source Closure + Actual-Area Resume From Solved Nominal Diagnostic

- Date: 2026-07-19
- Status: failed diagnostic experiment, not production-ready
- Stage mode: `load_side_group_boundary_load_single_solve_0p101_actual_area_resume_from_solved_nominal`
- Geometry mode: `roller1_outer_retained_conformal_narrow_source_closure3um`
- Unique variable: load the previously solved nominal-pressure narrow-source MPH, then change only `inner_bore_load_pressure` to `radial_load/(4.863178789249815e-3[m^2])` and solve one `0.101 N` actual-area checkpoint.

## Command

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --resume-actual-area-stage-from-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_20260717_114524_700877/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um.mph \
  --resume-actual-area-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal \
  --cores 1
```

Source solved MPH:

```text
runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_20260717_114524_700877/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um.mph
```

The run loaded the solved nominal MPH, configured the actual-area pressure stage, saved the configured checkpoint MPH, and entered `SOLVE_START`. After about 13 minutes without new output it was interrupted. COMSOL/JVM exited with code `133` and reported `Fatal error in exception handling` at `jp_javaframe.cpp JPJavaFrame 49`.

## Inputs Held Constant

- BoundaryLoad target: `0.101[N]`
- Active rollers: `[12, 1, 2]`
- Contact pair retained: `cp_roller_1_outer_raceway`
- Retained conformal target: reused from the solved nominal narrow-source MPH
- Roller 1 source closure: `+3 um`
- Roller 1 outer contact box tangential half-width: `0.9 mm`
- Contact settings: penalty `5e-5*E_steel`, relaxation `0.12`, tolerance `3[um]`
- Cage contact: inactive
- Diagnostic aids still active: weak inner guidance, weak roller foundations, temporary active-roller spring stabilization, inactive-roller fixed stabilization

## Result

- Source MPH load: pass
- Actual-area configured checkpoint save: pass
- Solve success: fail
- Saved actual-area solved MPH: none
- Result package: none
- Native PNG: none
- Displacement and max stress: unavailable for actual-area solve
- Active roller distribution: unavailable for actual-area solve

## No-Solve Stage Diagnostic

Command:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --diagnose-stage-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_configured.mph \
  --diagnose-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal/diagnostics_configured_mph \
  --cores 1
```

- Diagnostic success: true
- `radial_load`: `0.101[N]`
- `inner_bore_load_pressure`: `radial_load/(4.863178789249815e-3[m^2])`
- Active contact endpoint audit: pass for rollers `[1, 2, 12]`
- Roller 1 outer pair: `cp_roller_1_outer_raceway`
- Roller 1 outer endpoints: source `sel_roller_1_outer_contact`, destination `sel_outer_raceway_1_contact`
- Roller 1 outer source/destination entity counts: `2` / `6`

## BoundaryLoad Probe

Command:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-load-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_configured.mph \
  --load-probe-selection sel_inner_bore_load_surface \
  --load-probe-pressure-expression inner_bore_load_pressure \
  --load-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal/load_probe_configured_mph \
  --cores 1
```

- Probe success: true for expression integration
- Area: `0.004863178789249815 m^2`
- Pressure evaluated by solved-solution context: `44.65180347855952 Pa`
- Integrated load evaluated by solved-solution context: `0.2171497035786822 N`
- Load balance: fail, `missing_applied_boundary_load`

Interpretation: this configured MPH has the actual-area parameter expression in the parameter table, but it still carries the old nominal solved-solution context. The probe therefore reports the stale nominal final-solution load, not a completed actual-area solution. This is diagnostic evidence of the checkpoint state, not a valid actual-area load-closure result.

## Contact And Reaction Evidence

- Contact probe success: false, not run on an actual-area solved MPH
- Pair-specific Tn/gap/source/destination result: unavailable for actual-area solve
- Source/destination imbalance: unavailable for actual-area solve
- External load versus support/contact reaction balance: fail, not evaluated
- Reaction verified: false

## Artifacts

- Summary: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal/direct_3d_bearing_summary.json`
- Configured actual-area checkpoint MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_configured.mph`
- Stage diagnostic: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal/diagnostics_configured_mph/stage_mph_diagnostic.json`
- BoundaryLoad probe: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal/load_probe_configured_mph/load_probe_summary.json`
- Solved MPH: none
- PNG: none

## Gate Decision

- Code closure: not applicable; this was a runtime checkpoint diagnostic using existing helpers.
- Solve closure: fail.
- Contact transfer closure: fail.
- Reaction/load balance closure: fail.
- Engineering physical closure: fail.

Conclusion: checkpoint-resume avoids regenerating the nominal bootstrap and successfully saves an actual-area configured MPH, but the actual-area solve still does not return. No physical closure is achieved.
