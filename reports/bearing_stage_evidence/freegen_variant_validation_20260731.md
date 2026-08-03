# Agent Free-Generated Bearing Variant Validation (2026-07-31)

## Scope

This record preserves the ignored `runtime_smoke/` evidence for strict
Agent-authored 3D bearing generation across parameter and topology variants.
All passing runs used a fresh blank COMSOL model, no MPH input, no verified
fixture fallback, and `require_free_generated_code=true`.

The generated source was DeepSeek/API four-segment bearing code. Runtime
preprocessing was limited to generic Python/MPh API syntax normalization, such
as removing early dataset bindings and stringifying ambiguous string-array
property calls. No bearing geometry, physics, contact topology, or solver model
was reconstructed by a deterministic fixture.

## Passing Cases

| Case | Variant | Load | Key evidence | Artifacts |
|---|---|---:|---|---|
| `STRUCT-C0.4-retry2-formal` | Cage pocket radial clearance `0.4 mm`, zero angular offset, +X load | `10.099982438539563 N` | Load area error `1.57e-6`, applied-load error `1.57e-6`, support-reaction error `1.31e-6`, outer-contact balance error `6.99e-4`, weak-spring ratio `9.51e-7`, loaded-side fraction `1.0` | `runtime_smoke/bearing_variant_struct_c0p4_retry2_freegen_20260730/formal/provenance_manifest.json` |
| `BC-X-OFF15-1N-v6-formal` | Roller/pocket/split-tool angular offset `15 deg`, +X load | `1.0 N` | Load area error `1.57e-6`, applied-load error `1.57e-6`, support-reaction error `1.85e-6`, outer-contact balance error `1.05e-2`, weak-spring ratio `1.08e-5`, loaded-side fraction `1.0` | `runtime_smoke/bearing_variant_bcx_off15_1n_v6_freegen_20260731/formal/provenance_manifest.json` |
| `BC-X-OFF15-10N-v6-formal5` | Roller/pocket/split-tool angular offset `15 deg`, +X load | `10.099982438539563 N` | Load area error `1.57e-6`, applied-load error `1.57e-6`, support-reaction error `1.81e-6`, outer-contact balance error `2.93e-3`, weak-spring ratio `8.14e-6`, loaded-side fraction `1.0` | `runtime_smoke/bearing_variant_bcx_off15_10n_v6_freegen_20260731/formal5/provenance_manifest.json` |

Each passing case exported a native COMSOL `solid.mises` volume PNG from the
final solution dataset and saved a solved MPH under its runtime directory.

## Rejected Cases

| Case | Variant | Failure mode | Artifact |
|---|---|---|---|
| `BC-NX retry2` | Negative X inner-bore load and preload | Generated code passed static gates and blank-model setup, but the force-control solve reached the maximum Newton iterations before a final audited solution. | `runtime_smoke/bearing_variant_bcnx_retry2_freegen_20260730/formal/direct_3d_bearing_summary.json` |
| `BC-Y-OFF15 retry` | Positive Y load with `15 deg` roller/pocket offset | Generated code passed static gates and blank-model setup, but the first solve failed; a corrected forward-schedule retry exceeded the 900 s watchdog. | `runtime_smoke/bearing_variant_bcy_off15_v5e_auxcont_freegen_20260730/formal*/direct_3d_bearing_summary.json` |

## Interpretation

The Agent can now generate and solve more than one bearing instance from a
blank model, including changed cage clearance, changed roller angular phase,
and changed target load magnitude. The evidence does not yet prove robust
directional invariance: +X passes, while -X and +Y still need a more symmetric
load-ramp and contact-initialization policy before they can be treated as stable
production paths.
