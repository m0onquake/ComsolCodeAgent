# Roller 1 outer raceway-only construction partition diagnostic — 2026-07-15

## Scope

This report records a narrower follow-up to the construction-time source+raceway partition experiment. The previous `roller1_outer_construction_partition_patch` mode proved that both source and raceway can be partitioned during fixture construction, but it fragmented `roller_1 outer` into 9 source and 9 destination entities and failed at initial contact solve.

The new diagnostic mode is:

```text
--verified-fixture-local-contact-patch-mode roller1_outer_raceway_partition_only
```

It partitions only the outer-ring target side and keeps the `roller_1` source side on the original `geom1_roller_1_bnd` path. The intent is to reduce source-side fragmentation while testing whether a construction-time retained destination patch alone can recover `roller_1 outer` pair transfer.

## Code path added

Files changed:

- `scripts/run_agent_3d_bearing_full_demo.py`
- `tests/test_core.py`

When enabled, this mode:

- creates `partition_tool_roller1_outer_raceway_only_patch`;
- partitions only `outer_ring` with `partition_roller1_outer_raceway_only_patch`;
- narrows only `box_roller_1_outer_contact_patch`;
- binds `sel_outer_raceway_1_contact` to `geom1_partition_roller1_outer_raceway_only_patch_bnd`;
- keeps `sel_roller_1_outer_contact` bound through the original `geom1_roller_1_bnd` path;
- keeps the contact pair tag `cp_roller_1_outer_raceway` unchanged.

Default fixture behavior remains unchanged.

## Commands run

Static validation:

```bash
python3 -m pytest tests/test_core.py -q
python3 -m compileall -q comsol_agent tests scripts
```

Full fixture diagnostic:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_raceway_partition_only \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_only \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_only \
  --cores 1
```

Saved-MPH contact probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_only/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_only_20260715_060615_840871/bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_only.mph \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_only/contact_probe_solved_mph \
  --cores 1
```

## Artifacts

- Summary: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_only/direct_3d_bearing_summary.json`
- Configured MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_only/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`
- Solved MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_only/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_only_20260715_060615_840871/bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_only.mph`
- Native stage PNG: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_only/stage_plots/single_solve_3_roller_boundary_load_0p101n_parametric_native_volume.png`
- Contact probe JSON: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_only/contact_probe_solved_mph/contact_probe_summary.json`
- Contact probe Markdown: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_only/contact_probe_solved_mph/contact_probe_summary.md`

## Stage result

The model solved and produced a result package, but the physical gate remains failed:

- Stage solve success: `true`
- Stage: `single_solve_3_roller_boundary_load_0p101n_parametric`
- Active rollers: `12, 1, 2`
- Boundary load: `0.101[N]`
- Global max von Mises: `9.082466923966536e6 Pa`
- Inner-ring max von Mises: `1.5313105316250054e7 Pa`
- Max displacement: `0.0018147419819672733 m`
- Active roller nonzero ratio: `0.6666666666666666`
- Active roller gate: failed
- Zero active roller: `roller_1`

Per-roller von Mises probe from the stage summary:

| Roller | Max von Mises |
|---|---:|
| `roller_1` | `0.0` |
| `roller_2` | `264294.5921587763` |
| `roller_12` | `297021.93002071505` |

The native PNG exists and passes the basic nonblank/nonmonochrome image check, but the stage image selector correctly refuses to present it as bearing stress evidence because physical plausibility gates failed.

## Saved-MPH contact probe result

- Probe success: `true`
- Contact probe success count: `144`
- Contact probe nonzero count: `90`
- Zero pair-specific contact-pressure rollers: `roller_1`
- Source/destination imbalance rollers: `roller_1`
- Nonzero reference rollers: `roller_2`, `roller_12`

| Roller | Outer source entities | Outer destination entities | Pair-specific nonzero | Source/destination imbalance | Outer source response | Outer destination response |
|---|---:|---:|---:|---:|---:|---:|
| `roller_1` | 2 | 9 | `0 / 6` | true | false | true |
| `roller_2` | 2 | 2 | `2 / 6` | false | true | true |
| `roller_12` | 2 | 2 | `2 / 6` | false | true | true |

Important pair-specific result:

- `roller_1` remains zero pair-specific transfer.
- `roller_1` source-side response remains zero.
- `roller_2` and `roller_12` remain nonzero references.

## Interpretation

This is a useful negative result with one important positive control:

- Raceway-only construction partition does not break solve convergence, unlike the source+raceway partition and fixed curved sleeve modes.
- The destination side is now construction-time partitioned and non-empty, but `roller_1` still does not carry pair-specific load.
- Keeping the original two-entity roller source path is not sufficient to recover source-side response.
- Therefore, the remaining blocker is not just a missing retained destination patch. It is the matched engagement between `roller_1` source and destination at the `0 deg / +X` sector.

The next minimum experiment should target source engagement without returning to over-fragmented 9-entity source partitions:

1. keep this raceway-only partitioned destination;
2. apply a very small roller_1 source-side radial closure or local source patch offset only for `roller_1 outer`;
3. or select the minimal source subset from the construction-partition source result instead of all 9 source entities;
4. rerun the same `0.101 N` gate and require `roller_1` pair-specific `Tn` plus source response to become nonzero.

## Gate status

| Gate | Status |
|---|---|
| Code generation / CLI mode | Pass |
| Unit tests | Pass: `180 passed, 1 skipped` |
| Compileall | Pass |
| Fixture/template build | Pass |
| Configured MPH saved | Pass |
| COMSOL solve | Pass |
| Native PNG basic image quality | Pass |
| Physical plausibility gate | Fail |
| `roller_1 outer` pair-specific transfer | Fail, still zero |
| `roller_1` source response | Fail, still zero |
| Active roller distribution | Fail, `2 / 3` active rollers nonzero |
| Reaction/load closure | Not verified |
| Production-ready | false |
| Reaction-verified | false |

