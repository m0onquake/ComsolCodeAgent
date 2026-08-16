# Parameterized two-body angle-control smoke

Date: 2026-07-15

## Purpose

After the `roller_1 outer` two-body positive control succeeded, the local smoke runner was parameterized by `roller_id` so that `roller_2` and `roller_12` can be tested with the same minimal two-body strategy.

This is not a production model. It is an angle/control diagnostic before attempting a full-fixture construction-time patch.

## Code update

`scripts/run_agent_3d_bearing_full_demo.py` now supports:

```bash
--run-local-two-body-contact-smoke
--local-two-body-contact-roller-id <1..12>
```

The local model now computes the roller center, radial load direction, and local patch box from the roller angle. Default behavior remains `roller_id=1`.

## Commands run

`roller_2`:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --run-local-two-body-contact-smoke \
  --local-two-body-contact-roller-id 2 \
  --local-two-body-contact-output-dir runtime_smoke/bearing_family_p12_local_two_body_contact/roller2_outer_interference5um \
  --local-two-body-contact-model-name bearing3d_local_two_body_roller2_outer_interference5um \
  --local-two-body-contact-interference '5[um]' \
  --cores 1
```

`roller_12`:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --run-local-two-body-contact-smoke \
  --local-two-body-contact-roller-id 12 \
  --local-two-body-contact-output-dir runtime_smoke/bearing_family_p12_local_two_body_contact/roller12_outer_interference5um \
  --local-two-body-contact-model-name bearing3d_local_two_body_roller12_outer_interference5um \
  --local-two-body-contact-interference '5[um]' \
  --cores 1
```

## Results

| Case | Result | Artifacts |
|---|---|---|
| `roller_1` previous two-body positive control | solved; pair-specific transfer verified | `runtime_smoke/bearing_family_p12_local_two_body_contact/roller1_outer_interference5um_rerun2/` |
| `roller_2` parameterized two-body | solve failed: no converged stationary solution | `runtime_smoke/bearing_family_p12_local_two_body_contact/roller2_outer_interference5um/` |
| `roller_12` parameterized two-body | solve hung/was interrupted after configured MPH was saved | `runtime_smoke/bearing_family_p12_local_two_body_contact/roller12_outer_interference5um/` |

`roller_2` error:

```text
找不到解。
在 固体力学:
不收敛，相对步长太小。
返回的解不收敛。
没有返回所有参数步长。
```

`roller_12` was interrupted after only:

```text
local_two_body_contact_configured.mph
```

was saved.

## Interpretation

This is useful negative evidence. The minimal two-body strategy is not automatically angle-robust. The original `roller_1` two-body positive control still proves that pair-specific `Tn` can be detected for `roller_1 outer`, but the simplified support/load/patch construction is not a general homologous roller benchmark.

Therefore, it should not be copied directly into the full-bearing patch design.

The next full-fixture repair should keep the lesson from the positive control:

- pair-specific transfer is measurable when contact is actually established;
- source and destination both need field response;
- generic destination traction alone is insufficient.

But the geometry repair should be done in the full fixture with retained local source/destination patches, not by transplanting this minimal two-body support scheme.

## Gate status

| Gate | Status |
|---|---|
| parameterized local two-body CLI | implemented |
| static tests | pass |
| `roller_1` local two-body positive control | pass |
| `roller_2` parameterized local two-body | fail |
| `roller_12` parameterized local two-body | interrupted/no solved field |
| global 3-roller BoundaryLoad | not advanced |
| production-ready | fail |
| reaction-verified | fail |

