# Independent Opus Critique — prompt optimization implementation

> Source: read-only Opus pass over the current implementation diff after tests. After this critique, the cheap path-traversal guard and no-op-hunk wording nits were addressed and re-tested.

## Critique

**Verdict: ACCEPT** — net correctness improvement. The central fix (apply-failures no longer counted as semantic changes) is sound and well-tested. Notes below are minor.

### Correctness
- **Core fix is right.** `verifier._component_verdict` switching from `not patches_equivalent(...)` to `compare_patches(...).equivalent is False` correctly stops diff-format failures from masquerading as load-bearing changes. The indeterminate accounting flows through to the report and notes cleanly.
- **Trade-off worth flagging:** a perturbation that *genuinely* changes behavior but yields unappliable worker output now lands in `indeterminate` rather than `changed`, so it can **under-count** true load-bearing components. This is the intended bias (favor precision over recall), but it means `load_bearing_fraction` is now a lower bound when indeterminates are present. The note partially surfaces this; consider whether the threshold sweep should treat high-indeterminate runs as low-confidence rather than just appending a note.
- **`normalize_patch_diff` fence regex:** `(?:\n```|\Z)` will silently swallow trailing content if a closing fence is missing — acceptable for LLM noise, but a diff that legitimately contains a nested ``` would be truncated. Low risk for code diffs.
- **`apply_patch` path handling:** `target_name` comes from the (now normalized) diff and is joined under tempdir with `parents=True`. A malicious/garbled `+++ b/../../x` could escape the tempdir. Inputs are model-generated and trusted here, so low severity, but a `..`/absolute-path guard in `_extract_target_name` would be cheap insurance.
- **Parse-failure fallback:** in `compare_patches`, when both sides apply but `_normalize` returns None, it byte-compares and labels `SEMANTIC_MISMATCH` on inequality even though the mismatch may be pure formatting. Pre-existing behavior, not a regression.
- **Prompt contract minor tension:** "emit a valid no-op unified diff" vs. "contain at least one hunk" — a no-op-with-hunk (line replaced by itself) satisfies both, but the instruction is slightly self-contradictory and may confuse the worker. Prompt-only, no code impact.

### Test gaps
- No test for `load_fixture` raising on **mismatched corruptions length** (the new `ValueError` path), nor for the `all_perturbations` length-mismatch `ValueError`.
- No test for `patches_equivalent` **backward-compat** returning `False` on indeterminate (the legacy contract the diff explicitly documents).
- `normalize_patch_diff` **CRLF→LF** normalization is asserted only indirectly; no direct case.
- `corruptions=None` default path (all-`None` corruptions → `adding_mistakes` fallback) is untested.
- The new **paraphrase-brittleness note** branch in `verify` has no coverage.
- `exercise_verifier` detection relies on `stripped.strip() in KNOWN_CORRUPTIONS` exact-matching the manifest text minus the `"N. "` prefix — robust only while `adding_mistakes` substitutes the corruption verbatim. A test pins F1; consider asserting the same for F2/F3 to lock the contract.

Nothing here blocks. The 45 passing tests plus the harness predictions cover the high-risk path (indeterminate accounting); the gaps above are mostly error-path and control-branch coverage.
