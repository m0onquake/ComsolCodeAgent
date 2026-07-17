# Roller 1 zero-carry no-resolve contact probe refresh — 2026-07-15

## Scope

This report refreshes the saved-MPH contact probe on the existing solved `0.101 N` 3-roller BoundaryLoad probe-gate result package. It does not re-solve the model. The purpose is to re-check the local/semilocal `roller_1` vs `roller_2`/`roller_12` contact-transfer evidence before attempting any broader 3/6/12-roller or cage expansion.

## Command

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph runtime_smoke/bearing_family_p12_boundaryload_probe_gate/bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate_20260713_195429_133133/bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate.mph \
  --contact-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_probe_gate/bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate/contact_probe_solved_mph_20260715_refresh \
  --cores 1
```

## Artifacts

- JSON: `runtime_smoke/bearing_family_p12_boundaryload_probe_gate/bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate/contact_probe_solved_mph_20260715_refresh/contact_probe_summary.json`
- Markdown: `runtime_smoke/bearing_family_p12_boundaryload_probe_gate/bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate/contact_probe_solved_mph_20260715_refresh/contact_probe_summary.md`

## Probe result

- Probe success: `true`
- Successful contact evaluations: `144`
- Nonzero contact evaluations: `90`
- Pair-enforcement diagnostic success: `true`
- Zero pair-specific contact-pressure rollers: `roller_1`
- Source/destination imbalance rollers: `roller_1`
- Nonzero reference rollers: `roller_2`, `roller_12`

## Roller comparison

| Roller | Pair-specific success | Pair-specific nonzero | Pair-specific ratio | Source/destination imbalance | Contact settings match nonzero references |
|---|---:|---:|---:|---:|---:|
| `roller_1` | 6 | 0 | 0.0 | true | true |
| `roller_2` | 6 | 2 | 0.3333333333 | false | true |
| `roller_12` | 6 | 2 | 0.3333333333 | false | true |

## Source/destination field check

| Roller | Inner source nonzero | Inner destination nonzero | Outer source nonzero | Outer destination nonzero |
|---|---:|---:|---:|---:|
| `roller_1` | false | true | false | true |
| `roller_2` | true | true | true | true |
| `roller_12` | true | true | true | true |

The refreshed probe again shows the distinctive `roller_1` failure signature: the raceway destination side is stressed, but the roller-side source contact selections remain zero for both inner and outer pairs. Adjacent load-side rollers do not show this imbalance.

## Geometry gap proxy

| Roller | Inner radial delta | Outer radial delta |
|---|---:|---:|
| `roller_1` | `9.810987 mm` | `9.811112 mm` |
| `roller_2` | `6.006468 mm` | `2.246619 mm` |
| `roller_12` | `6.006421 mm` | `2.246615 mm` |

The radial proxy is still not by itself a sufficient pass/fail metric because local two-body positive controls can show large radial deltas while still transferring pair-specific traction. However, in the full-bearing `0.101 N` result, the large `roller_1` radial mismatch coincides with zero source response and zero pair-specific contact transfer.

## Current interpretation

This refresh does not change the acceptance status:

- `roller_1` still fails pair-specific contact transfer.
- `roller_1` still has source-zero/destination-nonzero imbalance.
- Static contact feature settings and pair endpoints remain consistent with nonzero reference rollers.
- The result is diagnostic only; it is not production-ready and does not verify reaction/load closure.

The remaining leading suspicion is a full-fixture local topology/source-surface problem at the `0 deg / +X` roller position, possibly related to cylinder seam, local source-face partitioning, or raceway/roller imprint equivalence. The next minimum experiment should target `roller_1` source-surface construction in the full fixture before attempting 6-roller, 12-roller, or cage expansion.
