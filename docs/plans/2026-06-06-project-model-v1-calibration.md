# Project Model v1 Calibration Implementation Plan

> **For Hermes:** Use disciplined-project-delivery, test-driven-development, and subagent/Opus review gates before completion.

**Goal:** Implement GitHub issue #4 by adding a separate Project Model v1 fixture suite and deterministic checker while preserving the existing Project Model v0 suite.

**Architecture:** Keep the v0 loader/checker API stable. Add v1-specific fixture loading, quality/policy checks, signal comparison, and suite summaries in `arena/project_model_fixtures.py`. Keep default verification hermetic: fixture-local JSON only, no live/paid LLM calls. Update `exercise_project_model_fixtures.py` to report v0 and v1 as separate suites.

**Tech Stack:** Python 3.12, pytest, PyYAML, jsonschema, uv. Opus review identified schema validation as mandatory, so Project Model v1 fixtures will validate against a vendored, source-hash-pinned copy of Build Arena's `project-model-v1.schema.json` rather than a locally invented schema.

---

## Source facts checked

- Repo: `git@github.com:leonbreukelman/arena-calibration.git`
- Issue: `https://github.com/leonbreukelman/arena-calibration/issues/4`
- Parent: `https://github.com/leonbreukelman/build-arena/issues/4`
- Build Arena v1 schema: `/home/leonb/projects/build-arena/docs/schemas/project-model-v1.schema.json`
- Build Arena v1 spec: `/home/leonb/projects/build-arena/docs/specs/2026-06-05-project-model-v1-shared-contract-spec.md`
- Readiness item: `PMV1-003` in `/home/leonb/projects/build-arena/docs/verification/2026-06-05-pre-live-readiness-register.json`
- Baseline verification before edits: `uv run pytest -q` -> `89 passed`; `uv run python exercise_project_model_fixtures.py --json` -> v0 overall pass.

## Acceptance criteria mapped to implementation

1. Existing v0 fixtures and tests still pass.
2. New `fixtures/project_model_v1/` suite exists and is loaded separately.
3. V1 loader validates fixture shape, safe relative paths, Project Model v1 top-level/nested fields, and expected/observed signal shape.
4. V1 quality checker uses Build Arena v1 semantics rather than owning a new schema:
   - Validate every fixture `project_model.json` against a vendored copy of Build Arena `docs/schemas/project-model-v1.schema.json` stored at `docs/schemas/project-model-v1.schema.json`, with a canonical `sha256sum -c` pin in `docs/schemas/project-model-v1.schema.json.sha256` and upstream origin metadata in `docs/schemas/project-model-v1.schema.source.yaml`.
   - Treat Build Arena source constants as inert citation strings, never live-read `/home/leonb/projects/build-arena` during normal repo verification.
   - `schemaVersion: project-model/v1` only.
   - graph, snapshot, gate report, provenance, hashes, models, derived artifacts, compatibility required.
   - failed gate report is diagnostic evidence, not acceptance.
   - component/contract/check/probe/gap references must resolve.
   - component `owned_node_ids` must resolve to `projectGraph.nodes[].id`.
   - contract `supporting_edge_ids` must resolve to `projectGraph.edges[].id`.
   - contract direction uses `snapshot.contracts[].from_component_id` / `to_component_id` and graph edges use `projectGraph.edges[].from_node_id` / `to_node_id`, mapped through each component's `owned_node_ids`.
   - provenance refs use string IDs in snapshot objects and full objects in `projectGraph.nodes[].provenance_refs[]` / `projectGraph.edges[].provenance_refs[]`; every snapshot ref must resolve to a graph provenance ref ID.
   - held-out probe metadata is declared in `snapshot.held_out_probes[]`; the checker can validate declared metadata (`builder_independent_from_decomposer`, `hidden_from_primary_decomposer`, `discrimination_passed`, `golden_control_passed`) but cannot prove actual independence.
   - high/blocker/critical verification gaps cannot be mislabeled as `gateReport.passed: true`.
   - protected/generated/scorer/verifier/schema graph nodes cannot be owned as ordinary mutable component surfaces.
5. V1 fixtures cover at least the issue-required cases:
   - F1 valid rich snapshot with graph, gate pass, probes, checks, provenance.
   - F2 decorative/generic project rationale despite syntactically valid v1.
   - F3 code too narrow / wrong component level using v1 graph and contracts.
   - F3 process wrong sequence using v1 contracts/edges.
   - F4 trivial or absent project-model utility.
   - fabricated provenance ref.
   - missing graph edge for a claimed contract.
   - reversed contract direction.
   - self-referential contract.
   - weak or non-independent held-out probe.
   - verification gap mislabeled as success.
   - protected/generated/scorer/verifier/schema ownership leak.
6. V1 summary shows F-label, signal, and v1 quality expectation matches separately; no single ambiguous score.
7. `uv run python exercise_project_model_fixtures.py --json` reports both v0 and v1 separately.

## Task 1: Add failing tests for v1 fixture loading and required coverage

**Objective:** Prove the repo does not yet load or report a v1 fixture suite.

**Files:**
- Modify: `tests/test_project_model_fixtures.py`

**Steps:**
1. Add `test_project_model_v1_fixtures_have_required_shape_and_failure_coverage`.
2. Import future constants/functions:
   - `PROJECT_MODEL_V1_SCHEMA_VERSION`
   - `load_all_project_model_v1_fixtures`
   - `REQUIRED_V1_FAILURE_CASES`
3. Assert IDs include all 12 required cases and labels include F1/F2/F3/F4.
4. Assert every v1 project model uses `project-model/v1`, has graph nodes/edges, provenance refs, gate report, derived artifacts, and compatibility v0 path.
5. Run targeted test and verify RED: missing imports/functions/fixtures.

## Task 2: Add failing tests for v1 quality/policy checks

**Objective:** Lock down deterministic v1-specific rejection behavior before writing production code.

**Files:**
- Modify: `tests/test_project_model_fixtures.py`

**Steps:**
1. Add tests for `evaluate_project_model_v1_quality` using fixture mutations or fixture data.
2. Pin `expected_v1_quality_issue_codes` comparison as an exact sorted set match (`observed codes == expected codes`), so invalid fixtures pass only when rejected for the intended reason.
3. Expected issue codes:
   - `schema_validation_error`
   - `fabricated_provenance_ref`
   - `missing_graph_edge_for_contract`
   - `reversed_contract_direction`
   - `self_referential_contract`
   - `weak_held_out_probe`
   - `verification_gap_mislabeled_success`
   - `protected_ownership_leak`
   - plus base structural codes such as `unsupported_schema_version` and `missing_required_field`.
4. Add an acyclic/valid positive assertion so the checker does not reject valid shared-edge graphs.
5. Add a deterministic ordering assertion: issue lists sort by `(code, location, message)`.
6. Run targeted tests and verify RED.

## Task 3: Add failing tests for separate v0/v1 reporting and mismatch reporting

**Objective:** Ensure the exercise command reports v0 and v1 separately, preserves v0 access/backward compatibility, and v1 mismatch rows are field/code-level.

**Files:**
- Modify: `tests/test_project_model_fixtures.py`
- Modify later: `exercise_project_model_fixtures.py`

**Steps:**
1. Add `test_project_model_v1_runner_reports_quality_expectations_without_single_score`.
2. Add `test_project_model_combined_exercise_reports_v0_and_v1_separately` using the combined main function and/or `runpy`.
3. Add a v0 regression-pinning assertion: existing v0-only `main(["--json"])` still exposes the old `metadata`, `summary`, and `fixtures` shape, and combined JSON keeps v0 under `suites.project_model_v0`.
4. Add perturbation test where observed v1 signal label or component status changes; assert field-level mismatch names.
5. Add test that the canonical `REQUIRED_V1_FAILURE_CASES` contains exactly the 12 issue-required IDs.
6. Run targeted tests and verify RED.

## Task 4: Implement v1 loader/checker APIs

**Objective:** Make the new tests pass with minimal code.

**Files:**
- Modify: `arena/project_model_fixtures.py`

**Implementation outline:**
- Add constants:
  - `PROJECT_MODEL_V1_CONTRACT_SOURCE` as the GitHub/spec URL citation string.
  - `PROJECT_MODEL_V1_SCHEMA_SOURCE` as the GitHub schema URL citation string.
  - `PROJECT_MODEL_V1_SCHEMA_PATH = Path("docs/schemas/project-model-v1.schema.json")` for the vendored copy.
  - `PROJECT_MODEL_V1_SCHEMA_SHA256_PATH = Path("docs/schemas/project-model-v1.schema.json.sha256")` for the recorded upstream hash.
  - `PROJECT_MODEL_V1_SCHEMA_VERSION = "project-model/v1"`.
  - `PROJECT_MODEL_V1_SIGNAL_SCHEMA_VERSION = "project-model-v1-calibration-signal/v0"`; do not let tests choose this after the fact.
- Add dataclass `ProjectModelV1Fixture` with fields parallel to v0 plus `expected_v1_quality_issue_codes` and `case_description`.
- Add `load_project_model_v1_fixture` and `load_all_project_model_v1_fixtures`, reusing safe path and JSON helpers.
- Add signal validation for v1 fixture expectations.
- Keep v0 loader names and behavior unchanged.

## Task 5: Implement v1 quality/policy evaluator

**Objective:** Deterministically score valid and invalid v1 fixtures.

**Files:**
- Modify: `arena/project_model_fixtures.py`
- Create: `docs/schemas/project-model-v1.schema.json`
- Create: `docs/schemas/project-model-v1.schema.json.sha256`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Implementation outline:**
- Vendor Build Arena `docs/schemas/project-model-v1.schema.json` exactly and record its SHA-256. Do not live-read the sibling Build Arena checkout during normal tests.
- Add `jsonschema>=4.0` and validate every v1 fixture model with `Draft202012Validator` before local semantic checks.
- Add `_v1_quality_issue(code, message, location)` with `feedback: "build-arena Project Model v1"`.
- Gather ID indexes:
  - graph node IDs and graph edge IDs.
  - graph provenance ref IDs from node/edge `provenance_refs`.
  - component, contract, check, held-out probe, verification gap IDs from `snapshot`.
  - component-owned graph nodes.
- Validate top-level and nested required fields based on Build Arena schema/spec.
- Detect issue-required semantic failures.
- Return a list of issue dicts, not a boolean.

## Task 6: Generate/commit v1 fixture data

**Objective:** Add hermetic fixture files under `fixtures/project_model_v1/`.

**Files:**
- Create: `fixtures/project_model_v1/<fixture_id>/manifest.yaml`
- Create: `fixtures/project_model_v1/<fixture_id>/project_model.json`
- Create: `fixtures/project_model_v1/<fixture_id>/proposal.md`
- Create: `fixtures/project_model_v1/<fixture_id>/public_rationale.md`
- Create: `fixtures/project_model_v1/<fixture_id>/expected_advisory_signal.json`
- Create: `fixtures/project_model_v1/<fixture_id>/observed_advisory_signal.json`

**Fixture design:**
- Use one valid rich base model with 3 components, 2 contracts, graph nodes/edges, provenance refs, gate report, one independent held-out probe, checks, derived artifacts, hashes, and compatibility v0 path.
- For rationale-only F2/F3/F4 fixtures, keep the v1 model valid and express the expected F-label/signals in the advisory signal.
- For v1-policy invalid fixtures, mutate one failure at a time and list the expected `expected_v1_quality_issue_codes` in the manifest.
- Keep all hashes syntactically valid 64-hex placeholders; no live/generated secrets.

## Task 7: Wire combined exercise command

**Objective:** Make `uv run python exercise_project_model_fixtures.py --json` emit separate v0/v1 suites.

**Files:**
- Modify: `arena/project_model_fixtures.py`
- Modify: `exercise_project_model_fixtures.py`

**Implementation outline:**
- Add `run_all_project_model_fixture_checks(v0_dir, v1_dir)` returning:
  - legacy top-level v0 `metadata`, `summary`, and `fixtures` for backward compatibility.
  - `suites.project_model_v0`.
  - `suites.project_model_v1`.
  - top-level `combined_summary.overall_pass` / `combined_summary.suite_passes` so the combined status never hides per-suite details.
- Add `combined_main(argv)` with `--suite all|v0|v1`, `--json`, and optional `--v0-fixtures-dir`, `--v1-fixtures-dir`.
- Keep `main(argv)` as v0-only compatibility if practical; otherwise update tests to ensure v0 behavior is still accessible.
- Point `exercise_project_model_fixtures.py` at `combined_main`.

## Task 8: Documentation and verification

**Objective:** Make the change discoverable and prove it works.

**Files:**
- Modify: `README.md` if it currently describes only v0.
- Create or update: `docs/verification/2026-06-06-project-model-v1-calibration.md` with Opus review and final verification evidence if useful.

**Commands:**
1. `uv run pytest tests/test_project_model_fixtures.py -q`
2. `uv run pytest -q`
3. `uv run python exercise_project_model_fixtures.py --json`
4. `uv run python exercise_project_model_fixtures.py`
5. `git diff --check`
6. Targeted JSON parse check for fixture files.

## Task 9: Opus review gates

**Objective:** Use Opus as requested before implementation and after implementation.

**Plan review result:** Opus returned `ACCEPT_WITH_CHANGES` on 2026-06-06. This plan was patched before coding to address the blockers: vendored/schema-hash validation, inert source citations, exact expected issue-code matching, quoted v1 graph/contract/provenance fields, declared held-out probe metadata limits, v0 output regression pinning, deterministic issue ordering, canonical 12-case list, and fixed v1 signal schema choice.

**Plan review:**
- Save prompt/output under `docs/verification/2026-06-06-opus-project-model-v1-plan-review.*`.
- Ask for verdict: `ACCEPT`, `ACCEPT_WITH_CHANGES`, or `REJECT`.
- Patch this plan before coding if review finds valid blockers.

**Implementation review:**
- After tests pass, run read-only Opus review of the final diff.
- Save final output under `docs/verification/2026-06-06-opus-project-model-v1-final-implementation-review.md`.
- Fix any blocking issues, rerun targeted/full verification, and record the result.

**Final implementation review result:** Opus returned `ACCEPT` after the final cleanup changes and found no blockers attributable to the implementation or missed criteria.

## Non-goals / guardrails

- Do not remove Project Model v0 support.
- Do not run paid/live model calls.
- Do not claim v1 is a production allow/deny gate; this is calibration/advisory coverage.
- Do not make Arena Calibration the owner of the Build Arena v1 schema; constants and checks should point back to Build Arena sources.
- Do not collapse v0 and v1 into one ambiguous score.
