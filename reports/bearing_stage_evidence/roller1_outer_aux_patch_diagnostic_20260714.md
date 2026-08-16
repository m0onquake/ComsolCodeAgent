# P12 roller_1 outer auxiliary patch diagnostic

Date: 2026-07-14

## Purpose

This diagnostic tests whether a construction-time local auxiliary raceway patch can recover the `roller_1 outer` pair-specific contact path.

It is intentionally not a production repair. The patch is a fixed local block at the `roller_1` outer raceway neighborhood and is used only to determine whether `roller_1` zero-carry is caused by missing/unsuitable local destination geometry.

## Code path added

`scripts/run_agent_3d_bearing_full_demo.py` now supports:

```bash
--verified-fixture-local-contact-patch-mode roller1_outer_aux_patch
```

When enabled, the verified fixture builder creates `roller1_outer_aux_raceway_patch` before `geom1.run()`, retains its boundary selection, fixes that auxiliary boundary, and binds:

```text
sel_outer_raceway_1_contact =
  Intersection(box_roller_1_outer_contact_patch,
               geom1_roller1_outer_aux_raceway_patch_bnd)
```

Default fixture behavior remains unchanged (`none`).

## Command run

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_aux_patch \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_aux_patch \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_aux_patch \
  --cores 1
```

No-solve diagnostic:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --diagnose-stage-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_aux_patch/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph \
  --diagnose-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_aux_patch/diagnostics_configured_mph \
  --cores 1
```

## Artifacts

- Summary: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_aux_patch/direct_3d_bearing_summary.json`
- Configured MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_aux_patch/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`
- Failed MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_aux_patch/failed_3d_contact_model.mph`
- Diagnostic JSON: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_aux_patch/diagnostics_configured_mph/stage_mph_diagnostic.json`
- Diagnostic Markdown: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_aux_patch/diagnostics_configured_mph/stage_mph_diagnostic.md`

## Diagnostic result

The fixture build succeeded and the stage configured MPH was saved.

No-solve configured-MPH diagnostic confirms that the auxiliary destination was created and bound:

| Item | Evidence |
|---|---|
| `sel_outer_raceway_1_contact` | 6 entities: `[189, 190, 191, 192, 193, 194]` |
| `sel_outer_raceway_1_contact` input | `['box_roller_1_outer_contact_patch', 'geom1_roller1_outer_aux_raceway_patch_bnd']` |
| `sel_roller_1_outer_contact` | 2 entities: `[187, 188]` |
| `cp_roller_1_outer_raceway` | source `sel_roller_1_outer_contact` count 2; destination `sel_outer_raceway_1_contact` count 6 |
| `fix_roller1_outer_aux_raceway_patch` | active, bound to `geom1_roller1_outer_aux_raceway_patch_bnd`, 6 entities |

The solve failed before any trustworthy physical field or native PNG was produced:

```text
找不到初始参数的解。
在 固体力学:
不收敛，相对步长太小。
返回的解不收敛。
没有返回所有参数步长。
```

## Gate status

| Gate | Status |
|---|---|
| Fixture/template build | Pass |
| Configured MPH saved | Pass |
| Aux patch destination non-empty | Pass |
| Contact pair bound to aux destination | Pass |
| COMSOL solve | Fail |
| Native PNG | Fail |
| Pair-specific `roller_1` Tn/gap validation | Not available, no solved field |
| Active roller distribution | Not available, no solved field |
| Reaction/load closure | Not available |
| Production-ready | Fail |
| Reaction-verified | Fail |

## Interpretation

This result is negative but useful. It rules out the weakest version of the “no local destination exists” hypothesis: a local destination can be created and bound at construction time.

However, the fixed block auxiliary patch is too crude as a contact target for the existing 0.101 N BoundaryLoad solve. It does not recover a solved contact state and therefore cannot prove `roller_1` pair-specific transfer.

The next minimum experiment should keep the construction-time local-patch idea but improve the mechanics:

1. Use a curved or conformal local raceway patch instead of a rectangular fixed block.
2. Or use a local two-body roller/curved-raceway submodel with displacement closure first, then reintroduce BoundaryLoad.
3. Only after `roller_1 outer` produces finite nonzero pair-specific `Tn` and finite contact status should the 3-roller BoundaryLoad gate be retried.

