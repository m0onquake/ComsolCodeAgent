# Roller 1 construction partition + 3 um source-closure diagnostic - 2026-07-16

## Scope

This report records a full-fixture diagnostic that combined construction-time
partitioning of the `roller_1` outer source and outer-ring destination with the
previously useful `+3[um]` source closure:

```text
--verified-fixture-local-contact-patch-mode roller1_outer_construction_partition_source_closure3um
```

The run kept the `0.101[N]` load-side 3-roller BoundaryLoad single-solve stage,
active rollers `12, 1, 2`, `cp_roller_1_outer_raceway`, contact settings, weak
guidance, temporary spring stabilization, and cage-inactive scope unchanged.
This is diagnostic evidence only.

## Code change

- Added fixture mode
  `roller1_outer_construction_partition_source_closure3um`.
- Reused the existing construction partition tools for:
  - `roller_1` source;
  - outer-ring destination.
- Preserved the `roller_1` `+3[um]` source closure.
- Added explicit geometry/bind markers and diagnostic role metadata.
- Added static regression coverage for the mode and its roller-1-only scope.

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
  --verified-fixture-local-contact-patch-mode roller1_outer_construction_partition_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_source_closure3um \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_construction_partition_source_closure3um \
  --cores 1
```

Configured-MPH diagnostic:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --diagnose-stage-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_source_closure3um/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph \
  --diagnose-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_source_closure3um/diagnostics_configured_mph \
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
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_source_closure3um/direct_3d_bearing_summary.json`
- Configured MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_source_closure3um/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`
- Failed MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_source_closure3um/failed_3d_contact_model.mph`
- Configured-MPH JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_source_closure3um/diagnostics_configured_mph/stage_mph_diagnostic.json`
- Configured-MPH Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_construction_partition_source_closure3um/diagnostics_configured_mph/stage_mph_diagnostic.md`
- Refreshed matrix:
  `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.md`

No solved MPH, native PNG, or saved-MPH contact probe was produced.

## Configured geometry audit

The construction features were present in the configured MPH:

| Item | Entity count |
|---|---:|
| `geom1_partition_roller1_outer_raceway_construction_patch_bnd` | `17` |
| `geom1_partition_roller1_outer_source_construction_patch_bnd` | `13` |
| `sel_roller_1_outer_contact` | `8` |
| `sel_outer_raceway_1_contact` | `9` |
| `cp_roller_1_outer_raceway` source | `8` |
| `cp_roller_1_outer_raceway` destination | `9` |

The intended construction features existed, but the final contact selections
were not narrowed to a small local pair. The configured model therefore does not
provide evidence of improved pair topology.

## Solve result

- Stage solve success: `false`
- Failure:
  `找不到初始参数的解；达到最大分离式迭代次数；返回的解不收敛；没有返回所有参数步长。`
- Physical validation: unavailable because no solved field was produced.
- `roller_1` pair-specific `Tn`: not measurable from a solved field.
- Active-roller ratio: unavailable; no per-roller stress probes were produced.

## Evidence matrix status

After refresh:

- `summary_count=144`
- `row_count=296`
- `saved_contact_probe_report_count=43`
- `saved_contact_probe_source_destination_imbalance_count=19`
- `production_ready_count=0`
- `reaction_verified_stage_count=0`

## Interpretation

This mode did not produce physical progress. It confirms that the construction
partition features can be created and audited, but the resulting selections
remain broad and the 0.101 N solve does not converge. It is weaker than the
previous `roller1_outer_raceway_partition_source_closure3um` result and should
not be reused as the main path.

## Next experiment

The next minimal experiment should use the existing retained conformal target
construction, add the proven `+3[um]` source closure, and avoid partitioning the
roller and outer ring into extra domains. Keep the same stage, pair, load, and
evidence gates.
