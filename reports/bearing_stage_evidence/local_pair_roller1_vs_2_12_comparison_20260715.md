# Local outer-pair comparison: `roller_1` vs `roller_2/12`

Date: 2026-07-15

## Purpose

This report consolidates the local/semilocal evidence required before returning to the global 3-roller BoundaryLoad gate.

It compares:

1. full-bearing local single-pair runs for `roller_1`, `roller_2`, and `roller_12`;
2. the minimal two-body `roller_1 outer` positive-control smoke;
3. the global `0.101 N` full-bearing probe-gate failure.

The acceptance question is narrow:

> Can the probe chain detect pair-specific outer-raceway transfer for homologous rollers, and is `roller_1` uniquely failing inside the full-bearing geometry?

## Compared artifacts

| Case | Probe report |
|---|---|
| `roller_1` full-bearing local single-pair | `runtime_smoke/bearing_family_p12_local_single_pair_load_compare/bearing3d_roller1_outer_local_radial_outward_1pa/contact_probe_solved_mph/contact_probe_summary.json` |
| `roller_2` full-bearing local single-pair | `runtime_smoke/bearing_family_p12_local_single_pair_load_compare/bearing3d_roller2_outer_local_radial_outward_1pa/contact_probe_solved_mph/contact_probe_summary.json` |
| `roller_12` full-bearing local single-pair | `runtime_smoke/bearing_family_p12_local_single_pair_load_compare/bearing3d_roller12_outer_local_radial_outward_1pa/contact_probe_solved_mph/contact_probe_summary.json` |
| `roller_1` minimal two-body positive control | `runtime_smoke/bearing_family_p12_local_two_body_contact/roller1_outer_interference5um_rerun2/contact_probe_solved_mph/contact_probe_summary.json` |
| full-bearing `0.101 N` probe gate | `runtime_smoke/bearing_family_p12_boundaryload_probe_gate/bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate/contact_probe_solved_mph/contact_probe_summary.json` |

## Evidence table

| Case | Pair-specific nonzero count | `solid.Tn_cp_*_outer_raceway` | generic destination `solid.Tn` | source nonzero | destination nonzero | imbalance | radial delta proxy |
|---|---:|---:|---:|---|---|---|---:|
| `roller_1` full local single-pair | 0 | 0.0 | 6931.79868321796 | yes | yes | no | 9.811112 mm |
| `roller_2` full local single-pair | 1 | 1876.7678014047713 | 36152.808540988925 | yes | yes | no | 2.248617 mm |
| `roller_12` full local single-pair | 1 | 1921.7050038895657 | 26851.5192341985 | yes | yes | no | 2.248613 mm |
| `roller_1` two-body positive control | 1 | 11478.665853398717 | 11478.665853398717 | yes | yes | no | 8.960612 mm |
| `roller_1` full `0.101 N` probe gate | 0 | 0.0 | 5289.383135910183 | no | yes | yes | 9.811112 mm |

All compared contact status probes still report `gap_cp_* = Infinity`, so the gap gate remains unresolved. The useful discriminator here is pair-specific `Tn` plus source/destination field response.

## Interpretation

The local comparison establishes three points:

1. Homologous full-bearing local single-pair cases for `roller_2` and `roller_12` produce nonzero pair-specific outer-raceway `Tn`.
2. `roller_1` fails in the full-bearing local single-pair case even though source and destination fields are both nonzero.
3. `roller_1` succeeds in the minimal two-body positive control using the same logical pair name `cp_roller_1_outer_raceway`.

This rules out several weaker explanations:

- the saved-MPH contact probe cannot detect pair-specific `Tn`;
- `roller_1` variable naming is intrinsically broken;
- all outer-raceway local pairs fail;
- source/destination fields alone are enough to certify pair transfer.

The remaining blocker is localized to the full-bearing `0 deg` roller/raceway geometry and Contact Pair enforcement path.

## Gate status

| Gate | Status |
|---|---|
| local `roller_2/12` pair-specific transfer | pass |
| local `roller_1` full-bearing pair-specific transfer | fail |
| local `roller_1` minimal two-body positive control | pass |
| full `0.101 N` three-roller active distribution | fail |
| finite gap/contact-status gate | unresolved/fail |
| reaction/load closure | not verified |
| production-ready | fail |

## Next experiment specification

The next full-bearing experiment should alter actual local topology, not solver tuning:

1. construction-time retained source patch on `roller_1` outer surface;
2. construction-time conformal/curved destination patch in the `0 deg` outer-raceway sector;
3. explicit binding of `cp_roller_1_outer_raceway` to those retained patches;
4. no acceptance from native PNG alone;
5. acceptance only if:
   - `roller_1`, `roller_2`, and `roller_12` active roller probes are all nonzero;
   - `roller_1 outer` pair-specific `Tn` is finite nonzero;
   - source and destination stress/displacement both respond;
   - no source-zero/destination-nonzero imbalance remains;
   - reaction/load closure has a nonzero verified candidate before any production-ready claim.

