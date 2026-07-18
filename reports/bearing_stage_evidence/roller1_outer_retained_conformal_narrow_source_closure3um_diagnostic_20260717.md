# Roller 1 retained conformal narrow source-closure diagnostic - 2026-07-17

## Scope

This is the requested one-variable diagnostic experiment:

```text
roller1_outer_retained_conformal_narrow_source_closure3um
```

The fixture reuses the retained conformal roller-1 outer target and the
successful `+3[um]` roller-1 source closure. The only geometry variable changed
relative to `roller1_outer_retained_conformal_source_closure3um` is the
roller-1 outer contact-box tangential half-width:

```text
1.8[mm] -> 0.9[mm]
```

The following were held fixed:

- Contact pair: `cp_roller_1_outer_raceway`
- Boundary load: `0.101[N]`
- Active rollers: `12, 1, 2`
- Contact settings and relaxation policy
- Weak guidance
- Temporary active-roller spring stabilization
- Cage-inactive stage scope

This is diagnostic evidence only. It is not a production-ready physical
closure.

## Code and static verification

Modified files:

- `scripts/run_agent_3d_bearing_full_demo.py`
- `tests/test_core.py`

The new mode has an explicit CLI choice, fixture marker, diagnostic role, and
regression assertions. Generated code confirms:

- retained conformal target is present;
- `ROLLER1_OUTER_SOURCE_CLOSURE` is present;
- source is `sel_roller_1_outer_contact`;
- destination is `sel_outer_raceway_1_contact`;
- pair is `cp_roller_1_outer_raceway`;
- `outer_box_tangential_half_width=0.9[mm]`;
- `BoundaryLoad` remains bound to `sel_inner_bore_load_surface`.

Static commands:

```bash
python3 -m pytest tests/test_core.py -q
python3 -m compileall -q comsol_agent tests scripts
git diff --check
```

Result before the COMSOL run:

```text
184 passed, 1 skipped
compileall: passed
git diff --check: passed
```

## COMSOL commands

Real fixture solve:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --direct-fixture-run \
  --use-verified-fixture \
  --verified-fixture-local-contact-patch-mode roller1_outer_retained_conformal_narrow_source_closure3um \
  --contact-stage-mode load_side_group_boundary_load_single_solve_0p101 \
  --artifact-root runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um \
  --model-name bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um \
  --cores 1
```

Saved-MPH contact probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph \
  runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_20260717_114524_700877/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um.mph \
  --contact-probe-output-dir \
  runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/contact_probe_solved_mph \
  --cores 1
```

Saved-MPH source-entity transfer probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-contact-mph \
  runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_20260717_114524_700877/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um.mph \
  --probe-contact-entity-transfer \
  --contact-entity-transfer-selection sel_roller_1_outer_contact \
  --contact-entity-transfer-roller 1 \
  --contact-probe-output-dir \
  runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/source_entity_transfer_probe_solved_mph \
  --cores 1
```

Saved-MPH reaction probe:

```bash
.venv/bin/python scripts/run_agent_3d_bearing_full_demo.py \
  --probe-reaction-mph \
  runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_20260717_114524_700877/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um.mph \
  --reaction-probe-selection sel_inner_bore_load_surface \
  --reaction-probe-output-dir \
  runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/reaction_probe_solved_mph \
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

### Solve and PNG

| Quantity | Result |
|---|---:|
| Template run | `true` |
| Staged solve | `true` |
| BoundaryLoad active | `true` |
| Input load | `0.101[N]` |
| Active rollers | `12, 1, 2` |
| Native stage PNG generated | `true` |
| Physical plausibility gate | `false` |
| Maximum von Mises stress | `1.2494601466e9[Pa]` |
| Maximum displacement | `1.1883195442[m]` |
| Active roller stress probe coverage | `3/3` |
| Active roller stress min/max ratio | approximately `0.0003194` |

Active roller maximum von Mises probes:

| Roller | Maximum von Mises |
|---|---:|
| `roller_1` | `1.2605952849e9[Pa]` |
| `roller_2` | `4.0263507088e5[Pa]` |
| `roller_12` | `4.5410257891e5[Pa]` |

The generated stress PNG is retained as evidence, but the requested stage
image was not accepted as bearing stress evidence because the physical
plausibility gate failed.

### Saved-MPH contact probe

| Quantity | Result |
|---|---:|
| Probe success | `true` |
| Candidate count | `972` |
| Successful probes | `144` |
| Nonzero probes | `104` |
| Source/destination imbalance rollers | none |
| Source unevaluable / destination nonzero rollers | `roller_1`, `roller_12`, `roller_2` |
| Zero pair-specific pressure rollers | none |

Pair-specific status:

| Roller | Pair-specific success | Pair-specific nonzero | Outer destination `Tn` |
|---|---:|---:|---:|
| `roller_1` | `6/6` | `2/6` | `5.2859685862e8` |
| `roller_2` | `6/6` | `1/6` | `2.0766230023e4` |
| `roller_12` | `6/6` | `1/6` | `2.1289639671e4` |

For `roller_1` outer contact:

- Source selection: `sel_roller_1_outer_contact`, `2` entities.
- Destination selection: `sel_outer_raceway_1_contact`, `6` entities.
- Destination pair-specific `Tn`: nonzero.
- Source pair-specific `Tn`: `selection_error`.
- Pair-specific `gap`: `Infinity` on the probed source/destination fields.
- Pair-specific `pn`/`gn`: mostly `selection_error`.
- Source/destination imbalance diagnostic: `false`.
- Pair-transfer source unevaluable / destination nonzero diagnostic: `true`.
- Source-entity transfer probe: source entities `197` and `198` have nonzero
  generic pressure/stress, but `solid.Tn_cp_roller_1_outer_raceway` evaluates
  with `evaluation_error` on both entities. The added `src`/`dst` alias
  candidates also return `evaluation_error`, so the source-side limitation is
  not just a naming suffix mismatch.

Thus, the narrow box preserves a nonzero destination-side transfer signal and
does not introduce the previously observed source/destination imbalance, but it
does not establish complete pair closure or finite contact-gap/pressure
evidence. The saved-MPH pair-transfer probe still cannot evaluate source-side
pair-specific `Tn` while destination-side `Tn` is nonzero.

### Saved-MPH reaction and load balance

The saved-MPH reaction tool returned a nonzero candidate, but the current
reaction gate separates `reaction_candidate_nonzero` from
`reaction_verified`. Because the candidate does not balance the traced
`0.101[N]` BoundaryLoad, `reaction_verified=false`:

| Quantity | Result |
|---|---:|
| Applied BoundaryLoad | `0.101[N]` |
| Best nonzero reaction candidate | `594.5611858[N]` |
| Absolute residual | `594.4601858[N]` |
| Reaction/load ratio | `5886.7444` |
| Relative residual to applied load | `5885.7444` |
| Reaction candidate nonzero | `true` |
| Reaction verified | `false` |
| Balance gate | **FAIL** |

The nonzero reaction candidate is
`solid.sx*nx+solid.sxy*ny+solid.sxz*nz` evaluated by the saved-MPH
`java_intsurface` method. It is evidence that a nonzero surface traction
integral can be evaluated, not evidence that the specified `0.101[N]`
BoundaryLoad is balanced.

The refreshed matrix remains:

```text
reaction_verified_stage_count=0
production_ready_count=0
```

## Diagnostic aids still active

The solved stage retains all of the following:

- temporary active-roller stabilization;
- weak roller foundation;
- weak inner-ring guidance;
- cage-inactive scope and temporary cage stabilization flag.

Consequently this run cannot pass the requested physical acceptance gates even
though the COMSOL solve, contact probe, and PNG generation succeeded.

## Artifacts

- Summary JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/direct_3d_bearing_summary.json`
- Configured MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/stage_models/single_solve_3_roller_boundary_load_0p101n_parametric_configured.mph`
- Solved MPH:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/result_packages/direct_3d_bearing_package_bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um_20260717_114524_700877/bearing3d_load_side_boundaryload_0p101_roller1_outer_retained_conformal_narrow_source_closure3um.mph`
- Native stage PNG:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/stage_plots/single_solve_3_roller_boundary_load_0p101n_parametric_native_volume.png`
- Stress PNG:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/bearing_3d_von_mises.png`
- Contact probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/contact_probe_solved_mph/contact_probe_summary.json`
- Contact probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/contact_probe_solved_mph/contact_probe_summary.md`
- Source-entity transfer probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/source_entity_transfer_probe_solved_mph/contact_probe_summary.json`
- Source-entity transfer probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/source_entity_transfer_probe_solved_mph/contact_probe_summary.md`
- Reaction probe JSON:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/reaction_probe_solved_mph/reaction_probe_summary.json`
- Reaction probe Markdown:
  `runtime_smoke/bearing_family_p12_boundaryload_roller1_outer_retained_conformal_narrow_source_closure3um/reaction_probe_solved_mph/reaction_probe_summary.md`
- Evidence matrix JSON:
  `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.json`
- Evidence matrix Markdown:
  `reports/bearing_stage_evidence/bearing_stage_evidence_matrix.md`

## Verdict

| Gate | Verdict |
|---|---|
| Code mode and single-variable geometry change | **PASS** |
| COMSOL solve | **PASS** |
| BoundaryLoad traceability | **PASS** |
| Contact probe execution | **PASS** |
| Nonzero roller/raceway transfer signal | **PASS, diagnostic only** |
| Complete pair-specific `Tn/gap/pn` closure | **FAIL** |
| External load versus reaction balance | **FAIL** |
| No temporary stabilization/guidance | **FAIL** |
| Reaction-verified stage gate | **FAIL** |
| Production-ready gate | **FAIL** |

This experiment does not justify advancing to a physical 3-roller closure,
6-roller expansion, 12-roller expansion, or cage restoration. It records a
reproducible narrow-box diagnostic and leaves the project explicitly below
both the reaction-verified and production-ready gates.
