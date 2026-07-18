# BoundaryLoad final-solution saved-MPH probe fix - 2026-07-19

## Scope

This follow-up keeps the solved narrow diagnostic model unchanged and fixes
only saved-MPH BoundaryLoad probe reporting. It does not change contact
geometry, contact settings, active rollers, BoundaryLoad magnitude, weak
guidance, temporary stabilization, or cage scope.

The probed experiment remains:

```text
roller1_outer_retained_conformal_narrow_source_closure3um
```

The unique code variable is the saved-MPH numerical probe parser: COMSOL
returns all parametric solution values for `EvalGlobal` and `IntSurface`, and
the probe now records the raw value array and selects the last value when
`result_index="last"`.

## Modified files

- `scripts/run_agent_3d_bearing_full_demo.py`
- `tests/test_core.py`

## Commands

Targeted static check:

```bash
python3 -m pytest tests/test_core.py -k boundary_load_probe -q
python3 -m compileall -q comsol_agent tests scripts
```

No-solve COMSOL saved-MPH load probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-load-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_20260717_114524_700877/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um.mph \
  --load-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/load_probe_solved_mph_final_solution_globals_20260719
```

Evidence matrix refresh:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --stage-evidence-matrix \
  --stage-evidence-root runtime_smoke \
  --stage-evidence-output-dir reports/bearing_stage_evidence
```

## Inputs held constant

- Solved MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_20260717_114524_700877/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um.mph`
- BoundaryLoad feature: `load_inner_bore`
- BoundaryLoad selection: `sel_inner_bore_load_surface`
- BoundaryLoad expression: `FperArea = [inner_bore_load_pressure, 0, 0]`
- BoundaryLoad target from stage context: `0.101[N]`
- Active rollers: `12, 1, 2`
- Contact pair retained: `cp_roller_1_outer_raceway`
- Geometry diagnostic: retained conformal target, `+3[um]` roller-1 source closure, `0.9[mm]` tangential half-width
- Diagnostic aids still active: weak inner guidance, weak roller foundations, temporary active-roller spring stabilization, cage inactive

## Result

The saved-MPH probe loaded the solved model and completed without re-solving.

| Quantity | Result |
|---|---:|
| Probe success | `true` |
| BoundaryLoad feature exists | `true` |
| BoundaryLoad feature type | `BoundaryLoad` |
| BoundaryLoad selection entity count | `8` |
| Selected area | `4.8631787892e-3[m^2]` |
| Final-step pressure | `44.6518034786[Pa]` |
| Final-step integrated load | `0.2171497036[N]` |
| Applied load target | `0.101[N]` |
| Integrated/target ratio | `2.1499970651` |
| Relative residual to target | `1.1499970651` |
| BoundaryLoad input balance gate | **FAIL** |

The raw parametric arrays are now preserved:

```text
area = [0.004863178789249815, ..., 0.004863178789249815]
pressure = [0.4420970641441537, 2.2104853207207684, 4.420970641441537, 22.104853207207686, 44.20970641441537, 44.43075494648745, 44.65180347855952]
integrated_load = [0.0021499970651354676, 0.010749985325677334, 0.02149997065135467, 0.10749985325677294, 0.21499970651354589, 0.2160747050461151, 0.2171497035786822]
```

The earlier saved-MPH BoundaryLoad report read the first parametric step
(`0.0021499971[N]`). After the parser fix, the final step is used and the
input load still fails the project load-balance gate because the selected
BoundaryLoad area and pressure expression integrate to about `2.15x` the
declared `0.101[N]` target.

## Contact and reaction context

No new contact solve was run. Existing narrow diagnostic evidence still stands:

- Solve closure: pass for the existing COMSOL solve.
- Contact probe execution: pass.
- `roller_1 outer` destination-side pair-specific `Tn` is nonzero.
- Source-side pair-specific `Tn` remains unevaluable in the saved-MPH probe.
- Existing inner-bore reaction candidate: `594.5611858[N]`, balance gate fail.
- Existing support reaction candidate: `294.6119539[N]`, balance gate fail.
- Existing maximum displacement: `1.1883195442[m]`.
- Existing maximum von Mises stress: `1.2494601466e9[Pa]`.

## Evidence matrix after refresh

```text
summary_count=155
row_count=307
production_ready_count=0
reaction_verified_stage_count=0
saved_boundary_load_probe_report_count=7
saved_boundary_load_probe_balanced_count=0
saved_contact_probe_report_count=60
saved_contact_probe_source_unevaluable_destination_nonzero_count=7
```

## Artifacts

- New BoundaryLoad JSON: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/load_probe_solved_mph_final_solution_globals_20260719/load_probe_summary.json`
- New BoundaryLoad Markdown: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/load_probe_solved_mph_final_solution_globals_20260719/load_probe_summary.md`
- Solved MPH: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_20260717_114524_700877/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um.mph`
- PNG: `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/stage_plots/single_solve_3_roller_boundary_load_0p101n_parametric_native_volume.png`
- Evidence matrix JSON: `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.json`
- Evidence matrix Markdown: `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.md`

## Gate decision

| Gate | Verdict |
|---|---|
| Code closure for final-step saved-MPH load probe | **PASS** |
| Solve closure | **UNCHANGED PASS** |
| BoundaryLoad traceability | **PARTIAL: feature traced, balance fails** |
| Contact transfer closure | **FAIL** |
| Reaction/load balance closure | **FAIL** |
| No diagnostic aids | **FAIL** |
| Engineering physical closure | **FAIL** |

Conclusion: this fixes a saved-MPH probe reporting bug, but it does not advance
the model to physical closure. The next physical variable should target the
BoundaryLoad area/load definition mismatch before using reaction closure as a
3-roller acceptance gate.
