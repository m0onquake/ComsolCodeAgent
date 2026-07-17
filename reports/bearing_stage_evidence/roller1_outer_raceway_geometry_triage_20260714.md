# P12 3D cylindrical roller bearing — roller_1 outer raceway geometry triage

Date: 2026-07-14

## Scope

This note records the current local evidence for the `roller_1` zero-carry blocker in the 3D cylindrical roller bearing physical-closure chain. It is intentionally a diagnostic report, not a production-ready acceptance claim.

## Current acceptance matrix state

Refreshed with:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py --stage-evidence-matrix --stage-evidence-root runtime_smoke --stage-evidence-output-dir reports/bearing_stage_evidence
```

Latest matrix:

- `summary_count=131`
- `row_count=283`
- `production_ready_count=0`
- `reaction_verified_stage_count=0`
- `saved_contact_probe_report_count=36`
- `saved_reaction_probe_report_count=1`
- `saved_reaction_probe_verified_count=0`

Therefore the current bearing chain is **not** production-ready and does **not** have verified reaction/load closure.

## Key local evidence

### 1. Local outer-pair comparison

Artifact root:

`runtime_smoke/bearing_family_p12_local_single_pair_load_compare/`

Known result:

- `roller_1` local outer pair solves, but pair-specific `Tn` remains zero and contact gap/status remains non-physical.
- `roller_2` and `roller_12` under the same local outer-pair strategy produce nonzero pair-specific transfer.

This proves the Contact Pair probing machinery can detect real transfer in this model family; the failure is localized to the `roller_1` contact geometry/selection path.

### 2. roller_1 destination scans

Artifacts:

- `runtime_smoke/bearing_family_p12_local_roller1_outer_destination_override_scan/override_scan_contact_probe_compact.json`
- `runtime_smoke/bearing_family_p12_local_roller1_outer_destination_true_outer_scan/true_outer_scan_contact_probe_compact.json`
- `runtime_smoke/bearing_family_p12_local_roller1_outer_destination_midradius_scan/midradius_scan_contact_probe_compact.json`

Observed candidates:

- Original / inner-ish entities such as `[25,26]`, `[8]`, `[9]`, `[8,9]`: pair-specific `Tn=0`, gap `Infinity`, destination radial centroid around `19.5–19.7 mm`.
- True outer-ish entities `[11,15]`, `[12,16]`, `[17]`, `[11,12,15,16,17]`: pair-specific `Tn=0`, gap `Infinity`, destination radial centroid around `31.0–31.5 mm`.
- Mid-radius entities `[114,115,118,119]`, `[126,127]`, `[219,220]`: pair-specific `Tn=0`, destination radial centroid around `26.2–28.4 mm`.

Simple destination-entity guessing has therefore not recovered physical contact for `roller_1`.

### 3. Latest box-intersection rebuild diagnostic

Artifacts:

- `runtime_smoke/bearing_family_p12_boundaryload_box_intersection_rebuild/direct_3d_bearing_summary.json`
- `runtime_smoke/bearing_family_p12_boundaryload_box_intersection_rebuild/diagnostics_configured_mph/stage_mph_diagnostic.json`
- `runtime_smoke/bearing_family_p12_boundaryload_box_intersection_rebuild/boundary_entity_map_outer_ring_configured/boundary_entity_map.json`
- `runtime_smoke/bearing_family_p12_boundaryload_probe_gate/bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate/boundary_entity_map_outer_ring_solved/boundary_entity_map.json`

The diagnostic mode intentionally rebuilt the `roller_1` outer contact patch from a local Box/Intersection rather than reusing the previous explicit/partitioned entity guesses.

Configured-MPH no-solve audit:

- `box_roller_1_outer_contact_patch`: `Box`, entity count `2`, entities `[185,186]`
- `sel_outer_raceway_1_contact`: `Intersection`, entity count `0`, entities `[]`
- `cp_roller_1_outer_raceway`: source count `2`, destination count `0`
- `sel_outer_raceway_2_contact`: entity count `1`, entities `[9]`
- `sel_outer_raceway_12_contact`: entity count `1`, entities `[8]`

The solve fails at multiphysics compilation because the destination selection of the `roller_1` outer Contact Pair is empty. This is useful negative evidence: a local box that selects the `roller_1` outer source side does not intersect `geom1_outer_ring_bnd`, while homologous `roller_2` and `roller_12` boxes do intersect outer-ring boundaries.

### 4. Outer-ring boundary entity map

A new no-solve/saved-MPH boundary map CLI was added:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --map-boundary-entities-mph <mph> \
  --boundary-map-selection geom1_outer_ring_bnd \
  --boundary-map-output-dir <out>
```

On the configured box-intersection MPH, the tool can list `geom1_outer_ring_bnd` entities `[1..10]`, but centroid evaluation is unavailable because the configured model has no solution dataset. This is correctly recorded as a failed centroid map, not as physical evidence.

On the solved `0.101 N` probe-gate MPH, the same selection maps successfully:

- entity count `10`, successful centroid rows `10`;
- nearest entity to `roller_1` (`0 deg`) is entity `9`, centroid angle `45 deg`, radius `27.91 mm`, angular offset `15 deg`;
- nearest entity to `roller_2` (`30 deg`) is also entity `9`, centroid angle `45 deg`, radius `27.91 mm`, angular offset `15 deg`;
- nearest entity to `roller_12` (`330 deg`) is entity `7`, centroid angle `315 deg`, radius `36.01 mm`, angular offset `15 deg`;
- `geom1_outer_ring_bnd` centroid angles appear at quadrant/diagonal sectors around `45/135/225/315 deg`, plus degenerate near-center rows, rather than at every roller angle.

This is stronger geometry evidence for the `roller_1` failure: the named outer-ring boundary selection is coarse/global and does not expose a retained local boundary at the load-side `0 deg` roller-raceway patch. A `roller_1` local Box/Intersection can therefore select the roller-side source surfaces while producing an empty outer-ring destination.

### 5. x≈31 mm outer-raceway Box/Intersection diagnostic

New diagnostic mode:

`load_side_group_boundary_load_single_solve_0p101_roller1_outer_x31_box_intersection`

Artifacts:

- `runtime_smoke/bearing_family_p12_boundaryload_outer_x31_box_intersection/direct_3d_bearing_summary.json`
- `runtime_smoke/bearing_family_p12_boundaryload_outer_x31_box_intersection/stage_models/single_solve_3_roller_boundary_load_0p101n_roller1_outer_x31_box_intersection_configured.mph`
- `runtime_smoke/bearing_family_p12_boundaryload_outer_x31_box_intersection/diagnostics_configured_mph/stage_mph_diagnostic.json`
- `runtime_smoke/bearing_family_p12_boundaryload_outer_x31_box_intersection/contact_probe_solved_mph/contact_probe_summary.json`

This mode tests a cleaner hypothesis: if the previous x≈27 mm box was too close to the roller center, place the outer patch near the intended outer-raceway radius:

- `box_roller_1_outer_contact_patch`: x `30.4..31.6 mm`, y `-1.2..1.2 mm`, z `-8.6..8.6 mm`;
- `sel_outer_raceway_1_contact`: now non-empty, entities `[8,9]`;
- `cp_roller_1_outer_raceway`: source `[187,188]`, destination `[8,9]`;
- `sel_outer_raceway_2_contact`: `[9]`;
- `sel_outer_raceway_12_contact`: `[8]`.

The configured selection-empty failure is therefore removed. However, solved evidence still fails the physical gate:

- active roller distribution remains incomplete: `roller_1=0 Pa`, `roller_2≈9.77e4 Pa`, `roller_12≈1.10e5 Pa`;
- `roller_1` pair-specific finite nonzero `Tn` count remains `0`;
- `roller_2/12` retain nonzero pair-specific transfer;
- `roller_1` inner/outer radial centroid gap proxy remains about `9.811 mm`, while nonzero `roller_2/12` outer gap proxy is about `2.247 mm`;
- saved contact probe reports `roller_1` source/destination imbalance and zero pair-specific contact pressure.

This is an important refinement: the blocker is no longer merely "empty outer-raceway destination selection". Even with a non-empty `[8,9]` destination at the intended outer raceway radius, `roller_1` is still too far from an actually engaged local contact state. The remaining root cause is likely geometry placement/gap/activation at the roller_1 local contact neighborhood, not just the existence of any destination entity.

### 6. Roller body boundary entity map

Additional saved-MPH maps were generated from the x≈31 solved model:

- `runtime_smoke/bearing_family_p12_boundaryload_outer_x31_box_intersection/boundary_entity_map_roller1_solved/boundary_entity_map.json`
- `runtime_smoke/bearing_family_p12_boundaryload_outer_x31_box_intersection/boundary_entity_map_roller2_solved/boundary_entity_map.json`
- `runtime_smoke/bearing_family_p12_boundaryload_outer_x31_box_intersection/boundary_entity_map_roller12_solved/boundary_entity_map.json`

Key source-side geometry comparison:

- `roller_1` outer source entities `[187,188]`: centroid radius about `29.656 mm`, angular offsets about `±4.93 deg`.
- `roller_2` outer source entities `[181,182]`: centroid radii about `28.148/30.493 mm`, closest outer-side angular offset about `1.75 deg`.
- `roller_12` outer source entities `[175,176]`: centroid radii about `30.493/28.148 mm`, closest outer-side angular offset about `1.75 deg`.

This adds a source-side asymmetry: `roller_1` is not merely missing a good destination. Its selected outer source faces are also geometrically less aligned with the intended outer-raceway contact neighborhood than the nonzero `roller_2/12` faces. That explains why making `sel_outer_raceway_1_contact` non-empty did not recover pair-specific contact pressure.

### 7. Actual outer contact selection source/destination maps

The exact contact selections in the x≈31 solved model were mapped:

- `sel_roller_1_outer_contact`
- `sel_outer_raceway_1_contact`
- `sel_roller_2_outer_contact`
- `sel_outer_raceway_2_contact`
- `sel_roller_12_outer_contact`
- `sel_outer_raceway_12_contact`

Artifacts:

- `runtime_smoke/bearing_family_p12_boundaryload_outer_x31_box_intersection/boundary_entity_map_sel_roller1_outer_source/boundary_entity_map.json`
- `runtime_smoke/bearing_family_p12_boundaryload_outer_x31_box_intersection/boundary_entity_map_sel_roller1_outer_raceway/boundary_entity_map.json`
- `runtime_smoke/bearing_family_p12_boundaryload_outer_x31_box_intersection/boundary_entity_map_sel_roller2_outer_source/boundary_entity_map.json`
- `runtime_smoke/bearing_family_p12_boundaryload_outer_x31_box_intersection/boundary_entity_map_sel_roller2_outer_raceway/boundary_entity_map.json`
- `runtime_smoke/bearing_family_p12_boundaryload_outer_x31_box_intersection/boundary_entity_map_sel_roller12_outer_source/boundary_entity_map.json`
- `runtime_smoke/bearing_family_p12_boundaryload_outer_x31_box_intersection/boundary_entity_map_sel_roller12_outer_raceway/boundary_entity_map.json`

Entity-level aggregate radial projection along each roller's nominal radial direction:

- `roller_1 outer`: source `29.546 mm`, destination `19.735 mm`, signed delta `-9.811 mm`.
- `roller_2 outer`: source `29.205 mm`, destination `26.959 mm`, signed delta `-2.247 mm`.
- `roller_12 outer`: source `29.205 mm`, destination `26.959 mm`, signed delta `-2.247 mm`.

This is the cleanest current evidence for the zero-carry root cause. `roller_1` is not failing because its Contact Pair lacks a destination in the x≈31 diagnostic; it is failing because the selected destination entities `[8,9]`, when used for the 0° roller_1 pair, project to the wrong radial neighborhood (`~19.7 mm`) rather than the `~27 mm` effective raceway neighborhood seen by the nonzero `roller_2/12` pairs. The selection is topologically present but geometrically unsuitable for the local pair.

### 8. Angular-offset seam diagnostic

A diagnostic-only fixture option was added:

```bash
--verified-fixture-roller-angular-offset-deg <deg>
```

It rebuilds the verified 3D fixture with all rollers and cage pockets phase-shifted, leaving the staged contact gates unchanged. This probes whether `roller_1` being exactly at `0 deg/+X` is a COMSOL cylinder seam/topology issue.

Runs:

- `runtime_smoke/bearing_family_p12_boundaryload_angular_offset15/direct_3d_bearing_summary.json`
- `runtime_smoke/bearing_family_p12_boundaryload_angular_offset15/diagnostics_configured_mph/stage_mph_diagnostic.json`
- `runtime_smoke/bearing_family_p12_boundaryload_angular_offset7p5/direct_3d_bearing_summary.json`
- `runtime_smoke/bearing_family_p12_boundaryload_angular_offset7p5/diagnostics_configured_mph/stage_mph_diagnostic.json`

Results:

- Both `15 deg` and `7.5 deg` offset fixtures build successfully and save configured MPH artifacts.
- Both fail during the 0.101 N 3-roller BoundaryLoad solve with `java.lang.NullPointerException`.
- No native PNG or solved field is accepted.
- No per-roller stress distribution can be verified for these offset runs.
- No-solve diagnostics show the offset changes source partition topology: `roller_2` inner/outer source selections collapse to one entity (`[171]` and `[176]`) in both `15 deg` and `7.5 deg` runs, while `roller_1/12` retain two source entities.

Interpretation:

The angular-offset experiment supports the broader seam/topology sensitivity hypothesis, but it is not a direct repair. The existing source-partition heuristic is angle-sensitive and can create degenerate one-entity source selections after phase shift. Therefore, a robust fix should explicitly generate/retain local source and destination contact patches, rather than relying on the current Box/Intersection plus post-hoc source partition.

## Excluded explanations so far

Current evidence does not support these as primary root causes:

- missing `roller_1` body selection;
- inactive `roller_1` inner/outer contact features;
- gross load-angle mapping error;
- gross roller patch radial placement error in configured metadata;
- static contact setting mismatch versus `roller_2/12`;
- pure source/destination flip;
- a tenfold active-spring stiffness change;
- simple explicit destination override;
- simple global contact interference.

## Current root-cause judgement

The strongest current hypothesis is a geometry/selection/imprint problem:

`roller_1` does not currently have a trustworthy local outer-raceway contact surface that is simultaneously:

1. on the outer ring boundary,
2. in the expected roller_1 contact neighborhood,
3. usable as a Contact Pair destination, and
4. capable of producing nonzero pair-specific transfer under local or 3-roller load.

The boundary entity map, x≈31 diagnostic, roller-body map, exact contact-selection maps, and angular-offset diagnostics sharpen this: the available `geom1_outer_ring_bnd` entities are too coarse/sectorized for the `0 deg` roller_1 contact patch, simply using the nearest non-empty outer-raceway entities `[8,9]` does not close the contact, the selected `roller_1` destination projects to the wrong radial neighborhood, and the current source-partition heuristic is angle/topology sensitive. The next repair should create or retain matching local source/destination contact patches with the correct local geometry/gap near `roller_1`, rather than guessing existing entity IDs or merely rotating the fixture.

This remains a blocker for the global 3/6/12 roller BoundaryLoad and cage-contact acceptance chain.

## Next minimum experiment

Do not proceed to 6/12 rollers or cage-pocket closure yet.

The next useful experiment should repair or rebuild the `roller_1` outer-raceway patch itself, not tune solver parameters. Recommended minimum path:

1. Audit `geom1_outer_ring_bnd` coverage by angular sector for `roller_1`, `roller_2`, and `roller_12`.
2. If the `roller_1` sector lacks an outer-ring boundary at the required local patch, change the geometry/selection generation so the outer raceway creates an explicit, retained, named boundary surface for that sector.
3. Re-run the local single-pair outer test for `roller_1` only.
4. Pass criteria for local acceptance:
   - nonzero pair-specific `solid.Tn_cp_roller_1_outer_raceway`;
   - finite/physically reasonable contact gap/status;
   - nonzero source/destination stress/displacement response;
   - source/destination fields distinguishable from generic raceway traction;
   - saved configured/solved/failed MPH and contact probe report.
5. Only after that, return to the 3-roller `BoundaryLoad` stage and require `active_roller_nonzero_probe_ratio=1.0`.
