# Roller 1 Outer Retained Conformal Narrow Source Closure + Actual-Area Singlepoint Diagnostic

- Date: 2026-07-18
- Status: failed diagnostic experiment, not production-ready
- Stage mode: `load_side_group_boundary_load_single_solve_0p101_actual_area_singlepoint`
- Geometry mode: `roller1_outer_retained_conformal_narrow_source_closure3um`
- Unique variable: disabled the `radial_load` parametric sweep with `use_parametric_sweep=false` and solved directly at the final `0.101 N` target.

## Command

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_narrow_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101_actual_area_singlepoint \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_singlepoint \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_singlepoint \
  --cores 1
```

The run produced the template JSON and configured-stage MPH, then stayed in the solve/save path without producing `direct_3d_bearing_summary.json` or a result package. It was interrupted to avoid an indefinite task hang. During cleanup, failure-state save hit `jpype._core.JVMNotRunning`, so only the configured MPH is available for no-solve diagnostics.

## Inputs Held Constant

- BoundaryLoad target: `0.101[N]`
- BoundaryLoad pressure expression: `radial_load/(4.863178789249815e-3[m^2])`
- Active rollers: `[12, 1, 2]`
- Contact pair retained: `cp_roller_1_outer_raceway`
- Contact settings: penalty `5e-5*E_steel`, relaxation `0.12`, tolerance `3[um]`
- Roller 1 outer contact box tangential half-width: `0.9 mm`
- Roller 1 source closure: `+3 um`
- Cage contact: inactive
- Diagnostic aids still active: weak inner guidance, weak roller foundations, temporary active-roller spring stabilization, inactive-roller fixed stabilization

## Result

- Solve success: fail
- Solver status: no solved MPH, no result package, no native COMSOL PNG
- Summary status: manually recorded failure summary for evidence-matrix inclusion after interrupted run
- Saved MPH: configured-stage MPH only
- Displacement and max stress: unavailable; no trustworthy solved field exists
- Active roller distribution: unavailable; no per-roller stress probes were produced

## BoundaryLoad Probe

Command:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-load-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_singlepoint/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_singlepoint_configured.mph \
  --load-probe-selection sel_inner_bore_load_surface \
  --load-probe-pressure-expression inner_bore_load_pressure \
  --cores 1
```

- Probe path: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_singlepoint/load_probe/load_probe_summary.json`
- Probe success: false
- Area: unavailable
- Integrated load: unavailable
- Pressure: unavailable
- Load balance: fail, `missing_integrated_boundary_load`

Interpretation: the configured MPH records the intended BoundaryLoad pressure expression, but this no-solve probe did not verify a traceable integrated `0.101 N` load.

## Contact Probe

Command:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_singlepoint/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_singlepoint_configured.mph \
  --probe-contact-entity-transfer \
  --contact-entity-transfer-roller 1 \
  --contact-entity-transfer-selection sel_roller_1_outer_contact \
  --cores 1
```

- Contact probe path: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_singlepoint/contact_probe/contact_probe_summary.json`
- Contact probe success count: `0`
- Contact probe nonzero count: `0`
- Warning: `No contact-surface candidate expression evaluated successfully.`
- Pair-specific Tn/gap/source/destination transfer: not verified; no computed solution exists

## Reaction Probe

Command:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-reaction-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_singlepoint/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_singlepoint_configured.mph \
  --reaction-probe-selection sel_outer_support_surface \
  --cores 1
```

- Probe path: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_singlepoint/reaction_probe/reaction_probe_summary.json`
- Probe success: false
- Reaction verified: false
- Candidate classes: `evaluation_error=40`
- Error basis: the solution has not been computed
- External load versus reaction balance: fail; no solved `0.101 N` reaction closure exists

## Artifacts

- Summary: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_singlepoint/direct_3d_bearing_summary.json`
- Configured stage MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_singlepoint/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_singlepoint_configured.mph`
- Stage diagnostic: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_singlepoint/diagnostics/stage_mph_diagnostic.json`
- BoundaryLoad probe: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_singlepoint/load_probe/load_probe_summary.json`
- Contact probe: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_singlepoint/contact_probe/contact_probe_summary.json`
- Reaction probe: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_singlepoint/reaction_probe/reaction_probe_summary.json`
- PNG: none; no solved stage exported a native COMSOL PNG

## Gate Decision

- Code closure: pass for mode wiring and reproducible diagnostic artifact generation.
- Solve closure: fail.
- Contact transfer closure: fail.
- Reaction/load balance closure: fail.
- Engineering physical closure: fail.

Conclusion: removing the `radial_load` parametric sweep and solving directly at `0.101 N` did not produce a solved, probeable physical stage. The experiment remains diagnostic only, still uses weak guidance and temporary stabilization, and provides no BoundaryLoad integration, contact transfer, or reaction-balance closure.
