# Roller 1 Outer Retained Conformal Source-Scope Saved-MPH Probe

- Date: 2026-07-19
- Status: diagnostic evidence only, not production-ready
- Baseline solved stage: `roller1_outer_retained_conformal_source_closure3um`
- Purpose: inspect whether the remaining `roller_1 outer` transfer blocker is physical zero transfer or source-side pair-variable scope/evaluation.
- Unique variable: no physics variable changed; this is a saved-MPH no-resolve probe using the current contact-probe implementation with endpoint-specific entity transfer.

## Source Endpoint Probe Command

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_source_closure3um_20260716_171750_712903/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_source_closure3um.mph \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/source_scope_probe_solved_mph_20260719 \
  --probe-contact-entity-transfer \
  --contact-entity-transfer-roller 1 \
  --contact-entity-transfer-selection sel_roller_1_outer_contact \
  --cores 1
```

## Destination Endpoint Probe Command

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_source_closure3um_20260716_171750_712903/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_source_closure3um.mph \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/destination_scope_probe_solved_mph_20260719 \
  --probe-contact-entity-transfer \
  --contact-entity-transfer-roller 1 \
  --contact-entity-transfer-selection sel_outer_raceway_1_contact \
  --cores 1
```

## Inputs Held Constant

- Solved MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_source_closure3um_20260716_171750_712903/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_source_closure3um.mph`
- BoundaryLoad target in the solved stage: `0.101[N]`
- Active rollers in the solved stage: `[12, 1, 2]`
- Contact pair retained: `cp_roller_1_outer_raceway`
- Geometry: retained conformal target with `+3 um` roller-1 source closure
- Diagnostic aids in the solved stage: weak inner guidance, weak roller foundations, temporary active-roller spring stabilization, cage inactive

## Probe Result

- Solve success: not rerun; existing baseline solved MPH was loaded.
- Contact probe success count: `144`
- Contact probe nonzero count: `104`
- Pair-transfer summary for `roller_1 outer`:
  - Source `abs(Tn)` integral: `null`
  - Destination `abs(Tn)` integral: `15074.102593474117`
  - Source evaluable: `false`
  - Destination evaluable: `true`
  - Source nonzero: `false`
  - Destination nonzero: `true`
  - Source zero / destination nonzero: `false`
  - Source unevaluable / destination nonzero: `true`

## Entity-Level Source Endpoint

- Selection: `sel_roller_1_outer_contact`
- Entity count: `2`
- Entities: `197`, `198`
- Pair-specific `solid.Tn_cp_roller_1_outer_raceway`: not evaluable on both source entities.
- Tried endpoint suffix/prefix variants such as `solid.Tn_cp_roller_1_outer_raceway_src`, `solid.Tn_src_cp_roller_1_outer_raceway`, `solid.Tn_cp_roller_1_outer_raceway_dst`, and `solid.Tn_dst_cp_roller_1_outer_raceway`: not evaluable.
- Generic source field response is nonzero:
  - Entity `197`: `solid.p=882184483.6531677`, `solid.mises=970656711.8011267`
  - Entity `198`: `solid.p=641406097.178451`, `solid.mises=1036831515.1385376`

Interpretation: the source-side contact surface is present and stressed, but the pair-specific `Tn` variable is not evaluable on the source-side boundary entities in this saved MPH.

## Entity-Level Destination Endpoint

- Selection: `sel_outer_raceway_1_contact`
- Entity count: `6`
- Entities with nonzero pair-specific `Tn` max: `13`, `14`, `17`, `18`, `19`, `20`
- Entities with nonzero pair-specific `Tn` integral: `13`, `14`, `18`, `19`
- Representative pair-specific integrals:
  - Entity `13`: `150.42210134740992`
  - Entity `14`: `127.85725263029393`
  - Entity `18`: `7406.245792181062`
  - Entity `19`: `7389.577447315343`
- Endpoint suffix/prefix variants for `_src` and `_dst` were not evaluable on destination entities either; the valid destination expression remains `solid.Tn_cp_roller_1_outer_raceway`.

## Load, Reaction, Displacement, And Stress Context

- BoundaryLoad traceability remains failed for this baseline: existing saved-MPH load probe integrated `0.0021499970651354676 N`, not `0.101 N`.
- Reaction/load balance remains failed: existing reaction probes report reactions hundreds to thousands of times larger than the external load.
- Baseline maximum displacement remains pathological: `1.1883195441906897 m`.
- Baseline global maximum von Mises remains pathological: `1249460146.5506132 Pa`.
- Active roller nonzero ratio in the baseline solved stage is `1.0`, but the distribution is highly unbalanced.

## Artifacts

- Source endpoint JSON: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/source_scope_probe_solved_mph_20260719/contact_probe_summary.json`
- Source endpoint Markdown: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/source_scope_probe_solved_mph_20260719/contact_probe_summary.md`
- Destination endpoint JSON: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/destination_scope_probe_solved_mph_20260719/contact_probe_summary.json`
- Destination endpoint Markdown: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/destination_scope_probe_solved_mph_20260719/contact_probe_summary.md`
- Refreshed evidence matrix: `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.md`
- Solved MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_source_closure3um_20260716_171750_712903/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_source_closure3um.mph`
- PNG: existing baseline native PNG only; no new PNG was produced because this was a no-resolve probe.

## Gate Decision

- Code closure: pass for current saved-MPH probe execution.
- Solve closure: unchanged; no new solve was run.
- Contact transfer closure: fail, because source-side pair-specific `Tn` is still not independently evaluable.
- Reaction/load balance closure: fail.
- Engineering physical closure: fail.

Conclusion: the retained conformal source-closure baseline has nonzero destination-side pair-specific transfer and nonzero generic source stress/pressure, but it still lacks source-side pair-specific `Tn` evidence and remains numerically pathological. This supports the next single-variable physical experiment targeting contact endpoint variable scope or contact formulation, not another destination entity swap.
