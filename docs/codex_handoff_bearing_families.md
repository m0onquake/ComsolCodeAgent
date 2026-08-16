# Codex handoff: multi-family bearing COMSOL development

## Repository state

- Repository: `git@github.com:m0onquake/ComsolCodeAgent.git`
- Development branch: `codex/bearing-family-automation-p12`
- Python requirement: `>=3.11`; Python 3.12 or 3.13 is recommended.
- Verified COMSOL runtime: COMSOL Multiphysics 6.2 with Structural Mechanics.
- Install development and Web dependencies with `pip install -e '.[dev,web]'`.

Do not copy `~/.comsol_agent/config.yaml` from another machine because it may
contain credentials. Configure `COMSOL_EXECUTABLE`, `COMSOL_VERSION`, and the
selected LLM provider's API key as environment variables on the destination.

## Proven current capability

- Typed common and family-specific parameters exist for tapered roller,
  angular-contact ball, needle roller, thrust, and spherical roller bearings.
- Unit normalization, provenance, required-parameter checks, and geometric
  feasibility validation are implemented.
- `TaperedRollerComsolBuilder` is the only complete new-family COMSOL builder.
- The three-roller `4 N` radial baseline passed real COMSOL physical gates:
  load error `2.77e-8`, equilibrium error `9.03e-6`, and weak-spring share
  `2.30e-5`.
- A real contact-angle/raceway-angle variant also passed: load error `2.75e-8`,
  equilibrium error `5.46e-6`, and weak-spring share `1.28e-5`.
- Both passed cases started from blank models and saved generated code,
  parameter manifests, logs, solved MPH files, native plots, and summaries.
- The repository regression snapshot passed `221` tests with `3` skipped;
  `tests/test_bearing_domain.py` contains 14 focused domain/builder tests.

Read `reports/tapered_roller_verification_20260813.md` before making claims
about solver verification.

## Known failure that must remain visible

The frictionless combined case with `4 N` radial and `-0.2 N` axial load did
not converge. COMSOL batch ran for `115661 s`, attempted `load_scale=1`, then
adaptively bisected back to about `0.566406` before reporting that the relative
step was too small. Do not mark combined loading as verified and do not replace
this result with an estimate.

The ignored evidence directory is:

```text
runtime_smoke/tapered_roller_3_combined_batch_setup/
```

It must be copied separately if the destination needs the 5.3 MB log and
partially solved 42 MB MPH. The two passed case directories are also ignored by
Git and must be copied separately:

```text
runtime_smoke/tapered_roller_3_bore_full_4n/
runtime_smoke/tapered_roller_3_variant_contact18_4n/
```

## Next engineering work

1. Diagnose the tapered combined-load failure from the batch log and saved MPH.
   Preserve force direction, remove no physical support, and keep the final
   weak-spring reaction share below 1%.
2. Implement an independent `AngularContactBallComsolBuilder`; validate a
   baseline, a contact-angle or preload variant, and a combined/direction case.
3. Repeat with independent builders for needle, thrust, and spherical roller
   families. Never substitute cylindrical-roller or deep-groove-ball topology.
4. Integrate builders into the natural-language Agent path and Web status UI.
5. Run the complete regression suite and real COMSOL physical audits before
   changing any family status from `planner-only` or `experimental` to
   `verified`.

Preserve unrelated working-tree changes and do not commit generated media or
runtime artifacts unless explicitly requested.

## Destination setup

```bash
git clone git@github.com:m0onquake/ComsolCodeAgent.git
cd ComsolCodeAgent
git switch codex/bearing-family-automation-p12
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev,web]'
python -m pytest -q
codex
```

After Codex opens in the repository, paste:

```text
/goal Continue the multi-family bearing COMSOL development described in
docs/codex_handoff_bearing_families.md. Treat the repository and copied
runtime_smoke artifacts as authoritative. First verify the current branch,
tests, COMSOL 6.2 connection, and the final combined-load batch failure. Then
continue the full original scope without redefining completion: repair and
physically verify tapered combined loading, implement independent angular-
contact ball, needle, thrust, and spherical roller COMSOL builders, run real
baseline/variant/load-direction cases with physical audits, integrate the Agent
and Web UI, preserve unrelated changes, and only mark a family verified when
solver-derived evidence and saved MPH/native plots prove every gate.
```
