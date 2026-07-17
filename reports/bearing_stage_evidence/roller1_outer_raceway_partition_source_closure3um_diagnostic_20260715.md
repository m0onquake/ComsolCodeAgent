# Roller 1 outer raceway partition + 3 um source-closure diagnostic — 2026-07-15

## Scope

This report records a full-fixture single-variable diagnostic for the P12 3D cylindrical-roller bearing closure chain. The run combines the prior `roller1_outer_raceway_partition_only` destination topology with a small `roller_1` source-side radial closure:

```text
--verified-fixture-local-contact-patch-mode roller1_outer_raceway_partition_source_closure3um
```

The diagnostic keeps the existing `0.101 N` load-side 3-roller BoundaryLoad single-solve stage, active rollers `12, 1, 2`, contact settings, weak guidance, temporary active-roller stabilization, and temporary cage stabilization. It does not expand to 6/12 rollers or cage contact, and it is not a production/design-grade gate.

## Code change

- Added verified fixture patch mode `roller1_outer_raceway_partition_source_closure3um`.
- Shifted only `roller_1` from `27.000[mm]` to `27.003[mm]` in the +X direction for this mode.
- Kept the `roller_1` source selection on `geom1_roller_1_bnd`.
- Kept the outer raceway destination on `geom1_partition_roller1_outer_raceway_only_patch_bnd`.
- Added setup markers:
  - `ROLLER1_OUTER_SOURCE_CLOSURE`
  - `ROLLER1_OUTER_RACEWAY_PARTITION_ONLY_GEOM|...|source_closure3um=true`
  - `ROLLER1_OUTER_RACEWAY_PARTITION_ONLY_BIND`
- Added summary metadata role:
  - `roller1_outer_raceway_partition_with_3um_source_closure_diagnostic`

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
  --verified-fixture-local-contact-patch-mode roller1_outer_raceway_partition_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_source_closure3um \
  --cores 1
```

Saved-MPH no-resolve contact probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_source_closure3um_20260715_062323_527184/bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_source_closure3um.mph \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um/contact_probe_solved_mph \
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

- Full run summary: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um/direct_3d_bearing_summary.json`
- Configured stage MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`
- Solved MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_source_closure3um_20260715_062323_527184/bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_source_closure3um.mph`
- Native PNG: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um/stage_plots/single_solve_3_roller_boundary_load_0p101n_parametric_native_volume.png`
- Contact probe JSON: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um/contact_probe_solved_mph/contact_probe_summary.json`
- Contact probe Markdown: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um/contact_probe_solved_mph/contact_probe_summary.md`
- Refreshed matrix: `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.md`

## Full-stage result

- Stage solve success: `true`
- Stage: `single_solve_3_roller_boundary_load_0p101n_parametric`
- Active rollers: `12, 1, 2`
- Boundary load: `0.101[N]`
- Native PNG quality gate: passed
- Global max von Mises: `9.082466923691012e6 Pa`
- Active roller nonzero ratio: `1.0`
- Active roller zero-stress rollers: none

Per-active-roller von Mises probe:

| Roller | Max von Mises |
|---|---:|
| `roller_1` | `6041890.424605975` |
| `roller_2` | `456111.9767762223` |
| `roller_12` | `506153.2591899262` |

## Saved-MPH contact probe result

- Probe success: `true`
- Contact probe success count: `144`
- Contact probe nonzero count: `106`
- `roller_1` pair-specific success count: `6`
- `roller_1` pair-specific nonzero count: `1`
- `roller_1` source/destination imbalance: `false`
- `roller_1` zero pair-specific contact pressure: `false`

Key `roller_1` values:

| Evidence | Result |
|---|---:|
| Outer destination pair-specific `solid.Tn_cp_roller_1_outer_raceway` | `2316720.3191555105` |
| Outer source generic field response | nonzero, max abs `6041890.42453211` |
| Outer destination generic field response | nonzero, max abs `8100224.7856930345` |
| Outer pair source entity count | `2` |
| Outer pair destination entity count | `9` |

This is the first saved-MPH full-fixture probe in this diagnostic chain where the `roller_1` outer pair-specific transfer is nonzero and the previous `roller_1` source-zero/destination-nonzero imbalance is removed.

Remaining caveat: `roller_1` pair-specific nonzero count is `1/6`, so this is an outer-transfer repair signal, not a complete all-pair closure proof.

## Evidence matrix status

After refresh:

- `summary_count=141`
- `row_count=293`
- `saved_contact_probe_report_count=42`
- `saved_contact_probe_source_destination_imbalance_count=18`
- `production_ready_count=0`
- `reaction_verified_stage_count=0`

No false production-ready or reaction-verified bump was introduced.

## Interpretation

The `roller1_outer_raceway_partition_source_closure3um` diagnostic produces real local physical progress relative to `roller1_cylinder_seam_shift15` and `roller1_outer_raceway_partition_only`:

- `roller_1` is no longer zero in the active-roller stress gate;
- active rollers `12/1/2` are all nonzero;
- `roller_1` outer pair-specific `solid.Tn_cp_roller_1_outer_raceway` is nonzero;
- `roller_1` source-side field response is nonzero;
- the saved-MPH pair-enforcement diagnostic reports `source_destination_imbalance=false` for `roller_1`.

This does not prove production/design-grade closure. The stage still uses temporary stabilization and weak guidance, reaction equivalence is not verified, cage contact is not active, and the matrix correctly keeps `production_ready_count=0` and `reaction_verified_stage_count=0`.

## Recommended next experiment

Keep the same 0.101 N 3-roller BoundaryLoad stage and avoid expanding scope. The next smallest useful experiment is to preserve the now-working `roller_1` +3 um source closure while reducing the destination fragmentation introduced by the partition-only target, for example a narrower/cleaner retained destination patch or a source-side retained patch variant that aims to improve `roller_1` pair-specific nonzero count beyond `1/6` without changing solver or preload policy.
