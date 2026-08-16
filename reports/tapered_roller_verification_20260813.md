# Tapered-roller COMSOL verification (2026-08-13)

## Capability status

- Dedicated typed domain model: implemented.
- Dedicated 3D cone/cup/frustum topology: implemented.
- Inclined inner-rib geometry matching the roller large-end plane: implemented.
- Inner-bore distributed load with selected-area integration: implemented.
- Radial baseline: **verified** by real COMSOL 6.2 solve.
- Contact-angle/raceway-angle variant: **verified** by real COMSOL 6.2 solve.
- Combined radial/axial load without an artificial axial constraint: **experimental; not converged**.
- Angular-contact ball, needle, thrust, and spherical roller builders: not yet verified.

## Verified radial baseline

Artifact directory:
`runtime_smoke/tapered_roller_3_bore_full_4n/`

- Status: `physical_gate_passed`
- Requested force: `[4, 0, 0] N`
- Integrated COMSOL load: `[4.0000001109, 0, 0] N`
- Load error: `2.77e-8`
- Force-balance relative error: `9.03e-6`
- Weak-foundation reaction share: `2.30e-5`
- Maximum displacement: `0.3557 mm`
- Maximum von Mises stress: `1.3515 MPa`
- All inner-raceway, outer-raceway, and rib contact groups transmitted load.
- Saved artifacts: generated code, parameters, topology manifest, solver log,
  machine-readable summary, solved MPH, and COMSOL-native von Mises PNG.

## Verified family-specific variant

Artifact directory:
`runtime_smoke/tapered_roller_3_variant_contact18_4n/`

The contact angle changed from `17.3558 deg` to `18 deg`; inner and outer
raceway angles changed consistently to `23.3558 deg` and `12.6442 deg`.
This changes the roller axes and both raceway cones, not a global scale factor.

- Status: `physical_gate_passed`
- Integrated load error: `2.75e-8`
- Force-balance relative error: `5.46e-6`
- Weak-foundation reaction share: `1.28e-5`
- Maximum displacement: `0.6407 mm`
- Maximum von Mises stress: `2.0860 MPa`

## Important rejected or failed paths

- Flat cylindrical rib: converged but allowed nonphysical axial roller drift;
  replacing it with an inclined conical rib reduced maximum displacement from
  `25.37 mm` to sub-millimetre values.
- Rigid roller connectors: with and without friction, exceeded the bounded
  solve window and were removed from the default generator.
- Hard cage/tangential displacement guides: did not provide a robust solve and
  were removed.
- Weak-foundation stiffness continuation to 1% or 10%: exceeded the bounded
  solve window and was removed.
- True geometric gap without zero-gap contact initialization: failed at the
  first parameter step; the current verified slice uses zero-gap initialization
  and records this limitation.
- Full-inner-bore `10 N` radial case: did not finish inside the bounded window;
  `4 N` is the currently verified baseline.
- `4 N` radial plus `1 N` axial with no inner-ring axial constraint: did not
  finish inside the bounded window. It is retained as failure evidence at
  `runtime_smoke/tapered_roller_3_combined_free_axial_4n1n/` and is not counted
  as verified.
- A frictionless `4 N` radial plus `-0.2 N` axial case was also exported as an
  unsolved MPH and launched through COMSOL batch so that continuation progress
  was externally visible. The solver reached `load_scale=1`, rejected that
  trial, and adaptively bisected back through `0.75`, `0.625`, and values near
  `0.566406`. After `115661 s` (1 day, 8 hours, 7 minutes, 41 seconds), COMSOL
  reported that it could not find solutions for all parameter values even at
  the minimum continuation step: the Solid Mechanics relative step became too
  small and the returned solution was nonconverged. The setup MPH, partially
  solved MPH, recovery file, and 5.3 MB batch log are under
  `runtime_smoke/tapered_roller_3_combined_batch_setup/`; this is retained as
  **failed experimental evidence**, not a passed case.

## Evidence policy

All reported stress, displacement, reaction, applied-force, weak-foundation,
and contact-force values above are solver-derived. No Hertz estimate or copied
historical MPH is accepted as solution evidence. Every verified case starts
from a blank COMSOL model and writes its own generated source and artifacts.

The repository regression suite at this snapshot reports `221 passed, 3
skipped`. The COMSOL runtime artifacts are intentionally excluded by
`.gitignore`; the generator, runner, tests, and this numerical record are the
versioned evidence trail.
