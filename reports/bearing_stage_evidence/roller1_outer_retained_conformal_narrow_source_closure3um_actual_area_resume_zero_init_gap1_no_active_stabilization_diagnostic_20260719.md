# Roller1 Outer Retained Conformal Narrow Source Closure3um Actual-Area Resume ZeroInitGap1 No Active Stabilization Diagnostic

Date: 2026-07-19

## Purpose

Test whether the previous `zeroInitGap=1` actual-area resume result depends on
the temporary active-roller spring stabilization. This is a single-variable
diagnostic on top of the solved `zeroInitGap=1` actual-area resume: disable the
temporary active-roller stabilization only, while keeping the same source MPH,
BoundaryLoad, active rollers, contact pair, contact settings, weak guidance,
weak roller foundation, and cage-inactive scope.

This experiment is diagnostic only. It cannot be production-ready because weak
inner guidance, weak roller foundation, inactive-roller stabilization, temporary
cage stabilization, and cage-inactive scope remain; additionally, the solve did
not complete.

## Code Change

- Added `--resume-actual-area-disable-active-stabilization`.
- Added `disable_active_roller_stabilization` to
  `run_actual_area_resume_from_solved_nominal_mph`.
- When enabled, the resumed stage records
  `active_roller_stabilization_active=false` and
  `temporary_active_roller_stabilization_active=false` while preserving the
  rest of the actual-area resume setup.
- Added regression coverage that this mode changes only the active-roller
  stabilization state and does not rebuild solver sequences.

## Command

Canonical run:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --resume-actual-area-stage-from-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_20260717_114524_700877/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um.mph \
  --resume-actual-area-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization \
  --resume-actual-area-contact-zero-init-gap 1 \
  --resume-actual-area-disable-active-stabilization \
  --cores 1
```

Configured-MPH no-solve diagnostic:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --diagnose-stage-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_zero_init_gap1_no_active_stabilization_configured.mph \
  --diagnose-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/diagnostics_configured_mph \
  --cores 1
```

Configured BoundaryLoad probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-load-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_zero_init_gap1_no_active_stabilization_configured.mph \
  --load-probe-selection sel_inner_bore_load_surface \
  --load-probe-pressure-expression inner_bore_load_pressure \
  --load-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/load_probe_configured_mph \
  --cores 1
```

Configured support reaction probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-reaction-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_zero_init_gap1_no_active_stabilization_configured.mph \
  --reaction-probe-selection sel_outer_support_surface \
  --reaction-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/support_reaction_probe_configured_mph \
  --cores 1
```

Configured contact probe attempt:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_zero_init_gap1_no_active_stabilization_configured.mph \
  --probe-contact-entity-transfer \
  --contact-entity-transfer-selection sel_roller_1_outer_contact \
  --contact-entity-transfer-roller 1 \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/contact_probe_configured_mph \
  --cores 1
```

Evidence matrix refresh:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --stage-evidence-matrix \
  --stage-evidence-root runtime_smoke \
  --stage-evidence-output-dir reports/bearing_stage_evidence
```

## Inputs

- Source MPH: solved nominal-pressure
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
  tolerance `3[um]`.
- Contact feature override: kept `zeroInitGap=1` for rollers `12`, `1`, and
  `2` inner/outer raceway contact features.
- Unique variable: disabled temporary active-roller stabilization only.

## Solve Result

- Solve success: false.
- Solve error: `Solve failed: java.lang.NullPointerException`.
- Configured MPH saved: true.
- Failed-model save: false, `Java Virtual Machine is not running`.
- Solved MPH: none.
- Native PNG: none.
- Maximum von Mises stress: unavailable.
- Maximum displacement: unavailable.
- Active roller stress distribution: unavailable.

Interpretation: full removal of the active-roller spring is too large a step
from the previous `zeroInitGap=1` diagnostic state. The model loses solve
closure before contact/reaction gates can be evaluated on a solved MPH.

## BoundaryLoad Evidence

Configured-MPH BoundaryLoad probe:

- MPH solution context: `configured_checkpoint`.
- `load_balance_evidence_allowed`: false.
- BoundaryLoad feature: `load_inner_bore`, type `BoundaryLoad`, active true.
- Selection: `sel_inner_bore_load_surface`, 8 entities.
- Area: `0.004863178789249815 m^2`.
- Configured pressure estimate: `20.76830903755033 Pa`.
- Configured integrated load estimate: `0.101 N`.
- Configured estimate balance: pass.
- Stale solution pressure evaluation: `44.65180347855952 Pa`.
- Stale solution integrated load: `0.2171497035786822 N`.
- Stale solution integrated/load ratio: `2.149997065135467`.
- Public load-balance gate: fail because configured checkpoints are not valid
  solved load-balance evidence.

Interpretation: the input configuration is traceable in the configured MPH,
but this is not solved BoundaryLoad closure.

## Contact Evidence

- Solved contact probe: not available because the solve failed.
- Configured contact probe: attempted, but COMSOL failed during startup with
  Equinox storage/security initialization errors, including
  `Error initializing storage for Equinox container` and
  `Must have AllPermission granted to install an extension bundle:
  com.comsol.securityutil_1.0.0`.
- Contact probe JSON/Markdown: not produced for this attempt.
- Pair-specific `Tn`, `gap`, source, and destination results: unavailable for
  this no-active-stabilization stage.

Interpretation: this stage provides no solved pair-specific contact-transfer
evidence.

## Reaction Evidence

Configured-MPH support reaction probe:

- Probe success: true.
- Reaction candidate nonzero: true.
- Reaction verified: false.
- Best expression: `solid.sx*nx+solid.sxy*ny+solid.sxz*nz`.
- Best method: `java_intsurface`.
- Best support reaction magnitude: `294.6119538579628 N`.
- Applied load from context: `0.101 N`.
- Reaction/load ratio: `2916.9500381976513`.
- Relative residual to load: `2915.9500381976513`.
- Reaction/load balance: fail.

Interpretation: because the MPH is a configured checkpoint with no solved
result for this stage, the reaction values are stale/configured diagnostics and
do not verify physical reaction closure.

## Artifacts

- Summary JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/direct_3d_bearing_summary.json`
- Configured MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_zero_init_gap1_no_active_stabilization_configured.mph`
- Stage diagnostic JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/diagnostics_configured_mph/stage_mph_diagnostic.json`
- Stage diagnostic Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/diagnostics_configured_mph/stage_mph_diagnostic.md`
- Configured BoundaryLoad probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/load_probe_configured_mph/load_probe_summary.json`
- Configured BoundaryLoad probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/load_probe_configured_mph/load_probe_summary.md`
- Configured reaction probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/support_reaction_probe_configured_mph/reaction_probe_summary.json`
- Configured reaction probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_no_active_stabilization/support_reaction_probe_configured_mph/reaction_probe_summary.md`

## Gate Decision

- Code closure: pass for reproducible no-active-stabilization diagnostic mode.
- Solve closure: fail.
- BoundaryLoad/input closure: configured traceability pass, solved load-balance
  fail/not allowed.
- Contact transfer closure: fail, no solved contact probe evidence.
- Reaction/load balance closure: fail.
- Engineering physical closure: fail.
- Production ready: false.

## Next Step

Do not remove the active-roller spring in one jump. The next single-variable
path should use stiffness continuation on the `zeroInitGap=1` actual-area
resume, for example reducing `active_roller_stabilization_k` from `1e10` to
`1e9`, then lower values only after solved BoundaryLoad/contact/reaction probes
are preserved.
