# Cylinder seam/source-surface API probe — 2026-07-15

## Scope

This report records a toy COMSOL geometry API probe added for the `roller_1` zero-carry investigation. It does not solve the bearing model. The purpose is to check whether the local COMSOL runtime accepts `Cylinder` feature properties that could shift or control the roller source-surface seam before the geometry is built.

## Why this matters

The latest saved-MPH contact probes show that, in the full `0.101 N` 3-roller BoundaryLoad result, `roller_1` has:

- pair-specific contact transfer count `0 / 6`;
- source/destination imbalance on both inner and outer contact pairs;
- zero roller-side source response but nonzero raceway-side destination response;
- contact feature settings and pair endpoints matching nonzero reference rollers `roller_2` and `roller_12`.

This makes the `0 deg / +X` roller source-surface topology or cylinder seam a leading suspect.

## Command

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-cylinder-seam-api \
  --cylinder-seam-probe-output-dir runtime_smoke/bearing_family_p12_cylinder_seam_api_probe/roller_source_seam_20260715_rerun \
  --cylinder-seam-probe-model-name bearing3d_cylinder_seam_api_probe_20260715_rerun \
  --cores 1
```

## Artifacts

- JSON: `runtime_smoke/bearing_family_p12_cylinder_seam_api_probe/roller_source_seam_20260715_rerun/cylinder_seam_api_probe.json`
- Markdown: `runtime_smoke/bearing_family_p12_cylinder_seam_api_probe/roller_source_seam_20260715_rerun/cylinder_seam_api_probe.md`
- Initial failed probe artifact, caused by helper-scope bug rather than COMSOL geometry failure: `runtime_smoke/bearing_family_p12_cylinder_seam_api_probe/roller_source_seam_20260715/cylinder_seam_api_probe.json`

## Result

- Probe success: `true`
- Geometry run success: `true`
- Accepted `Cylinder` properties:
  - `axis`
  - `axistype`
  - `pos`
  - `rot`
  - `selresult`
  - `selresultshow`
  - `type`
- Rejected `Cylinder` property:
  - `angle`

## Property set attempts

| Property | Value | Accepted |
|---|---|---:|
| `selresult` | `on` | true |
| `selresultshow` | `all` | true |
| `rot` | `15[deg]` | true |
| `rot` | `15` | true |
| `axis` | `['0', '0', '1']` | true |
| `axistype` | `z` | true |
| `angle` | `360[deg]` | false |
| `type` | `solid` | true |
| `pos` | `['0', '0', '-2[mm]']` | true |

## Interpretation

The local COMSOL runtime accepts `rot` and axis-related properties on `Cylinder` features and can run a toy geometry after those properties are set. This does not prove that the visible seam entity changes in the final bearing geometry, but it makes a full-fixture single-variable diagnostic technically feasible:

1. keep the 3-roller `0.101 N` BoundaryLoad setup unchanged;
2. apply a small pre-run `rot`/`axis` seam shift only to `roller_1` cylinder construction;
3. preserve all contact pair names, load direction, weak guidance, temporary spring, and contact feature settings;
4. solve or, if it fails, save configured/failed MPH;
5. run saved-MPH contact probe and require `roller_1` pair-specific `Tn` and roller-side source response to become nonzero before considering any global 3/6/12/cage expansion.

This is now the preferred next minimal experiment over more contact penalty/preload changes.

## Acceptance status

This probe is diagnostic only:

- production-ready: `false`
- reaction-verified: `false`
- 3-roller BoundaryLoad closure: still blocked by `roller_1` zero-carry
- 6/12 roller and cage expansion: not yet justified
