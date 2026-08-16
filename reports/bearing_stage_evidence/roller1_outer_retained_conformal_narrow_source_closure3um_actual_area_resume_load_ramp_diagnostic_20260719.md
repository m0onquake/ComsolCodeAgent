# Roller1 Outer Retained Conformal Narrow Source Closure3um Actual-Area Resume Load-Ramp Diagnostic

Date: 2026-07-19

## Purpose

Test one variable after both the actual-area resume checkpoint and fresh-solver
resume diagnostics failed: keep the solved nominal-pressure narrow-source MPH
and the existing solver sequence, but change the actual-area stage from a
single `0.101 N` point to a controlled `radial_load` ramp.

This is a diagnostic experiment only. It still uses weak inner guidance, weak
roller foundation, temporary active-roller spring stabilization, inactive
roller stabilization, and cage-inactive scope. It must not be marked
production-ready.

## Command

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --resume-actual-area-stage-from-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_20260717_114524_700877/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um.mph \
  --resume-actual-area-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp \
  --resume-actual-area-load-ramp "0.001 0.005 0.01 0.02 0.05 0.08 0.1 0.1005 0.101" \
  --cores 1
```

## Inputs

- Source MPH: solved nominal-pressure narrow-source
  `roller1_outer_retained_conformal_narrow_source_closure3um`.
- Retained conformal target: reused.
- Roller 1 source closure: reused `+3 um`.
- Roller 1 outer contact box tangential half-width: reused `0.9 mm`.
- Contact pair: kept `cp_roller_1_outer_raceway`; no source/destination swap
  was attempted.
- BoundaryLoad: kept `0.101 N`.
- BoundaryLoad pressure expression:
  `inner_bore_load_pressure = radial_load/(4.863178789249815e-3[m^2])`.
- Active rollers: kept `[12, 1, 2]`.
- Contact settings: penalty `5e-5*E_steel`, relaxation `0.12`,
  tolerance `3[um]`, `zeroInitGap=0`.
- Unique variable: enable a controlled `radial_load` sweep
  `0.001 0.005 0.01 0.02 0.05 0.08 0.1 0.1005 0.101`.

## Result

- Source MPH load: pass.
- Actual-area configured checkpoint save: pass.
- Solver reuse: kept `reuse_existing_solver=true`; no solver rebuild.
- Solve success: fail.
- Solve error:
  `Solve failed: java.lang.NullPointerException (exception stringification failed: JVMNotRunning: JVMNotRunning('Java Virtual Machine is not running'))`.
- Failed MPH save: fail, because the JVM was no longer running.
- Solved actual-area MPH: none.
- Result package: none.
- Native PNG: none.
- Displacement and max stress: unavailable because no solved actual-area field
  exists.
- Active roller load distribution: unavailable because no solved actual-area
  field exists.

## No-Solve Stage Diagnostic

Command:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --diagnose-stage-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_load_ramp_configured.mph \
  --diagnose-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/diagnostics_configured_mph \
  --cores 1
```

- Diagnostic success: true.
- Studies: `["std1"]`.
- Solvers in configured MPH: `["sol1"]`.
- Pair tags include `cp_roller_1_outer_raceway`.
- BoundaryLoad feature: `load_inner_bore`, active, type `BoundaryLoad`.
- BoundaryLoad selection: `sel_inner_bore_load_surface`, entities
  `[135, 136, 139, 140, 141, 142, 143, 144]`.
- BoundaryLoad input: `FperArea=["inner_bore_load_pressure", "0", "0"]`.
- Active raceway contacts: rollers `1`, `2`, and `12` inner/outer contacts
  remain active.
- Cage contacts: inactive.
- Diagnostic aids still active: weak inner guidance, weak roller foundations,
  temporary active-roller spring stabilization, inactive-roller stabilization.

## BoundaryLoad Probe

Command:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-load-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_load_ramp_configured.mph \
  --load-probe-selection sel_inner_bore_load_surface \
  --load-probe-pressure-expression inner_bore_load_pressure \
  --load-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/load_probe_configured_mph \
  --cores 1
```

- Probe success: true for expression integration.
- MPH solution context: `configured_checkpoint`.
- Area: `0.004863178789249815 m^2`.
- Configured parameter expression:
  `radial_load/(4.863178789249815e-3[m^2])`.
- Static configured estimate: `20.76830903755033 Pa *
  0.004863178789249815 m^2 = 0.101 N`.
- Static configured load-balance estimate: pass, ratio `1.0`.
- Pressure evaluated in the stale solution context: `44.65180347855952 Pa`.
- Integrated load evaluated in the stale solution context:
  `0.2171497035786822 N`.
- Solution-evaluation load balance: fail, ratio `2.149997065135467`.
- Public load-balance evidence gate: fail,
  `mph_context_not_valid_for_solved_load_balance`.

Interpretation: the configured MPH has a traceable actual-area BoundaryLoad
input, but the solve failed before producing a valid actual-area solution. The
solution-context integral is stale and cannot count as solved load-balance
evidence.

## Contact Probe

Command:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_load_ramp_configured.mph \
  --probe-contact-entity-transfer \
  --contact-entity-transfer-selection sel_roller_1_outer_contact \
  --contact-entity-transfer-roller 1 \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/contact_probe_configured_mph \
  --cores 1
```

- Probe success: true in configured/stale context.
- Candidate count: `972`.
- Success count: `144`.
- Nonzero count: `104`.
- `roller_1` pair-specific success count: `6`.
- `roller_1` pair-specific nonzero count: `2`.
- `roller_1` pair-specific nonzero ratio:
  `0.3333333333333333`.
- `roller_1` source/destination imbalance: `false`.
- `roller_1` zero pair-specific contact pressure: `false`.
- `roller_1` outer source entities: `2`.
- `roller_1` outer destination entities: `6`.
- Source-side `solid.Tn_cp_roller_1_outer_raceway`: selection error.
- Source-side `solid.gap_cp_roller_1_outer_raceway`: infinite result.
- Destination-side `solid.Tn_cp_roller_1_outer_raceway`:
  `528596858.61733407`.
- Destination-side `solid.gap_cp_roller_1_outer_raceway`: infinite result.

Interpretation: the configured/stale MPH retains the same destination-side
nonzero pair-specific outer contact signal seen in earlier diagnostics and does
not show a source/destination imbalance flag. Because the actual-area solve did
not complete, this cannot be counted as solved contact-transfer closure.

## Reaction Probe

Command:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-reaction-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_load_ramp_configured.mph \
  --reaction-probe-selection sel_outer_support_surface \
  --reaction-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/support_reaction_probe_configured_mph \
  --cores 1
```

- Probe success: true in configured/stale context.
- Reaction verified: false.
- Reaction candidate nonzero: true.
- Best support reaction candidate:
  `solid.sx*nx+solid.sxy*ny+solid.sxz*nz`.
- Best support reaction magnitude: `294.6119538579628 N`.
- Applied load context: `0.101 N`.
- Reaction/load ratio: `2916.9500381976513`.
- Relative residual to load: `2915.9500381976513`.
- Reaction/load balance: fail.

## Artifacts

- Summary JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/direct_3d_bearing_summary.json`
- Configured MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_load_ramp_configured.mph`
- Stage diagnostic JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/diagnostics_configured_mph/stage_mph_diagnostic.json`
- Stage diagnostic Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/diagnostics_configured_mph/stage_mph_diagnostic.md`
- BoundaryLoad probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/load_probe_configured_mph/load_probe_summary.json`
- BoundaryLoad probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/load_probe_configured_mph/load_probe_summary.md`
- Contact probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/contact_probe_configured_mph/contact_probe_summary.json`
- Contact probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/contact_probe_configured_mph/contact_probe_summary.md`
- Reaction probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/support_reaction_probe_configured_mph/reaction_probe_summary.json`
- Reaction probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_from_solved_nominal_load_ramp/support_reaction_probe_configured_mph/reaction_probe_summary.md`
- Solved MPH: none.
- PNG: none.

## Gate Decision

- Code closure: pass for reproducible CLI wiring and unit coverage.
- Solve closure: fail.
- Contact transfer closure: fail; only configured/stale contact evidence exists.
- Reaction/load balance closure: fail.
- Engineering physical closure: fail.

Conclusion: the controlled actual-area load ramp did not resolve the
NullPointer/JVM failure. This rules out a simple singlepoint load-step jump as
the only blocker, while preserving the earlier endpoint-audit conclusion that
source/destination swap is not justified. The next single-variable diagnostic
should target the actual-area pressure/contact initialization pathway before the
first actual-area load step, without changing contact endpoint topology.
