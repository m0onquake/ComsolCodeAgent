# Roller 1 retained conformal destination entity override + 3 um source-closure diagnostic - 2026-07-16

## Scope

This report records a destination-only entity override selected from a
per-boundary solved-MPH transfer probe:

```text
--verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_source_closure3um
--contact-stage-mode load_side_group_boundary_load_single_solve_0p101_roller1_outer_entity_override
--roller1-outer-entity-override-entities 13,14,18,19
```

The retained conformal target and `+3[um]` roller-1 source closure were
unchanged. The run kept the `0.101[N]` load-side 3-roller BoundaryLoad stage,
active rollers `12, 1, 2`, `cp_roller_1_outer_raceway`, contact settings, weak
guidance, temporary stabilization, and cage-inactive scope unchanged. This is
diagnostic evidence only.

## Hypothesis

The baseline retained-conformal solved-MPH entity probe found nonzero
pair-specific `Tn` integrals on destination entities `13, 14, 18, 19`, while
entities `17, 20` had near-zero integrals. The experiment therefore removes
only `17, 20` from `sel_outer_raceway_1_contact`.

## Code change

- Added optional per-entity `MaxSurface` and `IntSurface` transfer probing to
  the saved-MPH contact probe.
- Added the CLI flag
  `--probe-contact-entity-transfer`.
- Added the CLI option
  `--roller1-outer-entity-override-entities`.
- Kept the existing entity-override stage mode and default `[8,9]` behavior
  unchanged.
- Added metadata identifying overrides sourced from solved-MPH transfer
  integrals.

## Static verification

```bash
python3 -m pytest tests/test_core.py -q
python3 -m compileall -q comsol_agent tests scripts
git diff --check
```

Results:

- `181 passed, 1 skipped`
- `compileall`: passed
- `git diff --check`: passed

## COMSOL commands

Per-entity baseline transfer probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph <retained-conformal-solved-mph> \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/entity_transfer_probe_solved_mph \
  --probe-contact-entity-transfer \
  --contact-entity-transfer-selection sel_outer_raceway_1_contact \
  --contact-entity-transfer-roller 1 \
  --cores 1
```

Full fixture entity-override run:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101_roller1_outer_entity_override \
  --roller1-outer-entity-override-entities 13,14,18,19 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_entity_override_source_closure3um \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_entity_override_source_closure3um \
  --cores 1
```

Solved-MPH probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph <entity-override-solved-mph> \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_entity_override_source_closure3um/contact_probe_solved_mph \
  --probe-contact-entity-transfer \
  --contact-entity-transfer-selection sel_outer_raceway_1_contact \
  --contact-entity-transfer-roller 1 \
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
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_entity_override_source_closure3um/direct_3d_bearing_summary.json`
- Configured MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_entity_override_source_closure3um/stage_models/single_solve_3_roller_boundary_load_0p101n_roller1_outer_entity_override_configured.mph`
- Solved MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_entity_override_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_entity_override_source_closure3um_20260716_230028_615615/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_entity_override_source_closure3um.mph`
- Contact probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_entity_override_source_closure3um/contact_probe_solved_mph/contact_probe_summary.json`
- Contact probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_entity_override_source_closure3um/contact_probe_solved_mph/contact_probe_summary.md`
- Baseline entity-transfer probe:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_source_closure3um/entity_transfer_probe_solved_mph/contact_probe_summary.json`

## Full-stage result

- Stage solve success: `true`
- Global max von Mises: `1283237524.5176585 Pa`
- Inner-ring max von Mises: `1340707999.1244123 Pa`
- Maximum displacement: `1.0084613842774894 m`
- Active roller nonzero ratio: `1.0`
- Active roller stress min/max ratio: `0.0003132465262287572`

Active roller values:

| Roller | Max von Mises |
|---|---:|
| `roller_1` | `1285361647.0195835` |
| `roller_2` | `402635.07087655854` |
| `roller_12` | `454102.5789090451` |

The solution remains numerically pathological. The entity override did not
repair the global stress/displacement state.

## Contact probe result

- `roller_1` pair-specific success count: `6`
- `roller_1` pair-specific nonzero count: `2`
- `roller_1` pair-specific nonzero ratio: `0.3333333333333333`
- Outer destination pair-specific
  `solid.Tn_cp_roller_1_outer_raceway`: `528595987.03602505`
- Outer source field response: nonzero, max abs
  `1036831294.5049396`
- Outer destination field response: nonzero, max abs
  `528595987.03602505`
- `roller_1` source/destination imbalance: `false`

The override selection audit is:

| Pair endpoint | Entity count | Entities |
|---|---:|---|
| `roller_1` outer source | `2` | runtime source entities |
| `roller_1` outer destination | `4` | `13, 14, 18, 19` |

All four retained destination entities have nonzero pair-specific `Tn`
integrals. This confirms the topology hypothesis, but it does not increase the
pair-specific nonzero count because the two nonzero contact candidates are
still measured across the six-candidate probe set.

## Interpretation

This experiment achieved a real topology result: the destination selection was
reduced from `6` to `4` entities, and the retained four entities all carry
nonzero pair-specific transfer integrals. It did not achieve the requested
physical closure result:

- `roller_1` pair-specific nonzero ratio remains `2/6`;
- active rollers `12/1/2` remain nonzero, but stress distribution is highly
  unbalanced;
- displacement remains about one metre under `0.101[N]`.

Therefore this is a local topology-repair signal, not design-grade or
production-ready evidence.

## Evidence matrix status

The matrix must retain:

- `production_ready_count=0`
- `reaction_verified_stage_count=0`

## Next experiment

Do not continue narrowing entities based only on the current solved field.
The next minimal experiment should inspect source-side entity transfer
symmetry and the pair-specific candidate evaluation on the four retained
boundaries, then test one source/destination pair binding change only if that
diagnostic identifies a concrete mismatch.
