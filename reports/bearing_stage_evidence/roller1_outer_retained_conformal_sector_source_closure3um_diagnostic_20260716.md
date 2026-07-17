# Roller 1 retained conformal sector target + 3 um source-closure diagnostic - 2026-07-16

## Scope

This report records a sector-window variant of the retained conformal target:

```text
--verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_sector_source_closure3um
```

The retained conformal annulus is intersected with a local construction-time
window intended to reduce destination fragmentation. The run kept the
`0.101[N]` load-side 3-roller BoundaryLoad stage, active rollers `12, 1, 2`,
`cp_roller_1_outer_raceway`, contact settings, weak guidance, temporary
stabilization, and cage-inactive scope unchanged. This is diagnostic evidence
only.

## Code change

- Added the sector-window retained conformal mode.
- Reused the retained conformal target and `+3[um]` `roller_1` source closure.
- Added an annulus/window intersection before the final retained target.
- Kept the pair binding restricted to `roller_1` outer contact.
- Corrected the generated bind marker so sector mode reports
  `source_closure3um=true`.
- Added regression coverage for the complete bind marker.

## Static verification

```bash
python3 -m pytest tests/test_core.py -q
python3 -m compileall -q comsol_agent tests scripts
git diff --check
```

Results:

- `180 passed, 1 skipped`
- `compileall`: passed
- `git diff --check`: passed

## COMSOL commands

The full fixture run was executed before the marker correction:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_sector_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_sector_source_closure3um \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_sector_source_closure3um \
  --cores 1
```

Configured-MPH no-solve diagnostic:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --diagnose-stage-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_sector_source_closure3um/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph \
  --diagnose-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_sector_source_closure3um/diagnostics_configured_mph \
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
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_sector_source_closure3um/direct_3d_bearing_summary.json`
- Configured MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_sector_source_closure3um/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`
- Failed MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_sector_source_closure3um/failed_3d_contact_model.mph`
- Configured-MPH JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_sector_source_closure3um/diagnostics_configured_mph/stage_mph_diagnostic.json`
- Configured-MPH Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_sector_source_closure3um/diagnostics_configured_mph/stage_mph_diagnostic.md`
- Refreshed matrix:
  `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.md`

No solved MPH, native PNG, or saved-MPH contact probe was produced.

## Configured geometry audit

The configured MPH loaded successfully and all `89` required named selections
were runtime-bound. The local pair selections were:

| Pair endpoint | Entity count | Entities |
|---|---:|---|
| `sel_roller_1_outer_contact` | `2` | `187, 188` |
| `sel_outer_raceway_1_contact` | `8` | `189-196` |

The sector construction did not reduce destination fragmentation. The intended
sector feature exists in the generated model, but the final destination still
contains eight boundaries.

## Solve result

- Stage solve success: `false`
- Failure:
  `找不到初始参数的解；不收敛，相对步长太小；返回的解不收敛；没有返回所有参数步长。`
- Physical validation: unavailable because no solved field was produced.
- `roller_1` pair-specific `Tn`: not measurable from a solved field.
- Active-roller ratio: unavailable; no per-roller stress probes were produced.

The saved configured model also confirms the intended active contact feature
`contact_roller_1_outer` uses `cp_roller_1_outer_raceway`, while the failed
solver state prevents any claim about actual load transfer.

## Interpretation

This sector-window variant did not achieve its stated hypothesis. It preserved
the local source selection but left the destination at eight entities and made
the `0.101[N]` full-fixture solve fail to converge. It is weaker than the
retained conformal source-closure baseline and should not be promoted.

The matrix must retain:

- `production_ready_count=0`
- `reaction_verified_stage_count=0`

## Next experiment

Do not add more sector or partition geometry to this branch. The next work
should return to the strongest retained conformal source-closure baseline and
inspect why the six destination boundaries are only partially carrying the
pair-specific field before trying another single-variable topology change.
