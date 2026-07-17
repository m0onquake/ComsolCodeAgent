# Roller 1 radial-clean outer raceway entity override diagnostic - 2026-07-17

## Scope

This report records the follow-up destination-selection experiment on the
partitioned `roller_1` outer-raceway fixture:

```text
--verified-fixture-local-contact-patch-mode roller1_outer_raceway_partition_source_closure3um
--contact-stage-mode load_side_group_boundary_load_single_solve_0p101_roller1_outer_entity_override
--roller1-outer-entity-override-entities 11,13,14,15
```

The `+3[um]` roller-1 source closure, `0.101[N]` load-side 3-roller stage,
contact settings, weak guidance, temporary active-roller springs, and
cage-inactive scope were kept unchanged. This remains diagnostic evidence,
not a design or production gate.

## Artifacts

- Full-stage summary:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um_radial_clean_entity_override/direct_3d_bearing_summary.json`
- Solved MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um_radial_clean_entity_override/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_source_closure3um_radial_clean_entity_override_20260717_002445_853007/bearing3d_load_side_boundaryload_0p101_roller1_outer_raceway_partition_source_closure3um_radial_clean_entity_override.mph`
- Saved-MPH contact probe:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um_radial_clean_entity_override/contact_probe_solved_mph/contact_probe_summary.json`
- Saved-MPH contact probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_raceway_partition_source_closure3um_radial_clean_entity_override/contact_probe_solved_mph/contact_probe_summary.md`

## Geometry result

The destination selection was explicitly rebound to:

```text
11, 13, 14, 15
```

The saved-MPH geometry moment probe reports:

- roller-1 outer source radial centroid: `0.029546965875216886 m`
- roller-1 outer destination radial centroid: `0.030999730688496166 m`
- absolute radial centroid gap proxy: `0.0014527648132792795 m`
- destination entities with nonzero pair-specific `Tn` integrals: `11, 13, 14, 15`

The prior destination entities `8,9` were therefore excluded from this
experiment. Their earlier radial centroid was approximately `19.5 mm`, while
the retained destination entities are approximately `31.0 mm`, matching the
outer-raceway neighborhood.

## Pair-specific transfer result

The destination-side pair-specific variable is evaluated and nonzero:

```text
solid.Tn_cp_roller_1_outer_raceway
```

| Destination entity | Max pair `Tn` (Pa) | Pair `Tn` surface integral |
|---:|---:|---:|
| 11 | 2315170.9456458716 | 5.3080861575434355 |
| 13 | 1878632.2048767612 | 0.23833597108389792 |
| 14 | 2069080.5640304906 | 0.2993118717922956 |
| 15 | 2315170.9456458716 | 5.323832999698072 |
| **Total** |  | **11.169567000117702** |

This confirms that the radial-clean destination selection is not a
zero-carry destination selection. It does not, by itself, prove force
balance across the Contact Pair.

## Source-side limitation

On the roller source selection `sel_roller_1_outer_contact`, the same
pair-specific expression remains unevaluable:

```text
solid.Tn_cp_roller_1_outer_raceway -> selection_error
```

The source selection still has nonzero generic field response and the source
geometry is present, but the probe cannot numerically evaluate the
destination-scoped pair variable on that source selection. Consequently, the
pair-transfer record is:

```text
source_abs_Tn_integral = null
destination_abs_Tn_integral = 11.169567000117702
source_evaluable = false
destination_evaluable = true
source_zero_destination_nonzero = false
source_unevaluable_destination_nonzero = true
```

The generic contact-status probe separately reports finite nonzero source and
destination response, so this is not a verified physical source/destination
imbalance. The correct status is unresolved source-side pair-variable scope
for the integral probe, while generic source response is present.

## Stage result

- Stage solve success: `true`
- Physical contact smoke validation: `true`
- Active rollers: `roller_1`, `roller_2`, `roller_12`
- Active roller nonzero ratio: `1.0`
- Active roller min/max stress ratio: `0.07546923340412397`
- `roller_1` maximum von Mises: `6043681.063166839 Pa`
- Global maximum von Mises: `9082466.923691012 Pa`
- Maximum displacement: `0.002402183366172964 m`
- Physical plausibility errors: none reported

The full-stage solver result is therefore numerically successful and the
active rollers are nonzero, but the stage remains explicitly diagnostic
because temporary stabilization is active and the source-side pair-specific
reaction is not independently evaluable.

## Interpretation

This experiment establishes a useful geometric correction:

1. the true outer destination neighborhood is represented by entities
   `11,13,14,15`;
2. all four retained destination entities carry nonzero pair-specific
   `Tn`;
3. the destination centroid is close to the roller source centroid compared
   with the earlier `8,9` selection.

It does not close the remaining source-side pair-variable problem. The
previous conclusion that an entity override alone did not change the global
stage behavior still holds. No further blind destination deletion is
justified by this run.

The next experiment should remain diagnostic-only and inspect the evaluated
source endpoint/pair-variable scope in the solved model. An explicit endpoint
rebind should be attempted only if that audit shows divergent pair ownership
or stale source binding. Load, preload, cage scope, and solver stabilization
should remain unchanged.

## Gate status

The evidence matrix must retain:

- `production_ready_count=0`
- `reaction_verified_stage_count=0`
