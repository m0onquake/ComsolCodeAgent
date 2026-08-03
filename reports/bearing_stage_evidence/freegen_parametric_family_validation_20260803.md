# Free-generated parametric bearing family validation - 2026-08-03

## Scope

This run checked whether the segmented code-generation agent can generate 3D cylindrical roller bearing models across load direction, roller count, and geometric parameter changes without falling back to the verified fixture.

All LLM calls were run with local proxy variables unset because the local `127.0.0.1:7890` proxy path was unhealthy.

## Code-generation fixes validated

- Pair-bound Solid Mechanics `Contact` features are now rejected if generated code calls `feature('contact...').selection().named(...)` or `.selection().set(...)`. Runtime normalization removes those lines and keeps `set('pairs', [...])`, matching this COMSOL runtime where Contact feature selections are not editable after pair binding.
- Segment A now has an explicit Boolean-order contract for ring and cage construction. The gate rejects an empty-ring pattern such as `inner_diameter/2 - inner_race_outer_radius`.
- Segment D now explicitly requires `model.component('comp1').mesh().create('mesh1', 'geom1')` before retrieving `comp.mesh('mesh1')`; the previous prompt accidentally mentioned mesh creation in segment B and let D repeatedly retrieve a non-created mesh.
- The D-segment local mesh gate accepts both explicit repeated Size bindings and tuple/list loops, as long as every local Size calls `selection().geom('geom1', 2)` before `named(...)`.
- Final mirror-symmetry auditing now records angular mismatch and treats mirror symmetry as not applicable when a roller angular offset prevents exact mirror pairing.

## Evidence

| Case | Variant | Free generation | COMSOL setup / selections | Solve / audit result |
| --- | --- | --- | --- | --- |
| `PARAM8-X-1N-FREEGEN-FORMAL-REGEN1-20260803` | 8 rollers, `+X`, 1 N, inner/outer diameter 42/82 mm, roller 7 x 18 mm, 10 deg offset | Passed static segmented generation. First A attempt was rejected by Boolean-order gate, retry passed. | `template_run.success=true`; pre-solve selection audit passed. | Completed in 340.76 s; initialization and force solve passed; final strict audit failed only on outer contact resultant: 2.106840863% vs 2% gate. Existing artifact also failed mirror gate, but after the new applicability rule the 10 deg offset should skip exact mirror symmetry. |
| `PARAM8-Y-1N-FREEGEN-FORMAL-REGEN4-20260803` | 8 rollers, `+Y`, 1 N, same 42/82 mm parameter set and 10 deg offset | Passed regenerated static segmented generation after Contact-selection and Boolean-order fixes. | `template_run.success=true`; pre-solve selection audit passed; initialization passed. | Watchdog timed out at 900.13 s. Checkpoint reached `force_continuation_finished` with `force_solve_success=false`; summary reports `Solve failed: java.lang.NullPointerException`. No final audit was produced. |
| `param10_dims_static` | 10 rollers, `+X`, inner/outer diameter 45/90 mm, bearing width 20 mm, roller 7.5 x 17 mm, cage clearance 0.3 mm, 7.5 deg offset | Initial run failed in D because generated code retrieved `comp.mesh('mesh1')` before creating it. After the D prompt/gate fix, rerun passed A/B/C/D segmented generation and assembly quality gate. | COMSOL solve intentionally skipped for this static code-generation check. | Static production candidate passed. Assembled code contains `roller_count=10`, `roller_10`/`probe_roller_10` evidence, and `comp.mesh().create('mesh1', 'geom1')`. |

Key artifacts:

- `runtime_smoke/bearing_variant_param8_x_1n_freegen_20260803/formal_regen1/direct_3d_bearing_summary.json`
- `runtime_smoke/bearing_variant_param8_x_1n_freegen_20260803/formal_regen1/strict_watchdog_manifest.json`
- `runtime_smoke/bearing_variant_param8_y_1n_freegen_20260803/formal_regen4/direct_3d_bearing_summary.json`
- `runtime_smoke/bearing_variant_param8_y_1n_freegen_20260803/formal_regen4/strict_watchdog_manifest.json`
- `runtime_smoke/bearing_variant_param10_dims_freegen_20260803/static_regen1/segmented_generation/assembled_code.pyfrag`
- `runtime_smoke/bearing_variant_param10_dims_freegen_20260803/static_regen1/segmented_generation/assembled_manifest.json`

## Current interpretation

The agent can now generate different parameterized bearing structures without reverting to the baseline 12-roller fixture: 8-roller changed-dimension models reached COMSOL setup/selection/solve, and a 10-roller changed-dimension model passed the full static segmented generation pipeline.

`-X` and `+Y` are not yet stable for different reasons:

- Historical `-X` free-generated runs failed at nonlinear continuation with maximum Newton iterations. The signed load path is not just a sign flip in practice: active contact handoff and weak guidance are still tuned around the `+X` load-side progression, so the negative direction can enter a harder contact state before the force ramp is conditioned.
- `+Y` no longer fails because of generated code shape. The latest regenerated model passed strict setup, non-empty selection audit, pair binding, and initialization. It fails in the force-control continuation stage, with a COMSOL NullPointerException before final audit. This points to solver-path conditioning for a rotated load direction rather than a geometry/selection generation failure.
- The completed `+X` run is a near-pass physically but still not strict production pass: support reaction, applied load, load area, spring leakage, loaded-zone direction, and native PNG passed; the aggregate outer-contact resultant was 2.1068% off the target, just outside the 2% gate. This should be treated as a remaining force-transfer calibration issue, not a code-generation failure.

## Recommended next fixes

- Add direction-aware continuation schedules for `-X` and `+Y` instead of sharing the `+X`-optimized force-control ramp.
- Record force-stage checkpoint details before COMSOL exceptions so failures distinguish Newton nonconvergence, internal NullPointerException, and watchdog timeout.
- Tune the outer-contact resultant gate only after checking whether the 2.1068% `+X` residual is numerical quadrature/contact-pressure integration noise or real load leakage.
