I attempted to ground this against the actual repo, but no file-read/Bash/Grep tools are available here and the LSP server doesn't support Python, so I could not directly inspect `arena/project_model_fixtures.py`, the existing tests, or the sibling Build Arena schema. The review below is therefore of the **plan text against the stated acceptance criteria and source-doc descriptions** — I'm flagging that limitation explicitly because several blockers turn on the actual v1 edge/provenance field model, which I could not verify firsthand.

---

## Verdict: ACCEPT_WITH_CHANGES

The architecture is sound and matches the acceptance contract: separate `fixtures/project_model_v1` suite, separate v0/v1 reporting, hermetic JSON-only verification, deterministic checker returning issue codes, TDD-first. No reason to reject. But there are critical gaps that will produce either a silently-wrong checker or a non-reproducible/non-deterministic acceptance signal if implemented as written.

---

## Critical blockers (fix before coding)

1. **The checker hand-codes v1 semantics with no anti-drift mechanism — this *is* a local redefinition of Build Arena v1.** Task 5 says "validate top-level and nested required fields based on Build Arena schema/spec," but the plan defers actually validating fixtures against `project-model-v1.schema.json` to "unless Opus review identifies an unavoidable requirement." That requirement is unavoidable. Without (a) vendoring a pinned copy of the v1 schema into the repo with its upstream version/hash recorded, and (b) a test that fails when the hand-coded required-field list diverges from that vendored schema, the checker will silently rot the moment Build Arena revises v1. This is the central risk in requirement #5 (don't redefine v1 incorrectly) and the plan currently violates it.

2. **`PROJECT_MODEL_V1_SCHEMA_SOURCE`/`CONTRACT_SOURCE` reference absolute sibling paths (`/home/leonb/projects/build-arena/...`).** Clarify whether these are citation strings or live file reads. If live reads, verification is non-hermetic and breaks on CI/any other machine — directly contradicting the "hermetic, no external dependency" goal. The plan must state these are inert pointer strings *and* vendor the schema, or it fails reproducibility.

3. **Pass/fail comparison semantics for invalid fixtures are unspecified.** `expected_v1_quality_issue_codes` is introduced (Task 4/6) but nowhere does the plan say how observed issue codes are compared — exact-set match, superset, or subset. This is the classic calibration bug: a fixture engineered to be rejected must count as PASS when the checker rejects it for the *right* code. Without pinning the comparison rule, "deterministic" acceptance is undefined. Pin it (recommend exact-set match per fixture) before Task 2.

4. **The four graph/contract semantic checks assume an edge/provenance data model the plan never quotes.** `missing_graph_edge_for_contract`, `reversed_contract_direction`, `self_referential_contract`, and provenance-ref resolution all depend on the exact v1 edge representation (directed `from`/`to`, edge types, `provenance_refs` shape). The plan asserts this model without citing the actual schema field names. If the assumed model is wrong, all four checks are built on sand. Quote the concrete schema fields these checks read.

5. **Held-out probe / independence checks risk being tautological.** "Independent, hidden from primary decomposer, pass discrimination/golden controls" cannot be derived from static fixture JSON — the checker can only confirm the fixture *declares* independence. Define the exact fields and thresholds `weak_held_out_probe` keys off, and state plainly that this validates declared metadata, not actual independence. As written it's hand-wavy.

---

## Missing tests

- **No v0 regression-pinning test.** Refactoring `main` → `combined_main` (Task 7) can silently change the existing v0 JSON shape. `exercise_project_model_fixtures.py --json` is part of the current acceptance baseline; add a test pinning the v0 suite output structure so "v0 still passes" means structurally identical, not just "doesn't crash."
- **No downstream-consumer check for the JSON shape change.** Moving the top level to `suites.project_model_v0/_v1` is a breaking change to anything (e.g., the Build Arena harness) that parses today's output. Verify no consumer depends on the current top-level keys, or keep them backward-compatible.
- **No determinism test on issue-list ordering.** Task 5 returns a list of issue dicts; "deterministic field/code-level reporting" requires a stated sort (by code, then location). Add a test asserting stable ordering.
- **No test pinning the canonical 12 IDs in one place.** "12 required cases" (Task 1) is spread across criterion 5 and the Task 2 code list. Enumerate `REQUIRED_V1_FAILURE_CASES` canonically and assert the count + membership in one test to avoid an off-by-one between F-labels (F1/F2/F3-code/F3-process/F4 = 5) and the 7 policy-invalid codes.

## Unsafe assumptions

- **Signal shape is left for "tests to choose."** Task 4 offers `project-model-v1-calibration-signal/v0` *or* reuse advisory-v0, yet Task 6 fixture files are named `expected_advisory_signal.json` — implying reuse. Letting TDD pick a production constant's value is backwards. Decide the signal contract before Task 1.
- **`compatibility v0 path` (Task 1 step 4).** Validating a v1→v0 downgrade mapping means arena-calibration could invent v0↔v1 compat semantics that Build Arena owns. Point the check at Build Arena's compatibility definition; don't author one.
- **`summary.overall_pass` (Task 7) may itself be the forbidden "single ambiguous score."** Ensure it never substitutes for per-suite visibility and that expected-failures are accounted for correctly in its computation.
- **Placeholder 64-hex hashes** are fine only if the checker validates hash *shape*, never recomputes content hashes. State this explicitly so a "valid" fixture isn't rejected.

## Minor

- **PMV1-003 is cited but mapped to nothing.** If the readiness register imposes a constraint, map it to an acceptance criterion; otherwise drop the citation so it isn't mistaken for a satisfied requirement.
- Task 2's valid-shared-edge positive assertion is good — keep it, and extend it to assert the *valid* fixture yields an empty issue list (no false positives), not just "not rejected."

---

**Bottom line:** Approve to proceed *after* (1) vendoring + pinning the v1 schema with a drift test, (2) confirming the source constants are inert and hermetic, (3) pinning the expected-vs-observed comparison rule, and (4) quoting the real v1 edge/provenance fields the four semantic checks depend on. Everything else is solid.
