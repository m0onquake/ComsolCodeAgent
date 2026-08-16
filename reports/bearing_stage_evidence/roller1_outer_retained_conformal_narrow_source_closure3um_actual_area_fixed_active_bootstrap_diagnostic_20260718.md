# Roller 1 Outer Retained Conformal Narrow Source Closure + Actual-Area Fixed-Active Bootstrap Diagnostic

- Date: 2026-07-18
- Status: failed diagnostic experiment, not production-ready
- Stage mode: `load_side_group_boundary_load_single_solve_0p101_actual_area_fixed_active_bootstrap`
- Geometry mode: `roller1_outer_retained_conformal_narrow_source_closure3um`
- Unique variable: changed only `active_roller_stabilization_mode` from `spring` to `fixed` relative to `load_side_group_boundary_load_single_solve_0p101_actual_area_fine_bootstrap`.

## Command

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_narrow_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101_actual_area_fixed_active_bootstrap \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fixed_active_bootstrap \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fixed_active_bootstrap \
  --cores 1
```

The run was allowed to continue for a long solver window after exceeding the previous quick-failure behavior. It produced no summary/result package during that window, then was terminated with SIGTERM to avoid an indefinite task hang. The script wrote a failed summary during cleanup.

## Inputs Held Constant

- BoundaryLoad target: `0.101[N]`
- BoundaryLoad pressure expression: `radial_load/(4.863178789249815e-3[m^2])`
- Radial-load bootstrap sequence: `1e-5 5e-5 1e-4 5e-4 0.001 0.002 0.005 0.01 0.02 0.05 0.08 0.1 0.1005 0.101`
- Active rollers: `[12, 1, 2]`
- Contact pair retained: `cp_roller_1_outer_raceway`
- Contact settings: penalty `5e-5*E_steel`, relaxation `0.12`, tolerance `3[um]`
- Roller 1 outer contact box tangential half-width: `0.9 mm`
- Roller 1 source closure: `+3 um`
- Cage contact: inactive
- Diagnostic aids still active: weak inner guidance, weak roller foundations, temporary active-roller fixed stabilization, inactive-roller fixed stabilization

## Result

- Solve success: fail
- Solver status: long-running fixed-active solve terminated after no summary/result package was produced.
- Summary error: `Solve failed: Fatal error occurred`
- Native COMSOL PNG: none
- Saved MPH: configured-stage MPH only; no failed solved-state MPH was produced.
- Displacement and max stress: unavailable; no trustworthy solved field exists.

## BoundaryLoad Probe

- Probe path: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fixed_active_bootstrap/load_probe_configured_mph/load_probe_summary.json`
- Probe success: false
- Area: unavailable
- Integrated load: unavailable
- Pressure: unavailable
- Load balance: fail, `missing_integrated_boundary_load`

Interpretation: the configured MPH records the BoundaryLoad setup, but without a computed solution the load probe cannot produce an integrated load or a load-balance result.

## Contact Probe

- Contact probe path: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fixed_active_bootstrap/contact_probe_configured_mph/contact_probe_summary.json`
- Source-transfer probe path: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fixed_active_bootstrap/source_entity_transfer_probe_configured_mph/contact_probe_summary.json`
- Contact probe success count: `0`
- Contact probe nonzero count: `0`
- Warning: `No contact-surface candidate expression evaluated successfully.`
- Pair-specific Tn/gap/source/destination transfer: not verified; no computed solution exists.

## Reaction Probe

- Probe path: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fixed_active_bootstrap/reaction_probe_configured_mph/reaction_probe_summary.json`
- Probe success: false
- Reaction verified: false
- Candidate classes: `evaluation_error=40`
- Error: `No probed COMSOL reaction-force expression evaluated to a nonzero reaction; do not claim equivalent load transfer.`
- External load versus reaction balance: fail; no solved `0.101 N` reaction closure exists.

## Artifacts

- Summary: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fixed_active_bootstrap/direct_3d_bearing_summary.json`
- Configured stage MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fixed_active_bootstrap/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_fixed_active_bootstrap_configured.mph`
- Stage diagnostic: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fixed_active_bootstrap/diagnostics_configured_mph/stage_mph_diagnostic.json`
- BoundaryLoad probe: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fixed_active_bootstrap/load_probe_configured_mph/load_probe_summary.json`
- Contact probe: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fixed_active_bootstrap/contact_probe_configured_mph/contact_probe_summary.json`
- Source entity transfer probe: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fixed_active_bootstrap/source_entity_transfer_probe_configured_mph/contact_probe_summary.json`
- Reaction probe: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fixed_active_bootstrap/reaction_probe_configured_mph/reaction_probe_summary.json`
- PNG: none; no solved stage exported a native COMSOL PNG.

## Gate Decision

- Code closure: pass for mode wiring and reproducible diagnostic artifact generation.
- Solve closure: fail.
- Contact transfer closure: fail.
- Reaction/load balance closure: fail.
- Engineering physical closure: fail.

Conclusion: switching active rollers from temporary spring stabilization to temporary fixed stabilization avoids the previous fast failure pattern but does not produce a solved, probeable physics stage within the run window. This remains a diagnostic dead end for physical closure because it strengthens an explicitly non-production constraint and still provides no solved BoundaryLoad/contact/reaction evidence.
