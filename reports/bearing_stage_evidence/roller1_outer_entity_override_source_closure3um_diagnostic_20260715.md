# Roller 1 outer entity override + 3 um source-closure diagnostic - 2026-07-15

## Scope

This report records the next full-fixture diagnostic after
`roller1_outer_raceway_partition_source_closure3um`. The successful source-closure
fixture was kept unchanged. Only the staged contact mode was changed so that the
outer destination selection for `roller_1` was explicitly rebound to entities
`[8, 9]`.

```text
--verified-fixture-local-contact-patch-mode roller1_outer_raceway_partition_source_closure3um
--contact-stage-mode load_side_group_boundary_load_single_solve_0p101_roller1_outer_entity_override
```

The run kept the `0.101[N]` load-side 3-roller BoundaryLoad stage, active rollers
`12, 1, 2`, contact settings, weak guidance, temporary active-roller
stabilization, and cage-inactive scope. This is diagnostic evidence only, not a
production/design-grade run.

## Code change

- Reused the existing `entity_raceway_override` setup pipeline.
- Added the public stage mode:
  `load_side_group_boundary_load_single_solve_0p101_roller1_outer_entity_override`.
- Limited `raceway_selection_entity_overrides` to:

  ```python
  {"sel_outer_raceway_1_contact": [8, 9]}
  ```

- Kept inner selections and `roller_2`/`roller_12` selections unchanged by this
  mode.
- Preserved the `cp_roller_1_outer_raceway` destination rebind through
  `sel_outer_raceway_1_contact`.
- Added regression coverage for the stage metadata, setup markers, and override
  scope.

## Static verification

```bash
python3 -m pytest tests/test_core.py -q
python3 -m compileall -q comsol_agent tests scripts
```

Results:

- `180 passed, 1 skipped`
- `compileall`: passed

## COMSOL commands

Full fixture run:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_raceway_partition_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101_roller1_outer_entity_override \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_entity_override_source_closure3um \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_entity_override_source_closure3um \
  --cores 1
```

Saved-MPH no-resolve contact probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_entity_override_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_entity_override_source_closure3um_20260715_103234_884131/bearing3d_load_side_boundaryload_0p101_roller1_outer_entity_override_source_closure3um.mph \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_entity_override_source_closure3um/contact_probe_solved_mph \
  --cores 1
```

Evidence matrix refresh:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --stage-evidence-matrix \
  --stage-evidence-root runtime_smoke \
  --stage-evidence-output-dir reports/bearing_stage_evidence
```

## Artifacts

- Full run summary:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_entity_override_source_closure3um/direct_3d_bearing_summary.json`
- Configured MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_entity_override_source_closure3um/stage_models/single_solve_3_roller_boundary_load_0p101n_roller1_outer_entity_override_configured.mph`
- Solved MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_entity_override_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_entity_override_source_closure3um_20260715_103234_884131/bearing3d_load_side_boundaryload_0p101_roller1_outer_entity_override_source_closure3um.mph`
- Native PNG:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_entity_override_source_closure3um/stage_plots/single_solve_3_roller_boundary_load_0p101n_roller1_outer_entity_override_native_volume.png`
- Contact probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_entity_override_source_closure3um/contact_probe_solved_mph/contact_probe_summary.json`
- Contact probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_entity_override_source_closure3um/contact_probe_solved_mph/contact_probe_summary.md`
- Refreshed matrix:
  `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.md`

## Full-stage result

- Stage solve success: `true`
- Stage:
  `single_solve_3_roller_boundary_load_0p101n_roller1_outer_entity_override`
- Boundary load: `0.101[N]`
- Global max von Mises: `9082466.92396657 Pa`
- Native PNG and stress plausibility: passed
- Active roller nonzero ratio: `2/3 = 0.6666666666666666`
- Zero-stress active roller: `roller_1`

Per-active-roller von Mises probe:

| Roller | Max von Mises |
|---|---:|
| `roller_1` | `0.0` |
| `roller_2` | `264313.9506905501` |
| `roller_12` | `297041.150565126` |

## Selection and pair-enforcement result

The configured and solved model both show the intended explicit destination
selection:

| Item | Result |
|---|---:|
| `sel_roller_1_outer_contact` source entities | `2` |
| `sel_outer_raceway_1_contact` destination entities | `2` |
| Destination override entities | `8, 9` |
| Pair | `cp_roller_1_outer_raceway` |

The setup markers confirm:

```text
RACEWAY_SELECTION_ENTITY_OVERRIDE|...|selection=sel_outer_raceway_1_contact|entities=8,9
RACEWAY_SELECTION_ENTITY_REBIND|...|pair=cp_roller_1_outer_raceway|destination=sel_outer_raceway_1_contact
```

## Saved-MPH contact probe result

- Probe success: `true`
- Contact probe success count: `144`
- Contact probe nonzero count: `90`
- `roller_1` pair-specific success count: `6`
- `roller_1` pair-specific nonzero count: `0`
- `roller_1` pair-specific nonzero ratio: `0.0`
- `roller_1` outer destination pair-specific
  `solid.Tn_cp_roller_1_outer_raceway`: `0.0`
- `roller_1` outer source field response: zero
- `roller_1` outer destination field response: nonzero, max abs
  `4101210.6718584914`
- `roller_1` source/destination imbalance: `true`

The explicit destination override reduced the destination entity count from `9`
in the preceding source-closure diagnostic to `2`, but it did not create
pair-specific transfer or source-side response.

## Evidence matrix status

After refresh:

- `summary_count=143`
- `row_count=295`
- `saved_contact_probe_report_count=43`
- `saved_contact_probe_source_destination_imbalance_count=19`
- `production_ready_count=0`
- `reaction_verified_stage_count=0`

No production-ready or reaction-verified claim was introduced.

## Interpretation

This experiment validates the selection-control mechanism, not the physical
closure. The destination selection is now narrow and explicitly rebound to the
intended contact pair, but the full-fixture `roller_1` zero-carry symptom remains:

- `roller_1` active stress is still zero;
- active rollers `12/1/2` are not all nonzero;
- outer pair-specific `solid.Tn_cp_roller_1_outer_raceway` remains zero;
- source-side field response remains zero;
- source/destination imbalance remains true.

Therefore this mode is not an improvement over
`roller1_outer_raceway_partition_source_closure3um` for physical transfer. The
previous source-closure mode remains the strongest local-topology progress point.

## Recommended next experiment

Keep the successful `+3[um]` source closure and the original destination
partition geometry. The next minimal experiment should change the contact
pair's construction-time source/destination topology itself, such as a retained
conformal or imprinted `roller_1` outer patch, rather than only rebinding the
post-geometry destination selection. Keep the same 3-roller `0.101[N]` stage and
the same evidence gates.
