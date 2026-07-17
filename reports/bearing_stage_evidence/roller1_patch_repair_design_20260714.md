# P12 roller_1 local contact patch repair design

Date: 2026-07-14

## Purpose

This is the next executable repair design for the 3D cylindrical roller bearing physical-closure chain. It follows the evidence in `roller1_outer_raceway_geometry_triage_20260714.md` and keeps the acceptance gates unchanged.

The goal is not to make a prettier plot. The goal is to make `roller_1` local outer roller-raceway contact physically measurable:

- nonzero pair-specific `solid.Tn_cp_roller_1_outer_raceway`;
- finite/meaningful contact status instead of an infinite gap proxy;
- nonzero source and destination stress/displacement response;
- no reliance on generic `solid.Tn` on unrelated raceway surfaces;
- saved configured/solved/failed MPH and contact probe artifacts.

## Current blocker

The cleanest current evidence is the exact contact-selection map from the x≈31 diagnostic:

| Pair | Source radial projection | Destination radial projection | Delta |
|---|---:|---:|---:|
| `roller_1 outer` | `29.546 mm` | `19.735 mm` | `-9.811 mm` |
| `roller_2 outer` | `29.205 mm` | `26.959 mm` | `-2.247 mm` |
| `roller_12 outer` | `29.205 mm` | `26.959 mm` | `-2.247 mm` |

`roller_1` fails even when `sel_outer_raceway_1_contact` is non-empty (`[8,9]`). Therefore the problem is not merely an empty selection. The selected destination is topologically present but geometrically unsuitable for the `0 deg` local pair.

The reusable alignment report is saved at:

- `reports/bearing_stage_evidence/roller_outer_contact_selection_alignment_20260714.json`
- `reports/bearing_stage_evidence/roller_outer_contact_selection_alignment_20260714.md`

It quantifies `roller_1 outer` source/destination radial mismatch as `~4.37x` the nonzero `roller_2/12` reference mismatch.

The angular-offset diagnostics further show that the current source partition is angle/topology sensitive. Offsetting the fixture by `7.5 deg` or `15 deg` causes `roller_2` source selections to collapse to one entity and the 3-roller stage fails with `java.lang.NullPointerException`. Therefore, simply rotating the fixture is not a repair.

## Why previous partition attempts did not solve it

Previous staged partition attempts acted after the base fixture was already built:

- `load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch`
- `load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_rebind`
- `load_side_group_boundary_load_single_solve_0p101_roller1_partitioned_raceway_patch_min_entities`
- `roller1_outer_partition_single_pair_0p101`

They retained or overrode broad entity sets such as:

- outer retained/explicit entities `[8,9,11,15,25,26]`;
- min entities `[25,26]`;
- later x≈31 non-empty destination `[8,9]`.

These attempts either failed with `NullPointerException` or retained the same geometrically unsuitable coarse raceway surfaces. The core issue is that the local source/destination patches are not generated as matched local surfaces in the initial geometry topology.

## Proposed minimum repair

Implement a new diagnostic fixture variant rather than another staged-solve override.

### New fixture flag

Add a diagnostic-only option, for example:

```bash
--verified-fixture-local-contact-patch roller1_outer
```

or a named internal mode:

```text
verified_fixture_roller1_outer_local_patch
```

This should alter the verified fixture generation before `geom1.run()`, not after staged contact configuration.

### Geometry principle

For `roller_1 outer`, create matched local source/destination surfaces in the base geometry:

1. A retained local patch on `roller_1` outer cylindrical surface near the actual intended contact region.
2. A retained local patch on the outer raceway inner surface in the same local neighborhood.
3. Named selections bound directly to those retained patches:
   - `sel_roller_1_outer_contact`
   - `sel_outer_raceway_1_contact`
4. Contact Pair `cp_roller_1_outer_raceway` should bind to these named selections without relying on broad `geom1_outer_ring_bnd` sector entities `[8,9]`.

### Implementation options to test, in order

#### Option A — construction-time local partition

During `_build_verified_3d_full_bearing_code`, before final geometry run:

- create a narrow local tool at the `roller_1 outer` expected contact neighborhood;
- partition or imprint the outer ring object and roller_1 cylinder while the primitive objects are still clean;
- enable `selresult=on`, `selresultshow='bnd'`, and stable cumulative/named selections if available;
- create the contact selections from retained partition result selections, not from post-hoc global Box/Intersection.

Expected advantage: avoids staged re-partitioning a model that already has materials, pairs, physics, mesh, and solver state.

#### Option B — local auxiliary patch surface

If COMSOL partition remains unstable, introduce a thin local raceway patch object/surface as a diagnostic contact target:

- very thin local shell/solid patch conforming to the outer-raceway local neighborhood;
- material steel;
- fixed/tied or weakly coupled to outer ring for diagnostic only;
- Contact Pair destination is this local patch, not `geom1_outer_ring_bnd`.

This is not final design geometry, but it can prove whether the contact formulation and load path close once a correct local surface exists.

#### Option C — analytic local two-body submodel

If full-bearing topology remains unstable, create a reduced 3D roller-raceway local submodel:

- one roller segment;
- one local concave/flat raceway block;
- radial local BoundaryLoad or displacement;
- same contact probe gates.

This isolates COMSOL contact formulation from full-bearing assembly topology. It is a diagnostic precondition, not a substitute for global closure.

## Acceptance sequence after implementation

Run only local acceptance first:

1. Configure/save local model.
2. Solve or save failure.
3. Run `--probe-contact-mph` on solved MPH.
4. Required local pass:
   - `roller_1 outer` pair-specific `Tn` finite nonzero;
   - `pair_transfer_by_roller.roller_1.destination_abs_tn_nonzero_count > 0`;
   - gap/contact status no longer only infinite/zero;
   - source and destination centroid radial delta comparable to nonzero references or otherwise physically explained;
   - source/destination stress and displacement both respond.

Only then return to:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101 \
  --artifact-root runtime_smoke/<new_3roller_artifact> \
  --model-name <new_model_name> \
  --cores 1
```

The 3-roller gate still requires:

- active rollers `12/1/2` all nonzero;
- `active_roller_nonzero_probe_ratio=1.0`;
- no stress plateau rejection;
- pair-specific transfer for each active roller;
- nonzero reaction/load closure candidate before any design-grade claim.

## Current status

This design report does not change the acceptance result:

- `production_ready_count=0`;
- `reaction_verified_stage_count=0`;
- no 3/6/12/cage load closure has been verified.
