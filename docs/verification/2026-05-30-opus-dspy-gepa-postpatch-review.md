All four prior-review correction items are verified against the live tree, and the spec's "current repository facts" now match the code exactly:

- `verifier.py:45,66-67,78,171-200,267-273` — imports and uses `compare_patches`, has `sample_diffs_indeterminate` / `majority_comparison` / `perturbations_indeterminate`, treats `equivalent is None` as indeterminate, and emits the `"indeterminate patch comparisons"` note. ✓
- `patch_eq.py:33-209` — `PatchComparisonStatus` (incl. both `INDETERMINATE_*`), `compare_patches`, `normalize_patch_diff`, legacy `patches_equivalent`. ✓
- `lanham.py:79-140` — fixture-specific `corrupted` arg, `"It is NOT the case that "` as no-corruption default only, filler `"[step omitted: …]"`. ✓

---

## Verdict

**1. VERDICT: ACCEPT**

All six requested changes are present and the docs are now accurate against the working tree:
- `compare_patches()` is used everywhere; no duplicate `patch_outcome.py` is proposed (spec §5 L1, plan Phase 1). ✓
- `reasoning_corruptions` acknowledged as existing + governance section added (spec §4.6, §5 L2; plan Task 2.2). ✓
- Product dataset gate forbids benchmark-fixture training and blocks GEPA until a separately-sourced split exists (spec §5 L2 / §6 / AC#7; plan Task 5.3 gate, Phases 8–9). ✓
- Verifier-path firewall asserted, not just registry (spec §7 + AC#5; plan Task 4.1/4.2). ✓
- Corruption governance + provenance + held-out validation (spec §5 L2). ✓
- Superseded-in-part note on the research review (line 3). ✓

Component count reconciled to 13 (168 calls), and local verification corroborates the once-RED baseline is now green (focused prompt-optimization tests passed, full suite later passed with 46 tests, harness predictions hold, dry-run 168).

**2. Remaining blockers before handoff: none.**

**3. Small doc patches still required: none mandatory.** Two optional, non-blocking nits if you touch the files again:
- `arena/verifier.py:45` still imports `patches_equivalent` alongside `compare_patches`. Confirm it's actually still referenced; if it's now dead, drop it. Doesn't affect the docs' correctness — spec §2 already frames the wrapper as legacy.
- Research-review body still says "11 components" inline; the superseded-in-part header covers this, so no edit needed unless you want the body reconciled to 13 for cleanliness.

Ship it.
