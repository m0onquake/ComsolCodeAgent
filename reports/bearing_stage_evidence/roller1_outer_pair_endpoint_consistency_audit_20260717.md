# Roller 1 outer pair endpoint consistency audit - 2026-07-17

## Scope

This is a no-solve audit of the solved radial-clean diagnostic MPH:

```text
runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um_radial_clean_entity_override/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_source_closure3um_radial_clean_entity_override_20260717_002445_853007/bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_source_closure3um_radial_clean_entity_override.mph
```

The audit was added to the reusable stage-MPH diagnostic and does not call
`solve`.

## Result

The six raceway Contact Pair bindings for rollers `1, 2, 12` are consistent:

| Pair family | Expected source | Expected destination | Result |
|---|---|---|---:|
| `cp_roller_{i}_inner_raceway` | `sel_roller_{i}_inner_contact` | `sel_inner_raceway_{i}_contact` | `3/3` |
| `cp_roller_{i}_outer_raceway` | `sel_roller_{i}_outer_contact` | `sel_outer_raceway_{i}_contact` | `3/3` |

The radial-clean roller-1 outer pair is:

```text
source      = sel_roller_1_outer_contact       entities = [204, 205]
destination = sel_outer_raceway_1_contact      entities = [11, 13, 14, 15]
```

The corresponding Contact feature also references:

```text
contact_roller_1_outer.pairs = [cp_roller_1_outer_raceway]
```

The diagnostic summary is:

```json
{
  "success": true,
  "expected_pair_count": 6,
  "audited_pair_count": 6,
  "consistent_pair_count": 6,
  "divergent_pair_tags": [],
  "endpoint_rebind_justified": false
}
```

## Interpretation

The source-side unevaluable
`solid.Tn_cp_roller_1_outer_raceway` result is not explained by a stale or
swapped Contact Pair endpoint in this solved model. An endpoint swap is
therefore not justified as the next experiment because it would alter a
destination selection already shown to carry nonzero pair-specific `Tn`.

The remaining limitation is narrower: destination-side pair-specific `Tn`
evaluates, while the same variable on the roller source selection returns
`selection_error`. The run therefore remains a diagnostic contact smoke, not
a verified source/destination reaction balance.

## Artifacts

- No-solve JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um_radial_clean_entity_override/diagnostics_solved_mph_audit/stage_mph_diagnostic.json`
- No-solve Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um_radial_clean_entity_override/diagnostics_solved_mph_audit/stage_mph_diagnostic.md`
- Refreshed evidence matrix:
  `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.md`

## Gate status

- `production_ready_count=0`
- `reaction_verified_stage_count=0`
- `endpoint_rebind_justified=false`

