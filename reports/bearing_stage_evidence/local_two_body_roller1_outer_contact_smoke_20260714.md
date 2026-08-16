# Local two-body `roller_1 outer` contact smoke

Date: 2026-07-14

## Purpose

This smoke isolates the contact-probe/tooling question from the full 3D bearing geometry question.

The model contains only:

- one `roller_1` cylinder at the load-side `0 deg` position;
- one outer-ring/raceway body;
- one Contact Pair named exactly like the full bearing path: `cp_roller_1_outer_raceway`;
- source/destination selections named like the full bearing path:
  - `sel_roller_1_outer_contact`
  - `sel_outer_raceway_1_contact`

The goal is not production fidelity. The goal is to verify whether COMSOL and the saved-MPH probe chain can produce nonzero pair-specific `roller_1 outer` contact transfer in a minimal setting.

## New executable path

`scripts/run_agent_3d_bearing_full_demo.py` now supports:

```bash
--run-local-two-body-contact-smoke
```

with optional:

```bash
--local-two-body-contact-output-dir
--local-two-body-contact-model-name
--local-two-body-contact-interference
```

## Commands run

Two setup-debug attempts were kept as failed artifacts:

1. `roller1_outer_interference5um`
   - failed because `useRelaxation` used invalid lowercase value.
2. `roller1_outer_interference5um_rerun`
   - failed because the small model did not accept direct `geomnonlin` study property.

The successful run was:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --run-local-two-body-contact-smoke \
  --local-two-body-contact-output-dir runtime_smoke/bearing_family_p12_local_two_body_contact/roller1_outer_interference5um_rerun2 \
  --local-two-body-contact-model-name bearing3d_local_two_body_roller1_outer_interference5um_rerun2 \
  --local-two-body-contact-interference '5[um]' \
  --cores 1
```

## Artifacts

- Summary: `runtime_smoke/bearing_family_p12_local_two_body_contact/roller1_outer_interference5um_rerun2/local_two_body_contact_summary.json`
- Summary Markdown: `runtime_smoke/bearing_family_p12_local_two_body_contact/roller1_outer_interference5um_rerun2/local_two_body_contact_summary.md`
- Configured MPH: `runtime_smoke/bearing_family_p12_local_two_body_contact/roller1_outer_interference5um_rerun2/local_two_body_contact_configured.mph`
- Solved MPH: `runtime_smoke/bearing_family_p12_local_two_body_contact/roller1_outer_interference5um_rerun2/local_two_body_contact_solved.mph`
- Contact probe JSON: `runtime_smoke/bearing_family_p12_local_two_body_contact/roller1_outer_interference5um_rerun2/contact_probe_solved_mph/contact_probe_summary.json`
- Contact probe Markdown: `runtime_smoke/bearing_family_p12_local_two_body_contact/roller1_outer_interference5um_rerun2/contact_probe_solved_mph/contact_probe_summary.md`

## Result

The local two-body model solved and the saved-MPH contact probe succeeded.

Key probe values:

| Quantity | Value |
|---|---:|
| contact probe success count | 24 |
| contact probe nonzero count | 18 |
| `roller_1` pair-specific nonzero count | 1 |
| `roller_1` pair-specific success count | 3 |
| destination pair-specific `solid.Tn_cp_roller_1_outer_raceway` | `11478.665853398717` |
| destination generic `solid.Tn` | `11478.665853398717` |
| source/destination outer stress response | both nonzero |
| source/destination imbalance flag | false for outer pair |

The `gap_cp_roller_1_outer_raceway` probe still returned `Infinity`, so the strict gap-status gate is not fully satisfied by this local smoke. Still, the important distinction is that pair-specific `Tn` can be nonzero for `roller_1 outer` when the geometry is reduced and controllable.

## Gate status

| Gate | Status |
|---|---|
| Local model setup | Pass |
| Configured MPH saved | Pass |
| COMSOL solve | Pass |
| Solved MPH saved | Pass |
| saved-MPH contact probe | Pass |
| pair-specific `Tn` nonzero | Pass |
| source/destination field response | Pass |
| source/destination imbalance absent | Pass |
| finite/non-infinite gap status | Fail / unresolved |
| reaction/load closure | Not tested |
| global 3-roller BoundaryLoad | Not tested in this smoke |
| production-ready | Fail |
| reaction-verified | Fail |

## Interpretation

This is the strongest positive local control so far:

`roller_1 outer` is not intrinsically unable to produce pair-specific contact transfer in COMSOL, and the saved-MPH probe machinery is capable of detecting it.

Therefore, the full-bearing `roller_1` zero-carry blocker is now more specifically localized to the full-bearing geometry/selection/imprint/contact-closure path around the `0 deg` raceway sector, rather than to:

- pair-specific variable naming;
- saved-MPH probe machinery;
- generic inability of `roller_1 outer` to produce `Tn`;
- source/destination field evaluation in general.

The next minimum global-bearing experiment should transfer this local control back into the full fixture by creating a curved/conformal construction-time `roller_1 outer` raceway patch, not a fixed rectangular block. The acceptance target remains:

1. full-bearing `roller_1 outer` pair-specific `Tn` finite nonzero;
2. source and destination fields both nonzero;
3. active rollers `12/1/2` all nonzero in the 0.101 N BoundaryLoad stage;
4. then reaction/load closure.

