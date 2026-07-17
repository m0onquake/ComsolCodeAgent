# Roller 1 outer retained conformal patch diagnostic — 2026-07-15

## Scope

This report records a full-fixture single-variable diagnostic for the `roller_1 outer` zero-carry problem. It adds a construction-time retained curved local target for `roller_1 outer`, narrows only the `roller_1 outer` source/destination contact box, and keeps the existing `0.101 N` load-side 3-roller BoundaryLoad stage unchanged.

The new diagnostic mode is:

```text
--verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_patch
```

It is not a production repair. Its purpose is to test whether a curved retained local target improves the full-fixture `roller_1 outer` source/destination topology compared with the earlier fixed rectangular auxiliary block and cylinder seam-shift experiments.

## Code path added

Files changed:

- `scripts/run_agent_3d_bearing_full_demo.py`
- `tests/test_core.py`

The fixture builder now supports `roller1_outer_retained_conformal_patch`. When enabled, it:

- creates a thin curved auxiliary sleeve using two `Cylinder` features and a `Difference` feature named `roller1_outer_retained_conformal_patch`;
- retains the boundary selection `geom1_roller1_outer_retained_conformal_patch_bnd`;
- narrows only `box_roller_1_outer_contact_patch` to `x=[30.450,31.550] mm`, `y=[-1.800,1.800] mm`, `z=[-8.5,8.5] mm`;
- binds `sel_outer_raceway_1_contact` to `Intersection(box_roller_1_outer_contact_patch, geom1_roller1_outer_retained_conformal_patch_bnd)`;
- keeps `cp_roller_1_outer_raceway` source as `sel_roller_1_outer_contact` and destination as `sel_outer_raceway_1_contact`;
- fixes the auxiliary curved patch through `fix_roller1_outer_retained_conformal_patch`.

Default fixture behavior remains unchanged.

## Commands run

Static validation:

```bash
python3 -m pytest tests/test_core.py -q
python3 -m compileall -q comsol_agent tests scripts
```

Full fixture diagnostic:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_patch \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_patch \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_patch \
  --cores 1
```

Configured-MPH no-solve diagnostic:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --diagnose-stage-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_patch/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph \
  --diagnose-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_patch/diagnostics_configured_mph \
  --cores 1
```

## Artifacts

- Summary: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_patch/direct_3d_bearing_summary.json`
- Configured MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_patch/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`
- Failed MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_patch/failed_3d_contact_model.mph`
- Configured diagnostic JSON: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_patch/diagnostics_configured_mph/stage_mph_diagnostic.json`
- Configured diagnostic Markdown: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_patch/diagnostics_configured_mph/stage_mph_diagnostic.md`

## Result

The fixture/template build succeeded and the configured MPH was saved. The curved retained patch was created and bound as intended.

Configured-MPH diagnostic:

| Item | Evidence |
|---|---|
| `sel_roller_1_outer_contact` | 2 entities: `[197, 198]` |
| `sel_outer_raceway_1_contact` | 6 entities: `[13, 14, 17, 18, 19, 20]` |
| `sel_outer_raceway_1_contact` input | `['box_roller_1_outer_contact_patch', 'geom1_roller1_outer_retained_conformal_patch_bnd']` |
| `box_roller_1_outer_contact_patch` | 12 entities; narrowed to `x=[30.450,31.550] mm`, `y=[-1.800,1.800] mm` |
| `cp_roller_1_outer_raceway` source | `sel_roller_1_outer_contact`, 2 entities |
| `cp_roller_1_outer_raceway` destination | `sel_outer_raceway_1_contact`, 6 entities |
| `cp_roller_2_outer_raceway` destination | unchanged, `sel_outer_raceway_2_contact`, 1 entity |
| `cp_roller_12_outer_raceway` destination | unchanged, `sel_outer_raceway_12_contact`, 1 entity |

Solve result:

```text
Solve failed:
找不到所有参数的解，
即使采用最小参数步长也是如此。
在 固体力学:
不收敛，相对步长太小。
返回的解不收敛。
没有返回所有参数步长。
```

No native COMSOL PNG or solved stress/contact field is available. Therefore no saved-MPH contact probe was run for this diagnostic.

## Interpretation

This is a useful negative result:

- It confirms that a construction-time curved retained local target can be created and bound specifically to `roller_1 outer`.
- It confirms the new mode does not globally rebind `roller_2` or `roller_12`.
- It does not recover a converged `0.101 N` full-fixture solution.
- It does not provide pair-specific `Tn`, gap, source/destination field, active-roller distribution, or reaction/load closure evidence.

Compared with `roller1_outer_aux_patch`, this mode improves the target geometry from a rectangular block to a curved sleeve, but the extra fixed sleeve still makes the full BoundaryLoad solve fail before any physical gate can be evaluated. Compared with `roller1_cylinder_seam_shift15`, this mode changes the local destination topology rather than only rotating the roller source seam, but it still does not produce a validated full-fixture contact state.

The next minimum experiment should reduce the auxiliary patch's mechanical intrusion rather than expand the global model:

1. try a non-fixed retained curved patch with only contact enforcement, or a much thinner/clearance-shifted sleeve;
2. alternatively, use a true geometry imprint/partition on the existing outer-ring boundary instead of adding a separate fixed sleeve body;
3. keep the same `0.101 N` three-roller gate and require `roller_1` pair-specific `Tn` plus source-side response before any 6/12/cage expansion.

## Gate status

| Gate | Status |
|---|---|
| Code generation / CLI mode | Pass |
| Unit tests | Pass: `180 passed, 1 skipped` |
| Compileall | Pass |
| Fixture/template build | Pass |
| Configured MPH saved | Pass |
| Curved retained patch destination non-empty | Pass |
| Contact pair bound to curved destination | Pass |
| COMSOL solve | Fail |
| Native PNG | Fail |
| Pair-specific `roller_1 outer` transfer | Not available, no solved field |
| Active roller distribution | Not available, no solved field |
| Reaction/load closure | Not verified |
| Production-ready | false |
| Reaction-verified | false |

