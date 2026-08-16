# Roller 1 retained conformal narrow source-closure actual-area load diagnostic - 2026-07-18

## Scope

This is a follow-up single-variable diagnostic after the narrow retained
conformal `+3[um]` source-closure run showed that the traced `0.101[N]`
BoundaryLoad integrated to only `2.1499970651e-3[N]` on the saved MPH.

The new mode is:

```text
load_side_group_boundary_load_single_solve_0p101_actual_area_load
```

It reuses:

- Local contact patch mode:
  `roller1_outer_retained_conformal_narrow_source_closure3um`
- Retained conformal roller-1 outer target
- Roller-1 `+3[um]` source closure
- Roller-1 outer tangential contact-box half-width: `0.9[mm]`
- Contact pair: `cp_roller_1_outer_raceway`
- BoundaryLoad target: `0.101[N]`
- Active rollers: `12, 1, 2`
- Contact penalty, relaxation, tolerance, weak guidance, temporary active-roller
  spring stabilization, and cage-inactive scope

The only intended variable is the BoundaryLoad pressure normalization:

```text
inner_bore_load_pressure:
  radial_load/(pi*inner_diameter*bearing_width)
  -> radial_load/(4.863178789249815e-3[m^2])
```

The denominator is the actual `sel_inner_bore_load_surface` area measured by
the previous saved-MPH BoundaryLoad probe.

This is diagnostic evidence only. It is not a production-ready physical
closure.

## Code and static verification

Modified files:

- `scripts/run_agent_3d_bearing_full_demo.py`
- `tests/test_core.py`
- `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.json`
- `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.md`
- `reports/bearing_stage_evidence/roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_load_diagnostic_20260718.md`

Static commands before the COMSOL run:

```bash
python3 -m pytest tests/test_core.py -k "staged_contact or boundary_load_probe_reports" -q
python3 -m compileall -q comsol_agent tests scripts
python3 -m pytest tests/test_core.py -q
```

Results:

```text
2 passed, 186 deselected
compileall: passed
187 passed, 1 skipped
```

## COMSOL commands

Real fixture solve:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_narrow_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101_actual_area_load \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_load \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_load \
  --cores 1
```

Failed-MPH no-solve diagnostic:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --diagnose-stage-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_load/failed_3d_contact_model.mph \
  --diagnose-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_load/diagnostics_failed_mph \
  --cores 1
```

Failed-MPH BoundaryLoad input probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-load-mph runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_load/failed_3d_contact_model.mph \
  --load-probe-selection sel_inner_bore_load_surface \
  --load-probe-pressure-expression inner_bore_load_pressure \
  --load-probe-output-dir runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_load/load_probe_failed_mph \
  --cores 1
```

Evidence matrix refresh:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --stage-evidence-matrix \
  --stage-evidence-root runtime_smoke \
  --stage-evidence-output-dir reports/bearing_stage_evidence
```

## Results

### Solve

| Quantity | Result |
|---|---:|
| Template run | `true` |
| Stage setup | `true` |
| Pre-solve configured MPH | `true` |
| Staged solve | `false` |
| Native stage PNG generated | `false` |
| Solved result package | `none` |
| Failed MPH saved | `true` |
| Physical plausibility gate | `false` |
| Maximum von Mises stress | `null` |
| Maximum displacement | `null` |
| Active roller stress probe coverage | `0/3` |

Solver error:

```text
The stationary solver could not find an initial-parameter solution. Solid
Mechanics did not converge because the relative step size became too small, and
not all parameter steps returned a solution.
```

### BoundaryLoad input probe on failed MPH

| Quantity | Result |
|---|---:|
| Selection | `sel_inner_bore_load_surface` |
| Selection entities | `135, 136, 139, 140, 141, 142, 143, 144` |
| Feature type | `BoundaryLoad` |
| Feature active | `true` |
| `FperArea` | `["inner_bore_load_pressure", "0", "0"]` |
| Parameter expression | `radial_load/(4.863178789249815e-3[m^2])` |
| Area | `4.8631787892e-3[m^2]` |
| Integrated load in failed MPH | `1.0000000000e-3[N]` |
| Target stage load | `0.101[N]` |
| Integrated-to-target ratio | `0.0099009901` |
| Load balance gate | **FAIL** |

The failed MPH is stopped at the initial parametric load value, so the probe
confirms that actual-area pressure normalization was applied, but it does not
verify the final `0.101[N]` load. This stage failed before a solved saved-MPH
contact or reaction probe could be validly run.

### Contact and reaction probes

| Probe | Result |
|---|---|
| Saved-MPH contact probe | Not run; no converged solved MPH was produced. |
| Pair-specific `Tn/gap/source/destination` | Not evaluable for this failed solve. |
| Saved-MPH reaction probe | Not run; no converged solved MPH was produced. |
| External load versus reaction balance | **FAIL**, missing solved reaction evidence. |

### Diagnostic aids still active

The failed stage still used:

- temporary active-roller spring stabilization;
- weak roller foundation;
- weak inner-ring guidance;
- cage-inactive scope and temporary cage stabilization.

Therefore it cannot pass the requested production or engineering physical
acceptance gates even if a future variant converges.

## Artifacts

- Summary JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_load/direct_3d_bearing_summary.json`
- Configured MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_load/stage_models/single_solve_3_roller_boundary_load_0p101n_actual_area_load_configured.mph`
- Failed MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_load/failed_3d_contact_model.mph`
- No-solve diagnostic JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_load/diagnostics_failed_mph/stage_mph_diagnostic.json`
- No-solve diagnostic Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_load/diagnostics_failed_mph/stage_mph_diagnostic.md`
- BoundaryLoad probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_load/load_probe_failed_mph/load_probe_summary.json`
- BoundaryLoad probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um_actual_area_load/load_probe_failed_mph/load_probe_summary.md`
- Evidence matrix JSON:
  `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.json`
- Evidence matrix Markdown:
  `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.md`

## Verdict

| Gate | Verdict |
|---|---|
| Code mode and single-variable load-normalization change | **PASS** |
| COMSOL solve | **FAIL** |
| BoundaryLoad traceability | **PARTIAL**, configuration verified; final `0.101[N]` saved-MPH load not solved |
| Contact probe execution | **FAIL**, no converged solved MPH |
| Complete pair-specific `Tn/gap/pn` closure | **FAIL** |
| External load versus reaction balance | **FAIL** |
| No temporary stabilization/guidance | **FAIL** |
| Reaction-verified stage gate | **FAIL** |
| Production-ready gate | **FAIL** |

This experiment shows that correcting the BoundaryLoad pressure to the audited
selection area makes the previous diagnostic setup fail at the initial
parametric step. The next one-variable experiment should keep this actual-area
load normalization and adjust only the load ramp/bootstrap strategy, because
the contact transfer and reaction balance gates cannot be evaluated until a
converged solved MPH exists.
