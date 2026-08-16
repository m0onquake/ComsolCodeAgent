# Roller 1 narrow outer raceway partition + 3 um source-closure diagnostic — 2026-07-15

## Scope

This report records the follow-up full-fixture diagnostic after `roller1_outer_raceway_partition_source_closure3um`. The previous source-closure run repaired the hard `roller_1` outer pair-specific transfer symptom, but its saved-MPH probe still showed only `1/6` `roller_1` pair-specific nonzero variables and a fragmented outer destination selection with 9 entities.

This run kept the useful `roller_1` +X `3[um]` source closure and changed only the outer-ring destination partition tool size:

```text
--verified-fixture-local-contact-patch-mode roller1_outer_raceway_narrow_partition_source_closure3um
```

The stage mode, `0.101[N]` BoundaryLoad, active rollers `12, 1, 2`, contact settings, weak guidance, temporary active-roller stabilization, and cage-inactive scope were unchanged. This is diagnostic evidence only, not a production/design-grade run.

## Code change

- Added verified fixture patch mode `roller1_outer_raceway_narrow_partition_source_closure3um`.
- Reused the `roller_1` +X `3[um]` source closure from the successful prior diagnostic.
- Replaced the prior destination partition tool size `0.7 x 2.4 x 16.4[mm]` with a narrower `0.35 x 1.2 x 16.4[mm]` outer-ring partition tool.
- Kept `roller_1` source selection on `geom1_roller_1_bnd`.
- Bound `cp_roller_1_outer_raceway` to:
  - source: `sel_roller_1_outer_contact`
  - destination: `sel_outer_raceway_1_contact`
- Added diagnostic markers:
  - `ROLLER1_OUTER_SOURCE_CLOSURE`
  - `ROLLER1_OUTER_RACEWAY_NARROW_PARTITION_SOURCE_CLOSURE_GEOM`
  - `ROLLER1_OUTER_RACEWAY_NARROW_PARTITION_SOURCE_CLOSURE_BIND`
- Added summary metadata role:
  - `roller1_outer_raceway_narrow_partition_with_3um_source_closure_diagnostic`

## Static verification

```bash
python3 -m pytest tests/test_core.py::TestSimulationSkills::test_3d_full_bearing_demo_prompt_fixture_and_quality_gate -q
python3 -m pytest tests/test_core.py -q
python3 -m compileall -q comsol_agent tests scripts
```

Results:

- Targeted fixture test: `1 passed`
- Full `tests/test_core.py`: `180 passed, 1 skipped`
- `compileall`: passed

## COMSOL commands

Full fixture run:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_raceway_narrow_partition_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_narrow_partition_source_closure3um \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_narrow_partition_source_closure3um \
  --cores 1
```

The run saved the configured MPH but did not complete a solved result package. It was interrupted after a long solve with the script summary recording:

```text
Solve failed: java.lang.NullPointerException
```

Configured-MPH no-solve diagnostic:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --diagnose-stage-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_narrow_partition_source_closure3um/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph \
  --diagnose-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_narrow_partition_source_closure3um/diagnostics_configured_mph \
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

- Full run summary: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_narrow_partition_source_closure3um/direct_3d_bearing_summary.json`
- Configured MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_narrow_partition_source_closure3um/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`
- Configured-MPH diagnostic JSON: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_narrow_partition_source_closure3um/diagnostics_configured_mph/stage_mph_diagnostic.json`
- Configured-MPH diagnostic Markdown: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_narrow_partition_source_closure3um/diagnostics_configured_mph/stage_mph_diagnostic.md`
- Refreshed matrix: `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.md`

No solved MPH or saved-MPH contact probe exists for this run.

## Full-stage result

- Stage: `single_solve_3_roller_boundary_load_0p101n_parametric`
- Stage solve success: `false`
- Solve error: `java.lang.NullPointerException`
- Native PNG: none
- Result package: none
- Physical validation: failed
- Active-roller distribution audit: no per-roller stress probes available because no solved field was produced

Physical validation errors from the summary:

- `COMSOL solve did not converge; no trustworthy 3D stress/contact field is available.`
- `Global solid.mises is missing or near zero.`
- `Inner-ring maxop_inner_ring(solid.mises) is missing or near zero.`
- `solid.disp is missing or zero.`

## Configured-MPH diagnostic

The configured model did bind the intended pair and selections:

| Item | Result |
|---|---:|
| `sel_roller_1_outer_contact` entity count | `2` |
| `sel_outer_raceway_1_contact` entity count | `9` |
| `geom1_roller_1_bnd` entity count | `6` |
| `geom1_partition_tool_roller1_outer_raceway_narrow_closure_patch_bnd` entity count | `5` |
| `geom1_partition_roller1_outer_raceway_narrow_closure_patch_bnd` entity count | `17` |
| `cp_roller_1_outer_raceway` source | `sel_roller_1_outer_contact`, 2 entities |
| `cp_roller_1_outer_raceway` destination | `sel_outer_raceway_1_contact`, 9 entities |

The narrowed construction tool did not reduce the final `sel_outer_raceway_1_contact` destination count; it stayed at 9 entities, the same count as the previous successful source-closure diagnostic.

## Evidence matrix status

After refresh:

- `summary_count=142`
- `row_count=294`
- `saved_contact_probe_report_count=42`
- `saved_contact_probe_source_destination_imbalance_count=18`
- `production_ready_count=0`
- `reaction_verified_stage_count=0`

No false production-ready or reaction-verified bump was introduced.

## Interpretation

This narrower destination-partition variant did not improve the previous result. It failed to solve and did not reduce the `roller_1` outer destination fragmentation. Because no solved field exists, this run provides no new pair-specific `Tn` evidence and cannot be used as contact-closure evidence.

The previous `roller1_outer_raceway_partition_source_closure3um` remains the strongest current local-topology progress point: it produced `roller_1` active stress, nonzero `solid.Tn_cp_roller_1_outer_raceway`, nonzero source-side field response, and no source/destination imbalance.

## Recommended next experiment

Do not keep shrinking the block partition tool; it did not reduce the selected destination entity count and worsened solve robustness. The next smallest experiment should keep the successful `+3[um]` source closure but change how the destination selection is formed after geometry build: use an explicit post-geometry destination entity override or a boundary-map-derived minimal destination selection from the already solved source-closure MPH, while preserving `cp_roller_1_outer_raceway`, the 0.101 N 3-roller stage, and all contact/solver settings.
