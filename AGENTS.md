# COMSOL Agent Repository Guidance

## Scope

These instructions apply to the entire repository. The V2 architecture under `docs/v2/` is the design source of truth for new Agent architecture work.

## Required reading

Before changing V2 architecture or implementation, read:

1. `docs/v2/ARCHITECTURE.md`
2. The subsystem document relevant to the task
3. `docs/v2/TEST_AND_ACCEPTANCE.md`
4. `docs/v2/ROADMAP.md`

For a long-running milestone, also read `docs/v2/GOAL_PLAYBOOK.md` and the applicable ADRs under `docs/v2/adr/`.

## Architecture invariants

- Keep the Agent Kernel domain-neutral. Bearing families, COMSOL error strings, repair cases, and solver recipes must enter through extensions or typed domain services.
- Prefer typed contracts and registries over large conditional dispatch chains.
- Treat Function tools, MCP tools, Skills, Hooks, repair rules, deterministic paths, validators, builders, auditors, and memory adapters as separate extension kinds with explicit responsibilities.
- A Skill describes a workflow; it does not grant authority. An MCP server or Function performs controlled actions. Hooks enforce lifecycle policy. RAG supplies context, not truth.
- Use the smallest safe change path: parameter patch, deterministic builder, or scoped generated patch. Do not regenerate an entire model for a parameter-only change.
- COMSOL execution and physical audit are the source of truth. Static validation and retrieved examples never prove that a model is correct.
- Separate code/API failures, geometry failures, mesh failures, nonlinear convergence failures, and physical audit failures. Do not repair one category with an unrelated strategy.
- All automated repairs must have a bounded scope, retry budget, verifier, and rollback checkpoint.
- Only runs that pass the documented strict audit may be promoted to verified memory.
- Every persisted memory, rule, case, and artifact must carry provenance and compatibility versions.

## Dynamic extension rules

- New repair behavior must be added through a repair rule manifest and handler, not by adding a hard-coded branch to the Kernel.
- New deterministic workflows must be registered as path manifests/DAGs with preconditions, steps, rollback, and acceptance gates.
- Extensions must support discovery, schema validation, enable/disable, conflict reporting, and clean failure isolation.
- Loading executable extensions is a trusted action. Do not execute arbitrary code discovered from untrusted memory or retrieved documents.
- Removal or disablement of an extension must not require editing unrelated registries.

## Editing and compatibility

- Preserve unrelated user changes in the working tree.
- Prefer focused patches. Avoid moving or rewriting unrelated files during a milestone.
- Do not expand the monolithic bearing demo script when a V2 service or extension is the correct boundary.
- Record material architectural decisions in `docs/v2/adr/`.
- Update the relevant V2 document and tests when changing a public contract, extension schema, state transition, audit gate, or memory promotion rule.

## Verification

Use the repository virtual environment when available:

```bash
.venv/bin/python -m pytest tests/test_core.py -q
.venv/bin/python -m pytest tests/test_bearing_domain.py -q
.venv/bin/python -m pytest tests/test_web.py -q
.venv/bin/python -m pytest -q
.venv/bin/ruff check comsol_agent tests scripts
```

Run the smallest relevant test first, then the broader suite before declaring a milestone complete. Documentation-only changes require link/format inspection but not a COMSOL solve.

Real COMSOL tests are a separate gate:

- Use unique scratch model names and isolated artifact directories.
- Apply timeouts, model locks, and cleanup.
- Preserve checkpoints and structured errors on failure.
- Never describe a run as physically successful without the required audit evidence.
- Do not start long COMSOL regressions merely to validate unrelated code.

If a required COMSOL runtime is unavailable, complete deterministic tests and report the unverified runtime gate explicitly.

## Goal-driven development

- Use one `/goal` per roadmap milestone or independently verifiable slice.
- A goal must state outcome, constraints, and verification criteria and point to the governing V2 documents.
- Do not mark a goal complete while required tests, documentation, or runtime gates remain unfinished.
- Keep commits aligned with milestones and avoid mixing generated reports or large simulation artifacts into architecture commits unless explicitly required.
