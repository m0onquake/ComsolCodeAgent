# Roller 1 retained conformal target + 3 um source-closure diagnostic - 2026-07-16

## Scope

This report records a full-fixture diagnostic that reused the retained conformal
outer target and added the previously useful `+3[um]` `roller_1` source closure:

```text
--verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_source_closure3um
```

The run kept the `0.101[N]` load-side 3-roller BoundaryLoad single-solve stage,
active rollers `12, 1, 2`, `cp_roller_1_outer_raceway`, contact settings, weak
guidance, temporary springs, and cage-inactive scope unchanged. This is
diagnostic evidence only.

## Code change

- Added fixture mode
  `roller1_outer_retained_conformal_source_closure3um`.
- Reused the existing retained conformal target geometry.
- Added the `roller_1` `+3[um]` +X source closure to this mode.
- Kept the contact pair as `cp_roller_1_outer_raceway`.
- Added explicit geometry/bind markers, CLI choice, diagnostic role metadata,
  and regression tests.

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
  --verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_source_closure3um \
  --cores 1
```

Saved-MPH no-resolve contact probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_source_closure3um_20260716_171750_712903/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_source_closure3um.mph \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/contact_probe_solved_mph \
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

- Summary:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/direct_3d_bearing_summary.json`
- Configured MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`
- Solved MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_source_closure3um_20260716_171750_712903/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_source_closure3um.mph`
- Native stage PNG:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/stage_plots/single_solve_3_roller_boundary_load_0p101n_parametric_native_volume.png`
- Contact probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/contact_probe_solved_mph/contact_probe_summary.json`
- Contact probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/contact_probe_solved_mph/contact_probe_summary.md`
- Refreshed matrix:
  `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.md`

## Full-stage result

- Stage solve success: `true`
- Global max von Mises: `1249460146.5506132 Pa`
- Maximum displacement: `1.1883195441906897 m`
- Active roller nonzero ratio: `1.0`
- Active roller values:

| Roller | Max von Mises |
|---|---:|
| `roller_1` | `1260595284.8760736` |
| `roller_2` | `402635.07087615196` |
| `roller_12` | `454102.5789121733` |

The native stage image was not accepted as bearing stress evidence because the
stage failed the basic physical plausibility selection. The active load
distribution is also highly unbalanced, with min/max ratio
`0.00031940074320977184`.

## Saved-MPH contact probe result

- Probe success: `true`
- Contact probe success count: `144`
- Contact probe nonzero count: `104`
- `roller_1` pair-specific success count: `6`
- `roller_1` pair-specific nonzero count: `2`
- `roller_1` pair-specific nonzero ratio: `0.3333333333333333`
- Outer pair-specific
  `solid.Tn_cp_roller_1_outer_raceway`: `15074.102593474117`
- Outer source field response: nonzero, max abs
  `1036831515.1385376`
- Outer destination field response: nonzero, max abs
  `528596858.61733407`
- `roller_1` source/destination imbalance: `false`
- `roller_1` zero pair-specific contact pressure: `false`

Pair entity counts:

| Pair endpoint | Entity count |
|---|---:|
| `roller_1` outer source | `2` |
| `roller_1` outer destination | `6` |

Relative to `roller1_outer_raceway_partition_source_closure3um`, this increases
the `roller_1` pair-specific nonzero count from `1/6` to `2/6` and preserves the
nonzero outer transfer and zero-imbalance signal. It does not prove complete
all-pair closure.

## Evidence matrix status

After refresh:

- `summary_count=145`
- `row_count=297`
- `converged_native_stage_count=201`
- `saved_contact_probe_report_count=44`
- `saved_contact_probe_source_destination_imbalance_count=19`
- `production_ready_count=0`
- `reaction_verified_stage_count=0`

## Interpretation

This is the strongest new local-topology signal in this iteration:

- `roller_1` outer pair-specific transfer is nonzero;
- source-side response is nonzero;
- source/destination imbalance is removed;
- active rollers `12/1/2` all have nonzero stress probes;
- pair-specific nonzero count improves to `2/6`.

The result remains numerically pathological: stress and displacement are far
too large for a trustworthy bearing state, and the active load distribution is
highly unbalanced. Therefore this mode is a topology-repair diagnostic, not a
design-grade or production-ready result.

## Next experiment

Keep this retained conformal target and `+3[um]` source closure, then make one
small destination-only geometry adjustment to reduce the retained target's
destination fragmentation from 6 entities while preserving the nonzero source
transfer. Do not change preload, solver policy, roller count, cage scope, or
reaction gates.
