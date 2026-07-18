# Roller 1 Outer Retained Conformal Narrow Source Closure + Actual-Area Fine Bootstrap Diagnostic

- Date: 2026-07-18
- Status: failed diagnostic experiment, not production-ready
- Stage mode: `load_side_group_boundary_load_single_solve_0p101_actual_area_fine_bootstrap`
- Geometry mode: `roller1_outer_retained_conformal_narrow_source_closure3um`
- Unique variable: changed only the `radial_load` parametric bootstrap list from `0.001 0.005 0.01 0.05 0.1 0.1005 0.101` to `1e-5 5e-5 1e-4 5e-4 0.001 0.002 0.005 0.01 0.02 0.05 0.08 0.1 0.1005 0.101`.

## Command

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_narrow_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101_actual_area_fine_bootstrap \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fine_bootstrap \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fine_bootstrap \
  --cores 1
```

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
- Solver error: stationary solver could not find the initial parameter solution; solid mechanics did not converge because the relative step became too small.
- Native COMSOL PNG: none
- Saved MPH: failed-state MPH only
- Displacement and max stress: unavailable; no trustworthy solved field exists.

## BoundaryLoad Probe

- Probe path: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fine_bootstrap/load_probe_failed_mph/load_probe_summary.json`
- Area: `0.004863178789249815 m^2`
- Integrated load: `1.0000000000000014e-05 N`
- Applied target load: `0.101 N`
- Integrated/target ratio: `9.900990099009915e-05`
- Load balance: fail

Interpretation: the actual-area pressure expression is traceable, but the failed MPH is stopped at the new first bootstrap parameter value, `1e-5 N`, not at the final `0.101 N`.

## Contact Probe

- Probe path: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fine_bootstrap/contact_probe_failed_mph/contact_probe_summary.json`
- Contact probe success count: `144`
- Contact probe nonzero count: `108`
- Pair enforcement diagnostic: success, but failed-state only
- Nonzero reference rollers: `roller_1`, `roller_2`, `roller_12`
- Source/destination imbalance rollers: none reported by the pair-enforcement summary

Pair-specific failed-state details:

| Roller | Label | Tn class | Tn value | Gap class |
|---|---|---|---:|---|
| roller_1 | inner source | selection_error |  | infinite_result |
| roller_1 | inner raceway | nonzero_success | 1853293451.7876587 | infinite_result |
| roller_1 | outer source | selection_error |  | infinite_result |
| roller_1 | outer raceway | nonzero_success | 55516966748.368164 | infinite_result |
| roller_2 | inner raceway | nonzero_success | 802903308.1192788 | infinite_result |
| roller_2 | outer raceway | nonzero_success | 1.296938656705625e-12 | infinite_result |
| roller_12 | inner raceway | nonzero_success | 0.00045738686298207664 | infinite_result |
| roller_12 | outer raceway | nonzero_success | 384001323.71414506 | infinite_result |

These values are not physical closure evidence because the model did not converge to a solved final stage and the source-side pair-specific Tn probes remain unevaluable.

## Reaction Probe

- Probe path: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fine_bootstrap/reaction_probe_failed_mph/reaction_probe_summary.json`
- Reaction verified: false
- Candidate classes: `unknown_operator=23`, `zero_result=6`, `selection_error=8`, `nonzero_success=3`
- External load versus reaction balance: fail; no solved `0.101 N` reaction closure exists.

## Artifacts

- Summary: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fine_bootstrap/direct_3d_bearing_summary.json`
- Failed MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fine_bootstrap/failed_3d_contact_model.mph`
- Configured stage MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fine_bootstrap/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_fine_bootstrap_configured.mph`
- Stage diagnostic: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fine_bootstrap/diagnostics_failed_mph/stage_mph_diagnostic.json`
- BoundaryLoad probe: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fine_bootstrap/load_probe_failed_mph/load_probe_summary.json`
- Contact probe: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fine_bootstrap/contact_probe_failed_mph/contact_probe_summary.json`
- Source entity transfer probe: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fine_bootstrap/source_entity_transfer_probe_failed_mph/contact_probe_summary.json`
- Reaction probe: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_fine_bootstrap/reaction_probe_failed_mph/reaction_probe_summary.json`
- PNG: none; no solved stage exported a native COMSOL PNG.

## Gate Decision

- Code closure: pass for mode wiring and reproducible diagnostic artifact generation.
- Solve closure: fail.
- Contact transfer closure: fail; failed-state destination Tn candidates are not saved-solution transfer evidence.
- Reaction/load balance closure: fail.
- Engineering physical closure: fail.

Next action: keep the actual-area BoundaryLoad normalization, but do not continue shrinking the first load step alone. The failure now occurs at `1e-5 N`, so the next single-variable diagnostic should alter the contact initialization/constraint pathway before the first load step while preserving the retained conformal narrow geometry and 0.101 N target.
