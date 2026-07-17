# Full-bearing vs local-control `roller_1 outer` pair-transfer comparison

Date: 2026-07-15

## Purpose

This note compares the same logical contact path across two solved cases:

- full 3D bearing `0.101 N` probe-gate stage;
- local two-body `roller_1 outer` positive-control smoke.

The purpose is to identify which acceptance signal changes when `roller_1 outer` is moved from the full-bearing geometry into a controllable local model.

## Compared artifacts

Full-bearing diagnostic:

`runtime_smoke/bearing_family_p12_boundaryload_probe_gate/bearing3d_load_side_boundaryload_single_solve_0p101_probe_gate/contact_probe_solved_mph/contact_probe_summary.json`

Local two-body positive control:

`runtime_smoke/bearing_family_p12_local_two_body_contact/roller1_outer_interference5um_rerun2/contact_probe_solved_mph/contact_probe_summary.json`

Auxiliary full-fixture patch configured diagnostic:

`runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_aux_patch/diagnostics_configured_mph/stage_mph_diagnostic.json`

## Evidence table

| Signal | Full bearing `0.101 N` probe-gate | Local two-body positive control |
|---|---:|---:|
| Contact probe success / nonzero count | `144 / 90` | `24 / 18` |
| `roller_1` pair-specific nonzero count | `0` | `1` |
| `roller_1` pair-specific success count | `6` | `3` |
| `solid.Tn_cp_roller_1_outer_raceway` on destination | `0.0` | `11478.665853398717` |
| generic `solid.Tn` on destination | `5289.383135910183` | `11478.665853398717` |
| outer source field nonzero | no | yes |
| outer destination field nonzero | yes | yes |
| source-zero / destination-nonzero imbalance | yes | no |
| `gap_cp_roller_1_outer_raceway` | `Infinity` | `Infinity` |
| radial centroid delta proxy | `9.811112 mm` | `8.960612 mm` |

The auxiliary full-fixture patch did create and bind a non-empty destination:

| Item | Value |
|---|---|
| `sel_outer_raceway_1_contact` entity count | `6` |
| `sel_outer_raceway_1_contact` entities | `[189, 190, 191, 192, 193, 194]` |
| `cp_roller_1_outer_raceway` source | `sel_roller_1_outer_contact`, count `2` |
| `cp_roller_1_outer_raceway` destination | `sel_outer_raceway_1_contact`, count `6` |

But that auxiliary patch solve failed before a physical field was available, so it does not count as transfer success.

## Interpretation

The local two-body positive control is important because it uses the same pair naming convention and saved-MPH probe path as the full model:

`cp_roller_1_outer_raceway`

It proves that the pair-specific probe machinery can detect nonzero `roller_1 outer` transfer when the contact state is actually established.

The decisive difference is not simply the radial centroid delta proxy. Both cases still show a large radial-delta proxy and both report `gap = Infinity`. Yet the local two-body model produces nonzero pair-specific `Tn`, while the full-bearing model does not.

Therefore the remaining blocker is more specific:

> in the full-bearing assembly, the `roller_1 outer` source/destination surfaces are present and the destination can show generic traction/stress, but the Contact Pair enforcement does not establish pair-specific transfer on the roller-side source.

This further weakens explanations based on:

- saved-MPH probe variable naming;
- generic COMSOL inability to produce `roller_1 outer` pair-specific `Tn`;
- missing full-bearing destination selection alone;
- radial centroid proxy alone.

The stronger remaining suspects are:

1. source-side local surface topology or normal/parametric state at the `0 deg` seam;
2. full-bearing assembly pair mapping/imprint around the roller-side source surface;
3. contact state initialization in the full multi-body assembly;
4. source/destination local geometry mismatch that is not captured by centroid-only diagnostics.

## Next executable experiment

The next full-bearing experiment should not be another entity-ID scan.

The minimum useful experiment is a construction-time `roller_1 outer` source/destination patch that changes the local surface topology itself:

1. create a retained local source patch on `roller_1` outer surface away from the cylinder seam or with an explicitly controlled seam orientation;
2. create a conformal/curved retained raceway target patch in the same local neighborhood;
3. bind `cp_roller_1_outer_raceway` to those two retained local patches;
4. rerun the `0.101 N` three-roller BoundaryLoad gate;
5. require nonzero pair-specific `Tn` on both roller and destination evaluation contexts, nonzero source/destination stress/displacement, and active rollers `12/1/2` all nonzero.

Until that passes, global 3/6/12 roller BoundaryLoad and cage closure remain blocked from acceptance.

