# Roller1 Outer Retained Conformal Narrow Source Closure3um Actual-Area Resume ZeroInitGap1 Diagnostic

Date: 2026-07-19

## Purpose

Test one variable after the actual-area resume, fresh-solver resume, and
load-ramp diagnostics failed or did not reach a verified load/reaction state:
load the solved nominal-pressure narrow-source MPH, keep the same actual-area
`0.101 N` BoundaryLoad checkpoint, and explicitly set `zeroInitGap=1` on the
active rollers' inner/outer raceway Contact features before solving.

This is a diagnostic experiment only. It still uses weak inner guidance, weak
roller foundation, temporary active-roller spring stabilization, inactive
roller stabilization, and cage-inactive scope. It must not be marked
production-ready.

## Code Change

- Added `--resume-actual-area-contact-zero-init-gap`.
- Passed explicit `contact_feature_property_overrides` through the
  resume-from-solved-nominal actual-area runner.
- Passed the known stage BoundaryLoad context into saved-MPH BoundaryLoad and
  reaction probes so solved probe gates can compare against the intended
  `0.101 N` input before the final summary exists on disk.
- Preserved compact summary fields for `boundary_load_context`, `load_balance`,
  `solution_evaluation_load_balance`, `configured_parameter_load_estimate`,
  `reaction_load_balance`, and `reaction_verified`.

## Command

Canonical run:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --resume-actual-area-stage-from-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_20260717_114524_700877/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um.mph \
  --resume-actual-area-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context \
  --resume-actual-area-contact-zero-init-gap 1 \
  --cores 1
```

No-solve configured-MPH diagnostic:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --diagnose-stage-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_zero_init_gap1_configured.mph \
  --diagnose-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context/diagnostics_configured_mph \
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
  tolerance `3[um]`.
- Unique variable: active raceway Contact features for rollers `12`, `1`, and
  `2` were explicitly overridden to `zeroInitGap=1`.

## Solve Result

- Solve success: true.
- Saved solved MPH: true.
- Native PNG: true, passed nonblank/nonmonochrome quality gate.
- Maximum von Mises stress: `6526523.284302745 Pa`.
- Maximum displacement: `0.00006924300681257934 m`.
- Active roller stress distribution: pass for nonzero load-side stress on all
  three active rollers.

Active roller max von Mises values:

| Roller | Max von Mises (Pa) |
|---|---:|
| `roller_1` | `173040.9819956236` |
| `roller_2` | `5305.822431272637` |
| `roller_12` | `6234.294809551681` |

Active roller min/max ratio: `0.030662230242121648`.

## BoundaryLoad Evidence

Saved-MPH BoundaryLoad probe:

- MPH solution context: `solved_result_package`.
- BoundaryLoad context: stage
  `single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_zero_init_gap1`,
  applied load `0.101 N`.
- Selection: `sel_inner_bore_load_surface`.
- Area: `0.004863178789249815 m^2`.
- Pressure: `20.768309037550328 Pa`.
- Integrated load: `0.10100000000000037 N`.
- Load balance: pass.
- Integrated/load ratio: `1.0000000000000036`.
- Static configured estimate: pass,
  `20.76830903755033 Pa * 0.004863178789249815 m^2 = 0.101 N`.

Interpretation: this run provides a solved-MPH BoundaryLoad input closure for
the diagnostic actual-area stage. It does not provide reaction/load closure.

## Contact Evidence

Saved-MPH contact probe:

- Probe success: true.
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
- `contact_roller_1_outer.pairs`: `cp_roller_1_outer_raceway`.
- `contact_roller_1_outer.zeroInitGap`: `1`.
- Source/destination field probe, outer pair:
  source evaluable true, destination evaluable true, source nonzero true,
  destination nonzero true.
- Outer source max abs field value: `162374.08719674952`.
- Outer destination max abs field value: `17626.92999277592`.
- Destination-side pair-specific
  `solid.Tn_cp_roller_1_outer_raceway`: `17626.92999277592`.
- Source-side pair-specific
  `solid.Tn_cp_roller_1_outer_raceway`: selection error.
- Pair-specific gap values still evaluate as infinite on the probed source and
  destination labels.

Interpretation: `zeroInitGap=1` converts the previous actual-area solve failure
into a solved diagnostic state and preserves nonzero roller-1 outer destination
pair-specific transfer plus nonzero source/destination field probes. It still
does not prove complete pair-specific contact closure because source-side
pair-specific `Tn` remains unevaluable and gap evidence is not finite.

## Reaction Evidence

Saved-MPH reaction probe:

- Probe success: true.
- Reaction candidate nonzero: true.
- Reaction verified: false.
- Best expression: `solid.sx*nx+solid.sxy*ny+solid.sxz*nz`.
- Best method: `java_intsurface`.
- Best support reaction magnitude: `296.412030782202 N`.
- Applied load: `0.101 N`.
- Reaction/load ratio: `2934.772582002`.
- Relative residual to load: `2933.772582002`.
- Reaction/load balance: fail.

Interpretation: the solved stage is not in external load/support reaction
balance by the current project gate. This prevents reaction verification and
production readiness.

## Artifacts

- Summary JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context/direct_3d_bearing_summary.json`
- Configured MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_zero_init_gap1_configured.mph`
- Solved MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context/result_packages/actual_area_resume_from_solved_nominal.mph`
- Native PNG:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context/stage_plots/single_solve_3_roller_boundary_load_0p101n_actual_area_resume_from_solved_nominal_zero_init_gap1_native_volume.png`
- Stage diagnostic JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context/diagnostics_configured_mph/stage_mph_diagnostic.json`
- Stage diagnostic Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context/diagnostics_configured_mph/stage_mph_diagnostic.md`
- BoundaryLoad probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context/load_probe_solved_mph/load_probe_summary.json`
- BoundaryLoad probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context/load_probe_solved_mph/load_probe_summary.md`
- Contact probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context/contact_probe_solved_mph/contact_probe_summary.json`
- Contact probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context/contact_probe_solved_mph/contact_probe_summary.md`
- Reaction probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context/support_reaction_probe_solved_mph/reaction_probe_summary.json`
- Reaction probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_resume_zero_init_gap1_balanced_context/support_reaction_probe_solved_mph/reaction_probe_summary.md`

## Evidence Matrix Status

After refresh:

- `summary_count=162`.
- `row_count=315`.
- `saved_boundary_load_probe_report_count=14`.
- `saved_boundary_load_probe_balanced_count=2`.
- `saved_reaction_probe_report_count=10`.
- `saved_reaction_probe_verified_count=0`.
- `reaction_verified_stage_count=0`.
- `production_ready_count=0`.

## Gate Decision

- Code closure: pass for reproducible zeroInitGap diagnostic CLI and saved-probe
  context propagation.
- Solve closure: pass for this diagnostic stage.
- BoundaryLoad/input closure: pass for this diagnostic stage.
- Contact transfer closure: partial diagnostic pass, not complete physical
  closure.
- Reaction/load balance closure: fail.
- Engineering physical closure: fail.

Conclusion: explicit `zeroInitGap=1` is the first actual-area resume diagnostic
in this series to produce a solved MPH, native PNG, solved BoundaryLoad balance,
and saved-MPH contact/reaction probe package. It does not achieve physical
closure because support reaction is about `2934.77x` the applied load and the
run still depends on diagnostic guidance/stabilization.
