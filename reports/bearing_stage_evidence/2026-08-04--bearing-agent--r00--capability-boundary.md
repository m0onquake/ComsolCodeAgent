---
type: results-report
date: 2026-08-04
experiment_line: bearing-agent
round: 0
purpose: capability-boundary
status: active
source_artifacts:
  - reports/bearing_stage_evidence/freegen_variant_validation_20260731.md
  - reports/bearing_stage_evidence/freegen_parametric_family_validation_20260803.md
  - runtime_smoke/bearing_agent_freegen_strict_v24_local_freetet_dim_20260729/formal3_target_10p099982438539563N/direct_3d_bearing_summary.json
  - runtime_smoke/bearing_agent_freegen_strict_v24_local_freetet_dim_20260729/extra_100p999824N/direct_3d_bearing_summary.json
  - runtime_smoke/bearing_variant_bcx_off15_10n_v6_freegen_20260731/formal5/direct_3d_bearing_summary.json
  - runtime_smoke/bearing_variant_param10_dims_freegen_20260803/formal_regen3/direct_3d_bearing_summary.json
  - runtime_smoke/bearing_variant_param14_large_freegen_20260803/formal_regen1/direct_3d_bearing_summary.json
linked_experiments: []
linked_results:
  - reports/bearing_stage_evidence/freegen_variant_validation_20260731.md
  - reports/bearing_stage_evidence/freegen_parametric_family_validation_20260803.md
---

# Bearing Agent / Round 0 / Capability Boundary / 2026-08-04

> `r00` is a temporary roll-up round because the repository does not currently assign a single semantic round number to the July-August validation sequence.

## 1. Executive Summary

The agent is a validated, narrow-domain COMSOL workflow for parametric 3D cylindrical-roller-bearing contact models. It can use segmented LLM generation to create a fresh model, construct rings, cage pockets and rollers, bind audited global contacts, mesh and solve the model, and export machine-readable force audits, a new MPH file, per-roller loads, provenance, and a native COMSOL von Mises PNG.

The strongest supported operating region is positive-X radial loading. Strict end-to-end passes exist for changed 10-, 12-, and 14-roller geometries; the 12-roller baseline also passed at 10.099982 N and 100.999824 N. This is evidence of bounded parametric generalization, not evidence that arbitrary bearing geometry or arbitrary load direction will converge.

The current production boundary is therefore:

- **Supported with strict physical evidence:** fresh-model, free-generated cylindrical roller bearings under `+X` radial load for the validated 10/12/14-roller cases.
- **Supported as generation/setup capability, but not a strict physical pass:** 6- and 8-roller variants; both solved, but missed the 2% outer-contact resultant gate.
- **Unsupported for production claims:** `+Y` and historical `-X` variants, arbitrary bearing families, arbitrary parameter ranges, and results without the full force/provenance audit.

Decision: keep the agent positioned as a strict cylindrical-roller-bearing workflow with an explicit validated envelope. Do not market it as a general COMSOL model generator or direction-invariant bearing solver yet.

## 2. Experiment Identity and Decision Context

This report consolidates the strict free-generation, structure-variation, load-direction, and force-balance experiments completed through 2026-08-04. The decision question is not whether the agent can produce a plausible model or image, but where it can repeatedly produce a new physically audited model without loading an existing MPH or silently replacing generated code with a fixture.

The prior uncertainty was whether the successful 12-roller `+X` model was a single tuned example. The later 10- and 14-roller passes strengthen the claim that roller count and major dimensions are parameterized. The 6/8-roller near-failures and the `+Y/-X` failures show that solver conditioning and force-transfer accuracy are still geometry- and direction-sensitive.

## 3. Setup and Evaluation Protocol

Formal runs use the following contract:

- Start from a new blank COMSOL model; `mph_input=null` and no continuation from an existing MPH.
- Require segmented free-generated code with `require_free_generated_code=true`, `fallback=false`, and `verified_fixture=false`.
- Permit only bounded, recorded COMSOL/Python API normalization; runtime code must not rebuild the main geometry or physics.
- Create inner ring, outer ring, cylindrical rollers, and a Boolean cage with roller pockets and explicit clearances.
- Use two audited global contact searches with distinct inner- and outer-contact roller selections.
- Initialize contact with a small displacement, then inherit solutions through force-continuation chunks.
- Apply the final load on the inner-bore boundary and fix the outer support.
- Audit load area and applied load to 1%, support reaction and roller-contact resultant to 2%, stabilization spring share to 1%, load-zone direction, symmetry when geometrically applicable, and native PNG validity.
- Preserve a watchdog manifest and diagnostic artifacts on timeout or failure.

The physical evidence is deterministic COMSOL acceptance evidence rather than a statistical repeated-seed study. LLM generation can retry rejected segments, so a successful case establishes existence of a conforming generated model, not a measured generation success probability.

## 4. Main Findings

### 4.1 Strictly passed cases

| Case | Geometry/load | Runtime | Support balance error | Outer-contact balance error | Spring/load ratio | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Baseline 12 rollers | `+X`, 10.099982 N | not used for cross-case timing | 0.000131% | 0.069985% | 0.000095% | Pass |
| Baseline 12 rollers, high load | `+X`, 100.999824 N | not used for cross-case timing | 0.000510% | 0.437582% | 0.000799% | Pass |
| 12 rollers, 15° phase offset | `+X`, 10.099982 N | 334.65 s | 0.000181% | 0.293206% | 0.000814% | Pass |
| Parametric 10 rollers | 45/90 mm ID/OD, 7.5 × 17 mm rollers, 7.5° offset, `+X`, 1 N | 654.07 s | 0.000949% | 0.200522% | 0.001140% | Pass |
| Parametric 14 rollers | 55/105 mm ID/OD, 6 × 19 mm rollers, 12.857° offset, `+X`, 1 N | 1169.33 s | 0.000345% | 0.704776% | 0.000487% | Pass |

These cases demonstrate that the validated implementation is not tied to exactly 12 rollers, one angular phase, or one diameter set. They do not define safe interpolation or extrapolation bounds between those points.

### 4.2 Agent capabilities supported by code and evidence

1. **Constrained free generation:** decomposes a full model into geometry, cage/rollers, selections/physics, and mesh/study/result segments; rejects nonconforming code before spending COMSOL runtime.
2. **Parametric cylindrical-bearing construction:** parameterizes roller count, bore and outer diameters, width, roller diameter/length, pitch and raceway radii, cage clearance, roller phase, radial-load axis/sign, and target load.
3. **COMSOL API hardening:** detects or normalizes known invalid pair, material, mesh, result, and array-property patterns while recording every change.
4. **Physical contact topology:** uses separate inner/outer roller contact selections and two global Contact Pairs; prevents per-roller pairs from repeatedly binding the same continuous raceway.
5. **Nonlinear solve orchestration:** performs displacement initialization, inherited native auxiliary continuation, chunked force ramps, and process-group watchdog termination.
6. **Strict validation:** checks geometry/selection completeness, pair endpoints, load area, support reaction, per-roller loads, aggregate roller force, spring leakage, load-zone direction, conditional symmetry, and final-dataset selection.
7. **Auditable delivery:** emits a new MPH, native COMSOL PNG, JSON summary, provenance manifest, watchdog manifest, and roller-load CSV.

## 5. Statistical Validation

No inferential statistical test is appropriate for the current evidence bundle: each listed case is one deterministic nonlinear solve after an LLM-generated candidate passes static gates. Claims are therefore limited to case-level acceptance.

Confidence is highest where independent gates agree: applied load, support reaction, roller resultant, spring leakage, loaded zone, and the final native plot all pass on the same saved solution. Confidence is lower for general generation reliability because retry counts and repeated independent generations have not been aggregated into a success-rate study.

The core non-COMSOL regression suite passes: `202 passed, 1 skipped` using `python3 -m pytest tests/test_core.py -q` on 2026-08-04. The project `.venv` does not currently contain `pytest`; the repository's system-Python test path was used.

## 6. Figure-by-Figure Interpretation

### 6.1 Baseline 12-roller, 10.099982 N native stress plot

Artifact: `runtime_smoke/bearing_agent_freegen_strict_v24_local_freetet_dim_20260729/formal3_target_10p099982438539563N/target_10p099982438539563N_native_volume.png`

Why shown: this is the first full strict acceptance reference. The image is useful only together with the force audit; its existence alone is not proof of physical validity.

Supported interpretation: the plotted stress field comes from the fresh model's final target solution, whose load, support reaction, per-roller resultant, spring leakage, and symmetry gates passed.

### 6.2 Phase-offset 12-roller, 10.099982 N native stress plot

Artifact: `runtime_smoke/bearing_variant_bcx_off15_10n_v6_freegen_20260731/formal5/target_10p099982438539563N_native_volume.png`

Why shown: this case changes roller phase while retaining the design load. It also exposed and fixed a result-selection bug where a plot could show the first 1 N point rather than the final 10.099982 N point.

Supported interpretation: the corrected plot explicitly selects the second solution of the high-load chunk and displays `radial_load(2)=10.1 N`. This validates the export path, not just the mechanical solve.

### 6.3 Parametric 10- and 14-roller native stress plots

Artifacts:

- `runtime_smoke/bearing_variant_param10_dims_freegen_20260803/formal_regen3/target_1p0N_native_volume.png`
- `runtime_smoke/bearing_variant_param14_large_freegen_20260803/formal_regen1/target_1p0N_native_volume.png`

Why shown: these are the strongest evidence that the workflow can move beyond the original 12-roller geometry.

Supported interpretation: both plots belong to fresh, changed-dimension models whose full strict audits passed. They support bounded structural generalization, but no mesh-convergence or experimental stress validation has been performed.

## 7. Failure Cases / Negative Results / Limitations

| Boundary | Evidence | Current interpretation |
| --- | --- | --- |
| 6 rollers, `+X`, 1 N | Solve and most gates passed; outer-contact error was 3.1611% against a 2% limit. | Geometry/setup capability exists, but force-transfer accuracy is not yet production-passing. |
| 8 rollers, `+X`, 1 N, 10° offset | Solve passed; outer-contact error was 2.10684%. The stored artifact also applied an exact-mirror gate that later became inapplicable for this offset. | Near-pass, not a formal pass. Must rerun after the latest audit/schedule changes. |
| 8 rollers, `+Y`, 1 N | Setup, selections, and initialization passed; force continuation ended with a COMSOL `NullPointerException` and 900 s timeout. | Direction-rotated nonlinear continuation remains unstable. |
| 9 rollers, `+Y`, 1 N | Initialization passed; force continuation failed with the same COMSOL exception and timed out around 920 s. | Failure is not specific to one roller count. |
| Historical `-X` cases | Maximum Newton iterations/contact handoff failures. | Load sign is parameterized in code but not physically validated as direction-invariant. |

Additional limits:

- The validated domain is 3D cylindrical roller bearings. Ball, tapered, spherical, needle, thrust, misaligned, damaged, lubricated, thermal, transient, fatigue, or multiphysics bearings are not validated.
- Cage contact is intentionally disabled in the strict accepted topology; the cage is geometrically audited and stabilized rather than included as a fully interacting body.
- The workflow uses a specific contact/solver strategy and empirical continuation schedules. It is not a proof that every geometrically valid parameter combination will converge.
- Material/contact assumptions are engineering-model assumptions, not calibrated test data. Stress magnitude has not been validated against experiment or an independent solver.
- No systematic mesh-convergence, discretization-error, sensitivity, uncertainty, repeated-generation reliability, or hardware/runtime benchmark study has been completed.
- Free generation still depends on a configured LLM service and may need segment retries. COMSOL, a valid license, the expected Java/MPh runtime, and sufficient wall time are external prerequisites.
- Runtime normalization is bounded and logged, but a strict pass should always inspect provenance rather than infer autonomy from the final MPH alone.
- Runtime artifacts under `runtime_smoke/` may be local/large and are not a substitute for durable repository documentation.

## 8. What Changed Our Belief

- **Strengthened:** the agent can generate and solve more than the original 12-roller fixture. Independent 10- and 14-roller changed-dimension strict passes support real parameterization.
- **Strengthened:** a visually plausible PNG is insufficient; explicit final-solution selection and force closure are necessary and now enforced.
- **Weakened:** changing load axis or sign is not merely a syntactic parameter change. Contact-set handoff and nonlinear conditioning make direction a first-class solver variable.
- **Unresolved:** whether the 6/8-roller residuals are primarily integration/mesh error, contact leakage, or continuation-path error.
- **Unresolved:** generation success probability across repeated independent LLM samples and wider geometry distributions.

## 9. Next Actions

1. Rerun 6- and 8-roller `+X` cases with the new small-roller continuation chunks and corrected offset-aware symmetry rule; do not relax the 2% force gate before diagnosing the residual.
2. Isolate the `+Y/-X` COMSOL force-stage failure with checkpoint-level solver diagnostics and direction-aware initialization/continuation, then require at least two distinct roller counts to pass before claiming directional generalization.
3. Add a compact machine-readable capability matrix so CI/reporting can distinguish `generated`, `setup passed`, `solved`, and `strictly accepted` states.
4. Add repeated-generation trials and report retry/success rates separately from physical solve success.
5. Add mesh-convergence and independent reference comparisons before promoting stress magnitudes into scientific or design claims.
6. Keep the accepted `+X` cases as regression fixtures for audit behavior, but retain the rule that formal free-generation acceptance starts from a blank model and cannot fall back to those fixtures.

## 10. Artifact and Reproducibility Index

### Primary reports

- `reports/bearing_stage_evidence/freegen_variant_validation_20260731.md`
- `reports/bearing_stage_evidence/freegen_parametric_family_validation_20260803.md`

### Passed strict summaries

- `runtime_smoke/bearing_agent_freegen_strict_v24_local_freetet_dim_20260729/formal3_target_10p099982438539563N/direct_3d_bearing_summary.json`
- `runtime_smoke/bearing_agent_freegen_strict_v24_local_freetet_dim_20260729/extra_100p999824N/direct_3d_bearing_summary.json`
- `runtime_smoke/bearing_variant_bcx_off15_10n_v6_freegen_20260731/formal5/direct_3d_bearing_summary.json`
- `runtime_smoke/bearing_variant_param10_dims_freegen_20260803/formal_regen3/direct_3d_bearing_summary.json`
- `runtime_smoke/bearing_variant_param14_large_freegen_20260803/formal_regen1/direct_3d_bearing_summary.json`

### Negative/near-pass summaries

- `runtime_smoke/bearing_variant_param6_compact_freegen_20260803/formal_regen1/direct_3d_bearing_summary.json`
- `runtime_smoke/bearing_variant_param8_x_1n_freegen_20260803/formal_regen1/direct_3d_bearing_summary.json`
- `runtime_smoke/bearing_variant_param8_y_1n_freegen_20260803/formal_regen4/direct_3d_bearing_summary.json`
- `runtime_smoke/bearing_variant_param9_y_freegen_20260803/formal/direct_3d_bearing_summary.json`

### Main implementation and tests

- `comsol_agent/simulation/bearing_3d.py`
- `scripts/run_agent_3d_bearing_full_demo.py`
- `scripts/run_strict_bearing_watchdog.py`
- `tests/test_core.py`

No Obsidian write-back was attempted because this repository is not bound to an Obsidian project knowledge base.
