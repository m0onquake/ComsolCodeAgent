# Roller 1 outer construction-time partition patch diagnostic — 2026-07-15

## Scope

This report records the next `roller_1 outer` full-fixture topology diagnostic after the failed fixed auxiliary block, cylinder seam-shift, and fixed curved retained sleeve experiments.

The diagnostic mode is:

```text
--verified-fixture-local-contact-patch-mode roller1_outer_construction_partition_patch
```

The purpose is to test the repair-design Option A: create local source/destination topology during fixture construction, before the staged contact setup, instead of adding a fixed auxiliary target body or using staged post-hoc entity overrides.

## Code path added

Files changed:

- `scripts/run_agent_3d_bearing_full_demo.py`
- `tests/test_core.py`

The fixture builder now supports `roller1_outer_construction_partition_patch`. When enabled, it:

- creates a local partition tool for the outer-raceway side;
- creates a separate local partition tool for the `roller_1` source side;
- partitions `outer_ring` with `partition_roller1_outer_raceway_construction_patch`;
- partitions `roller_1` with `partition_roller1_outer_source_construction_patch`;
- keeps the local `0.101 N` 3-roller BoundaryLoad stage, contact settings, weak guidance, and temporary spring settings unchanged;
- narrows only `box_roller_1_outer_contact_patch`;
- binds `sel_roller_1_outer_contact` to `geom1_partition_roller1_outer_source_construction_patch_bnd`;
- binds `sel_outer_raceway_1_contact` to `geom1_partition_roller1_outer_raceway_construction_patch_bnd`;
- keeps the contact pair tag `cp_roller_1_outer_raceway` unchanged.

Default fixture behavior remains unchanged.

## Commands run

Static validation:

```bash
python3 -m pytest tests/test_core.py -q
python3 -m compileall -q comsol_agent tests scripts
```

Initial construction-time partition attempt:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_construction_partition_patch \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_patch \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_construction_partition_patch \
  --cores 1
```

This first attempt failed during fixture construction because one partition tool was reused after `keeptool=off` removed it:

```text
You need to provide input objects
- property: tool
```

After changing the fixture to use separate source and raceway partition tools, the rerun command was:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_construction_partition_patch \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_patch_rerun \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_construction_partition_patch_rerun \
  --cores 1
```

Configured-MPH diagnostic:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --diagnose-stage-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_patch_rerun/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph \
  --diagnose-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_patch_rerun/diagnostics_configured_mph \
  --cores 1
```

## Artifacts

Initial failed construction attempt:

- Summary: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_patch/direct_3d_bearing_summary.json`
- Failed MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_patch/failed_3d_contact_model.mph`
- Failed-MPH diagnostic: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_patch/diagnostics_failed_mph/stage_mph_diagnostic.json`

Rerun after separate partition tools:

- Summary: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_patch_rerun/direct_3d_bearing_summary.json`
- Configured MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_patch_rerun/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`
- Failed MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_patch_rerun/failed_3d_contact_model.mph`
- Configured diagnostic JSON: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_patch_rerun/diagnostics_configured_mph/stage_mph_diagnostic.json`
- Configured diagnostic Markdown: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_patch_rerun/diagnostics_configured_mph/stage_mph_diagnostic.md`

## Rerun result

The corrected construction-time partition fixture builds and saves a configured MPH. The staged solve still fails before any trustworthy solved stress/contact field is available:

```text
Solve failed:
找不到初始参数的解。
在 固体力学:
不收敛，相对步长太小。
返回的解不收敛。
没有返回所有参数步长。
```

No native COMSOL PNG or solved-MPH contact probe is available for the rerun.

## Configured-MPH topology audit

The configured-MPH diagnostic proves the construction-time partition did create and bind local source/destination topology:

| Item | Evidence |
|---|---|
| `sel_roller_1_outer_contact` | 9 entities: `[204, 205, 206, 207, 208, 209, 210, 211, 212]` |
| `sel_outer_raceway_1_contact` | 9 entities: `[8, 9, 11, 12, 13, 14, 15, 16, 17]` |
| `sel_roller_1_outer_contact` source input | `['box_roller_1_outer_contact_patch', 'geom1_partition_roller1_outer_source_construction_patch_bnd']` |
| `sel_outer_raceway_1_contact` destination input | `['box_roller_1_outer_contact_patch', 'geom1_partition_roller1_outer_raceway_construction_patch_bnd']` |
| `box_roller_1_outer_contact_patch` | narrowed to `x=[30.450,31.550] mm`, `y=[-1.800,1.800] mm`; 26 entities |
| `cp_roller_1_outer_raceway` source | `sel_roller_1_outer_contact`, 9 entities |
| `cp_roller_1_outer_raceway` destination | `sel_outer_raceway_1_contact`, 9 entities |
| `cp_roller_2_outer_raceway` destination | unchanged, `sel_outer_raceway_2_contact`, 2 entities |
| `cp_roller_12_outer_raceway` destination | unchanged, `sel_outer_raceway_12_contact`, 2 entities |

## Interpretation

This is a useful negative result and a partial implementation success:

- The first construction-time partition attempt exposed a concrete setup bug: reusing one partition tool with `keeptool=off` removed the tool before the second partition.
- After using separate source/raceway tools, fixture setup and configured-MPH save succeeded.
- The configured model proves `roller_1 outer` was actually rebound to construction-time partition result selections.
- The solve still fails at the initial parameter step, so no pair-specific `Tn`, source/destination field response, active roller distribution, or reaction closure can be claimed.

Compared with the fixed curved sleeve, this partition mode avoids adding a fixed auxiliary contact body. Compared with old staged partition modes, this performs topology generation during initial fixture construction. The remaining issue is likely that the partitioned local source/destination selections are still too broad or over-fragmented for stable contact initialization: `roller_1 outer` now has 9 source and 9 destination boundary entities, and the local box still captures 26 entities.

The next minimum experiment should refine the construction-time partition rather than expanding to 6/12/cage:

1. reduce the partition tool width or z extent to create fewer source/destination entities;
2. try keeping only the raceway construction partition while leaving the roller source selection at the previous two-entity source;
3. or add a configured-MPH boundary map of the partition result selections to choose the minimal retained source/destination subset before solving.

## Gate status

| Gate | Status |
|---|---|
| Code generation / CLI mode | Pass |
| Unit tests | Pass: `180 passed, 1 skipped` |
| Compileall | Pass |
| Fixture/template build after separate tools | Pass |
| Configured MPH saved | Pass |
| Construction-time partition source selection non-empty | Pass |
| Construction-time partition destination selection non-empty | Pass |
| Contact pair bound to partition selections | Pass |
| COMSOL solve | Fail |
| Native PNG | Fail |
| Pair-specific `roller_1 outer` transfer | Not available, no solved field |
| Active roller distribution | Not available, no solved field |
| Reaction/load closure | Not verified |
| Production-ready | false |
| Reaction-verified | false |

