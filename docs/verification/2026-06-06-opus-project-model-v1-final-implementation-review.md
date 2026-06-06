## Verdict: ACCEPT

Both final cleanup changes are sound and introduce no blockers, and all stated verification passes.

**Cleanup 1 — sha256 split:**
- `expected_hash = ...read_text().strip().split()[0]` correctly extracts the digest from a pure `sha256sum -c` line (`<hash>  <filename>`), and `sha256sum -c` reports OK without warnings, so the file is genuinely in canonical format. The hash gate in `_project_model_v1_schema()` still fires on mismatch.
- Moving origin metadata to `project-model-v1.schema.source.yaml` is consistent with the README hunk. Note (non-blocking): `PROJECT_MODEL_V1_SCHEMA_SOURCE` remains a hardcoded constant pinned to commit `6aab52cc…`; it now duplicates the yaml and could drift later. Not a blocker today since both point at the same commit, but worth keeping in mind.

**Cleanup 2 — guarded direction checks:**
- The added guard `from_component_id in component_ids and to_component_id in component_ids and from_component_id != to_component_id` correctly suppresses `misrouted_contract_edge`/`reversed_contract_direction` noise precisely when a distinct, separate code already fires (`missing_component_reference` for unknown endpoints, `self_referential_contract` for `from == to`). The legitimate `reversed_contract_direction` case (both endpoints known and distinct) still runs. This is the right scoping and matches the deterministic, sorted-issue calibration design.

**Acceptance criteria:** v0 preserved (legacy top-level `metadata`/`summary`/`fixtures` retained; v0 loader unchanged), v1 added with required F1/F2/F3/F4 cases enumerated in `REQUIRED_V1_FAILURE_CASES`, vendored hash-pinned schema validation, and separate `suites`/`combined_summary` reporting. 97 passed, combined exercise true, 37 JSON files valid, `git diff --check`/`py_compile` clean.

No blockers attributable to the two cleanup changes or missed criteria.
