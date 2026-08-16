# Roller 1 retained conformal equal-height target + 3 um source-closure diagnostic - 2026-07-16

## Scope

This report records the equal-height variant of the retained conformal target
experiment:

```text
--verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_equal_height_source_closure3um
```

The retained conformal cylinders use equal axial height (`16.4[mm]`) and the
same `+3[um]` `roller_1` source closure as the strongest prior local-topology
experiment. The run kept the `0.101[N]` load-side 3-roller BoundaryLoad stage,
active rollers `12, 1, 2`, `cp_roller_1_outer_raceway`, contact settings, weak
guidance, temporary stabilization, and cage-inactive scope unchanged. This is
diagnostic evidence only.

## Code change

- Added the equal-height retained conformal fixture mode.
- Set both conformal cylinders to `16.4[mm]`.
- Kept the inner cylinder at `z=-8.2[mm]`.
- Preserved the `+3[um]` source closure and the roller-1-only pair binding.
- Added CLI metadata, diagnostic role metadata, and regression coverage.

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
  --verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_equal_height_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_equal_height_source_closure3um \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_equal_height_source_closure3um \
  --cores 1
```

Saved-MPH no-resolve contact probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_equal_height_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_equal_height_source_closure3um_20260716_193405_924257/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_equal_height_source_closure3um.mph \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_equal_height_source_closure3um/contact_probe_solved_mph \
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
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_equal_height_source_closure3um/direct_3d_bearing_summary.json`
- Configured MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_equal_height_source_closure3um/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`
- Solved MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_equal_height_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_equal_height_source_closure3um_20260716_193405_924257/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_equal_height_source_closure3um.mph`
- Native stage PNG:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_equal_height_source_closure3um/stage_plots/single_solve_3_roller_boundary_load_0p101n_parametric_native_volume.png`
- Contact probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_equal_height_source_closure3um/contact_probe_solved_mph/contact_probe_summary.json`
- Contact probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_equal_height_source_closure3um/contact_probe_solved_mph/contact_probe_summary.md`
- Refreshed matrix:
  `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.md`

## Full-stage result

- Stage solve success: `true`
- Global max von Mises: `1249460144.0479639 Pa`
- Inner-ring max von Mises: `1340705247.26117 Pa`
- Maximum displacement: `1.0084613842775283 m`
- Active roller nonzero ratio: `1.0`
- Active roller stress min/max ratio: `0.0003193998958665981`

Active roller values:

| Roller | Max von Mises |
|---|---:|
| `roller_1` | `1260598628.8747087` |
| `roller_2` | `402635.07079215825` |
| `roller_12` | `454102.5789094943` |

The solution is numerically pathological: displacement is about one metre
under a `0.101[N]` diagnostic load and active-roller stress is highly
unbalanced. The native image therefore does not establish a trustworthy
bearing state.

## Saved-MPH contact probe result

- Contact probe success count: `144`
- Contact probe nonzero count: `104`
- `roller_1` pair-specific success count: `6`
- `roller_1` pair-specific nonzero count: `2`
- `roller_1` pair-specific nonzero ratio: `0.3333333333333333`
- Outer pair-specific
  `solid.Tn_cp_roller_1_outer_raceway`: `528596152.46337634`
- Outer source field response: nonzero, max abs
  `437005.88720154203`
- Outer destination field response: nonzero, max abs
  `3485555.0079607693`
- `roller_1` source/destination imbalance: `false`
- `roller_1` zero pair-specific contact pressure: `false`

Pair entity counts:

| Pair endpoint | Entity count |
|---|---:|
| `roller_1` outer source | `2` |
| `roller_1` outer destination | `6` |

## Interpretation

Equalizing the axial heights did not improve the local topology signal relative
to `roller1_outer_retained_conformal_source_closure3um`: the outer pair remains
nonzero and source/destination imbalance remains absent, but the pair-specific
nonzero count is still `2/6` and the global solution remains physically
untrustworthy. This is a diagnostic topology result, not a design-grade or
production-ready result.

## Evidence matrix status

The matrix must retain:

- `production_ready_count=0`
- `reaction_verified_stage_count=0`

## Next experiment

Do not promote this equal-height variant. Continue from the strongest retained
conformal source-closure baseline only if a new destination topology change can
be justified by a single measurable hypothesis.
