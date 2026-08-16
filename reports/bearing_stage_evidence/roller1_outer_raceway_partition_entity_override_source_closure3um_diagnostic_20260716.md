# Roller 1 partitioned outer raceway entity override + 3 um source closure diagnostic - 2026-07-16

## Scope

This report records one destination-only selection experiment on the
construction-time partition fixture:

```text
--verified-fixture-local-contact-patch-mode roller1_outer_raceway_partition_source_closure3um
--contact-stage-mode load_side_group_boundary_load_single_solve_0p101_roller1_outer_entity_override
--roller1-outer-entity-override-entities 8,9,11,13,14,15
```

The partitioned outer raceway and the `+3[um]` roller-1 source closure were
kept unchanged. The run kept the `0.101[N]` load-side 3-roller BoundaryLoad
stage, active rollers `12, 1, 2`, `cp_roller_1_outer_raceway`, contact
settings, weak guidance, temporary springs, and cage-inactive scope
unchanged. This is diagnostic evidence only.

## Diagnostic basis

The solved partition fixture was first probed per destination entity:

```text
runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um/entity_transfer_probe_solved_mph
```

The original destination selection contained entities:

```text
8, 9, 11, 12, 13, 14, 15, 16, 17
```

Nonzero pair-specific `Tn` integrals were found on:

```text
8, 9, 11, 13, 14, 15
```

Entities `12, 16, 17` had near-zero integrals and were removed only for the
full-fixture rerun.

## Commands

Partition-fixture entity probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph <partitioned-solved-mph> \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um/entity_transfer_probe_solved_mph \
  --probe-contact-entity-transfer \
  --contact-entity-transfer-selection sel_outer_raceway_1_contact \
  --contact-entity-transfer-roller 1 \
  --cores 1
```

Full-fixture destination override:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_raceway_partition_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101_roller1_outer_entity_override \
  --roller1-outer-entity-override-entities 8,9,11,13,14,15 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um_entity_override \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_source_closure3um_entity_override \
  --cores 1
```

Solved-MPH contact probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph <entity-override-solved-mph> \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um_entity_override/contact_probe_solved_mph \
  --probe-contact-entity-transfer \
  --contact-entity-transfer-selection sel_outer_raceway_1_contact \
  --contact-entity-transfer-roller 1 \
  --cores 1
```

## Artifacts

- Full-stage summary:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um_entity_override/direct_3d_bearing_summary.json`
- Configured MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um_entity_override/stage_models/single_solve_3_roller_boundary_load_0p101n_roller1_outer_entity_override_configured.mph`
- Solved MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um_entity_override/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_source_closure3um_entity_override_20260717_000308_162377/bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_source_closure3um_entity_override.mph`
- Contact probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um_entity_override/contact_probe_solved_mph/contact_probe_summary.json`
- Contact probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um_entity_override/contact_probe_solved_mph/contact_probe_summary.md`
- Pre-override entity probe:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um/entity_transfer_probe_solved_mph/contact_probe_summary.json`

## Result

- Stage solve success: `true`
- Active roller nonzero ratio: `1.0`
- Active rollers: `roller_1`, `roller_2`, `roller_12`
- Active roller max von Mises values:
  - `roller_1`: `6041890.424615464 Pa`
  - `roller_2`: `456111.9767762223 Pa`
  - `roller_12`: `506153.2591899262 Pa`
- Active roller min/max stress ratio: `0.07549160026437446`
- Global max von Mises: `9082466.923691012 Pa`
- Maximum displacement: `0.00240166414093838 m`
- Physical plausibility errors: none

The solved-MPH probe reported:

- Outer pair destination entities after override: `8,9,11,13,14,15`
- Aggregate `roller_1` outer pair-specific `Tn` integral: `11.167385860896044`
- Aggregate pair-specific success count: `6`
- Aggregate pair-specific nonzero count: `1`
- Source/destination imbalance: `false`
- All six retained destination entities had nonzero entity-level pair-specific
  `Tn` integrals.

## Interpretation

This experiment preserves the physically better partition fixture, but the
destination entity override did not change the global stress, displacement, or
aggregate pair-specific count relative to the unfiltered partition run. It is
therefore a topology-selection confirmation, not a new full-fixture closure
repair.

The source-side entity probe showed generic `p` and `mises` response on both
source entities, while pair-specific `Tn` is not evaluable on the source
selection. The current evidence does not justify another blind source entity
deletion or a pair endpoint swap.

This remains diagnostic smoke evidence. It is not design-grade or
production-ready evidence.

## Gate status

The evidence matrix must retain:

- `production_ready_count=0`
- `reaction_verified_stage_count=0`

## Next experiment

The next minimal experiment should target the remaining difference between
entity-level destination transfer and aggregate pair enforcement: add a
diagnostic-only audit of the contact feature's evaluated destination selection
and pair variable scope, then test one explicit outer-pair endpoint rebind on
the partition fixture only if that audit shows stale or divergent pair
ownership. Do not change load, preload, cage scope, or solver settings.
