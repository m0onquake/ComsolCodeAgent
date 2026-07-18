# Roller1 Outer Retained Conformal Narrow Source Closure3um Actual-Area Resume Fresh-Solver Diagnostic

Date: 2026-07-19

## Purpose

Test one variable after the actual-area resume-from-solved-nominal checkpoint failed/hung: remove the existing saved solver sequence from the loaded nominal solved MPH, let the unchanged stage setup create a fresh solver sequence, then solve the same `0.101 N` actual-area BoundaryLoad checkpoint.

This remains a diagnostic experiment. It still uses weak inner guidance, weak roller foundation, temporary active-roller spring stabilization, and cage-inactive scope. It must not be marked production-ready.

## Command

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --resume-actual-area-stage-from-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_20260717_114524_700877/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um.mph \
  --resume-actual-area-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_fresh_solver \
  --resume-actual-area-rebuild-solver \
  --cores 1
```

## Inputs

- Source MPH: solved nominal-pressure narrow-source `roller1_outer_retained_conformal_narrow_source_closure3um` result package.
- Retained conformal target: reused.
- Roller 1 source closure: reused `+3 um`.
- Roller 1 outer contact box tangential half-width: reused `0.9 mm`.
- Contact pair: kept `cp_roller_1_outer_raceway`; no source/destination swap was attempted.
- BoundaryLoad: kept `0.101 N`.
- Active rollers: kept `[12, 1, 2]`.
- Contact settings, weak guidance, temporary active-roller spring, and cage-inactive scope: kept.
- Unique variable: remove old solver sequence `sol1` before actual-area stage setup and solve.

## Result

- Solver-sequence rebuild: pass. Summary records `solver_tags_before=["sol1"]`, `removed_solver_tags=["sol1"]`, and `solver_tags_after=[]`; the configured MPH diagnostic then shows COMSOL recreated `sol1`.
- Actual-area configured checkpoint save: pass.
- Solve success: fail. The run was interrupted after the same no-progress solve behavior and returned `Solve failed: java.lang.NullPointerException`.
- Failed MPH save: fail, because COMSOL/JVM disconnected before the failed checkpoint could be saved: `Not connected to a server`.
- PNG/stress/displacement: unavailable because no solved result exists.
- Contact probe: not run on a solved MPH; pair-specific Tn/gap/source/destination evidence is unavailable.
- Reaction/load balance: fail; no solved reaction or support-reaction evidence exists.

## BoundaryLoad Probe

Command:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-load-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_fresh_solver/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_fresh_solver_configured.mph \
  --load-probe-selection sel_inner_bore_load_surface \
  --load-probe-pressure-expression inner_bore_load_pressure \
  --load-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_fresh_solver/load_probe_configured_mph \
  --cores 1
```

- MPH solution context: `configured_checkpoint`.
- BoundaryLoad feature: `load_inner_bore` exists, active, type `BoundaryLoad`.
- BoundaryLoad selection: `sel_inner_bore_load_surface`, entities `[135, 136, 139, 140, 141, 142, 143, 144]`.
- BoundaryLoad pressure input: `FperArea=["inner_bore_load_pressure", "0", "0"]`.
- Pressure parameter: `inner_bore_load_pressure = radial_load/(4.863178789249815e-3[m^2])`.
- Applied load context: `0.101 N`.
- Area/integrated load/pressure from solution evaluation: unavailable; no solved dataset is usable after fresh solver rebuild and failed solve.
- Load-balance evidence gate: fail, `mph_context_not_valid_for_solved_load_balance`.

## Stage Diagnostic

Command:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --diagnose-stage-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_fresh_solver/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_fresh_solver_configured.mph \
  --diagnose-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_fresh_solver/diagnostics_configured_mph \
  --cores 1
```

- Diagnostic success: true.
- Studies: `["std1"]`.
- Solvers in configured MPH: `["sol1"]`.
- Active raceway contact features: roller 1/2/12 inner and outer contacts active.
- Cage contacts: inactive.
- Weak guidance/stabilization: still active, so this evidence is diagnostic only.

## Evidence Paths

- Summary JSON: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_fresh_solver/direct_3d_bearing_summary.json`
- Configured MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_fresh_solver/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_fresh_solver_configured.mph`
- Stage diagnostic JSON: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_fresh_solver/diagnostics_configured_mph/stage_mph_diagnostic.json`
- Stage diagnostic Markdown: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_fresh_solver/diagnostics_configured_mph/stage_mph_diagnostic.md`
- BoundaryLoad probe JSON: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_fresh_solver/load_probe_configured_mph/load_probe_summary.json`
- BoundaryLoad probe Markdown: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_fresh_solver/load_probe_configured_mph/load_probe_summary.md`
- Solved MPH: unavailable.
- PNG: unavailable.
- Contact/reaction probe reports on solved MPH: unavailable.

## Closure Status

- Code closure: pass for reproducible fresh-solver resume entry and JVM-safe solve failure capture.
- Solve closure: fail.
- Contact transfer closure: fail/unavailable for this experiment.
- Reaction/load balance closure: fail/unavailable for this experiment.
- Engineering physical closure: fail.

Conclusion: removing and regenerating the solver sequence did not resolve the actual-area BoundaryLoad solve failure. The blocker is not only stale solver-sequence reuse; the next diagnostic should target the actual-area pressure solve formulation or a controlled load ramp without changing contact endpoint topology.
