# Independent Opus Review — DSPy/GEPA Prompt Evolution spec + plan

**Reviewer:** independent Opus pass. **Mode:** read-only (no doc edits made).
**Scope reviewed:** `docs/specs/2026-05-30-dspy-gepa-prompt-evolution.md`,
`docs/plans/2026-05-30-dspy-gepa-prompt-evolution.md`,
`docs/verification/2026-05-30-opus-dspy-gepa-research-review.md`, cross-checked against the
actual working tree (`arena/patch_eq.py`, `verifier.py`, `lanham.py`, `llm.py`, `api_llm.py`,
`fixtures.py`, `runner.py`, `tests/`, `fixtures/*/manifest.yaml`).

---

## 1. VERDICT: ACCEPT_WITH_CHANGES

The architecture is correct and the safety stance is sound. The subject/product firewall, the
three-layer separation, the freezing of the subject prompt and thresholds, "no optimizer in the
live verifier path," and the deferral of perturbation-policy GEPA all faithfully internalize the
research review's central critique (objective A is an adversary of objective B). On *direction*,
this is a GO.

It is **not** a clean ACCEPT because the spec and plan were written against the research review's
**stale code snapshot**, not the current working tree. The tree has already moved on: the
patch-outcome taxonomy and diff normalization largely exist, fixture-specific corruptions are
already wired in, and an untracked **RED** test file already encodes the verifier migration with
field names the plan contradicts. Following the plan verbatim would duplicate modules, leave the
suite red, and — most importantly — leave one **active, un-governed contamination vector** in the
instrument. All issues are fixable by editing the three docs and reconciling with the tree.

---

## 2. Critical blockers (must clear before implementation)

**B1 — The baseline is already RED; the plan asserts it is green.**
`tests/test_prompt_optimization.py` (untracked, in tree) contains
`test_verifier_does_not_count_apply_failures_as_load_bearing_changes`, which asserts
`PerturbationOutcome.sample_diffs_indeterminate == 3`, `load_bearing_fraction == 0.0`,
`perturbations_changed_patch == 0`, and a note containing `"indeterminate patch comparisons"`.
None of those exist in `arena/verifier.py` today; current code yields `perturbations_changed_patch == 4`
and fraction `1.0` for that fake (it still calls the boolean `patches_equivalent`, so an unapplyable
diff counts as "changed" — `verifier.py:165-174`). Plan **Task 0.1 "Expected: Existing tests pass"
is false as of this checkout.** Resolve before any "baseline" claim.

**B2 — The plan duplicates modules that already exist and inverts the dependency.**
`arena/patch_eq.py` already defines `PatchComparisonStatus`
(`EQUIVALENT/SEMANTIC_MISMATCH/INDETERMINATE_BOTH_FAILED/INDETERMINATE_APPLY_FAILED`),
`PatchComparison`, `compare_patches()` (returns `equivalent=None` on apply failure), and
`normalize_patch_diff()` (single markdown-fence strip, CRLF→LF, exactly one trailing newline) plus
`_extract_target_name`. Plan **Task 1.2** creates a *new* `arena/patch_outcome.py` reimplementing all
of this, and **Task 1.4** makes the existing, more-correct `patch_eq.py` "delegate to the new
evaluator" — backwards. This is churn and a real chance of behavioral drift.

**B3 — The plan's new verifier fields contradict the already-written test.**
Plan **Task 2.2** proposes `sample_status_counts` / `invalid_samples` / `majority_status`; the existing
RED test pins `sample_diffs_indeterminate` and the note string `"indeterminate patch comparisons"`.
Implement the plan literally and the suite stays red. Names must be reconciled.

**B4 — A live contamination vector is un-governed (see §6, item A).** `reasoning_corruptions` are now
measurement stimulus, co-authored with the target verdict in the same manifest. This must be governed
(provenance + blind authoring + held-out validation) before the instrument's numbers are trusted. It
is independent of DSPy/GEPA and is the highest-integrity-risk item.

---

## 3. Required changes to the SPEC

- **§2 "Current repository facts" is materially inaccurate. Re-derive from the current tree:**
  - ✗ "patch_eq.py currently collapses apply failure into boolean non-equivalence." Only the legacy
    `patches_equivalent()` wrapper collapses; `compare_patches()` already returns a structured
    `INDETERMINATE_APPLY_FAILED` with `equivalent=None`. The real gap is that **the verifier still
    calls the boolean wrapper.**
  - ✗ "lanham.py perturbations are … filler `...`." Filler is now
    `"[step omitted: reasoning for this component is unavailable]"` (`lanham.py:111-115`), and
    `adding_mistakes` already accepts a fixture-specific `corrupted` argument (`lanham.py:76-94`);
    `"It is NOT the case that "` is only the *no-corruption default*.
  - ✗ Omits that `Fixture.reasoning_corruptions` already exists (`fixtures.py:72,125-134`) and that
    **all four manifests already populate it.** The "perturbations are weak/future" framing is wrong.
  - The "165 worker + 3 judge = 168" figure implies Σcomponents over promoted fixtures = **13**
    (`9 + 12·Σn = 165 ⇒ Σn = 13`), not the research review's "11." Re-derive and reconcile.
- **§5 Layer 1:** reframe from "build a new taxonomy" to "**migrate the verifier onto the existing
  `compare_patches` taxonomy and extend it**." Drop the new `PatchStatus` enum unless a genuine
  single-patch quality classification is needed beyond the existing two-patch comparison status; if
  it is, build it *on top of* `normalize_patch_diff`/`apply_patch`/`_normalize`, not as a fork.
- **§5 Layer 2 + §6:** the dataset-size gate must apply to the **product** lane too, not only the
  deferred perturbation lane. With 4 benchmark fixtures there is no product train/dev/heldout split;
  state that product GEPA is **not runnable until a real, separately-sourced dataset exists**, and
  forbid using calibration benchmark fixtures as product training data.
- **§7 Served-model pinning:** the spec *requires* `requested_model`+`served_model` for API providers,
  but `served_model` validation exists **only** for OpenAI-compatible providers
  (`api_llm.py:108-133`); the default `AnthropicWorker` (`llm.py:140-165`) records nothing. Either add
  a spec-level task to extend recording to Anthropic/CLI (`unverified_cli_model`), or explicitly scope
  it out — do not silently require it.
- **New §:** governance for `reasoning_corruptions` (provenance, blind authoring, held-out-model
  validation, freezing). See §6.

## 4. Required changes to the PLAN

- **Phase 0:** fix the false green-baseline claim. Either (a) note that `tests/test_prompt_optimization.py`
  is RED and fold it into Phases 1–2 as the driving spec, or (b) reconcile it explicitly. The plan must
  *acknowledge this file exists.*
- **Phase 1:** rewrite around `patch_eq.py`. Replace "Create `arena/patch_outcome.py`" + "make
  `patch_eq.py` delegate to it" with "extend `arena/patch_eq.py`." Delete or de-scope the duplicate
  normalization/fence/newline tasks (already implemented and already covered by
  `test_prompt_optimization.py::test_fenced_diff_missing_final_newline_is_normalized_before_apply`).
- **Phase 1 test asset:** Task 1.1 depends on `/tmp/arena_xai_diag_outputs/F1_unperturbed_grok-4.3_sample1.diff`
  — an absolute path not in the repo and absent in CI/fresh clones. Make the **inline** Grok-4.3 sample
  mandatory; do not read from `/tmp`.
- **Phase 2:** adopt the existing test's field name `sample_diffs_indeterminate` (and the note string)
  rather than inventing `invalid_samples`/`sample_status_counts`; have the verifier call
  `compare_patches` and exclude `INDETERMINATE_*` from `changed_patch` and the load-bearing count.
  State explicitly that **live** fractions are *expected to change* post-migration (only *fake*-worker
  fractions stay fixed) — do not "preserve" the old inflated behavior.
- **Phases 8–9:** gate the product-optimization lane on a real dataset (same gate as perturbation
  research). Today no task populates `datasets/patch_quality/*.jsonl`; the Phase 8 dry-run and Phase 9
  smoke would optimize on an empty/near-empty, fixture-derived set. Mark Phase 9 not-runnable until a
  dataset with a sealed held-out split exists, sourced separately from the benchmark fixtures.
- **Firewall:** add a negative assertion at the **verifier call path** (the verifier refuses a
  `role: product_patch_compiler` artifact), not only at the registry (AC#8 currently tests the
  registry). Task 4.2's "wire registry into verifier later, maybe" should become "verifier loads
  *only* subject artifacts; loading any other role raises."
- **Add a corruption-authoring task** to govern `reasoning_corruptions` (provenance, blind authoring,
  held-out validation, freezing) — currently nothing in the plan owns this, yet the migration depends
  on it.

## 5. Missing tests / unsafe assumptions

- **Unsafe:** "existing tests pass" (Task 0.1) — they don't (B1). "F1/F2/F3 fractions unchanged after
  migration" is true only for valid-diff fakes; conflating that with live behavior would hide the very
  fix being shipped.
- **Unsafe:** product GEPA is greenlit while its dataset is empty scaffolding — optimizing on a handful
  of fixture-derived rows overfits and consumes the benchmark.
- **Missing:** `_majority_diff` over an all-indeterminate sample set (today each unapplyable sample
  forms its own singleton bucket — `verifier.py:130-141`; assert the intended behavior).
- **Missing:** served-model coverage for Anthropic/CLI; `ModelCallTrace.served_model` (Task 3.2) is
  silently empty for the default provider.
- **Missing:** a determinism note — `WORKER_TEMPERATURE = 0.0` already (`llm.py:36`), so the 3-sample
  majority vote is near-vestigial on the Anthropic path. Either justify `N_SAMPLES=3` under temp-0 or
  document that variance only matters for non-zero-temp providers. (The research review's
  "stochastic metric, tiny n" risk is smaller than stated for temp-0, real elsewhere.)
- **Missing (instrument validity):** a control/placebo test and a code-alone-solve guard, as the
  research review's "Missing tests" section lists. The spec inherited the conclusions but the plan did
  not carry these into tasks.

## 6. Where the plan still risks contaminating the instrument with product optimization

The GEPA-side firewall is clean: subject prompt, thresholds, load-bearing rule, live path, and the
perturbation loop are all explicitly off-limits (spec §6; plan "non-goals"). The residual risks are
**not** GEPA — they are introduced by the in-flight migration and under-governed by the docs:

- **(A) `reasoning_corruptions` are live stimulus co-authored with the target verdict — hand-rolled
  answer-key leakage.** Each manifest declares its expected load-bearing fraction *in the same file*
  as the corruptions (F1 `= 0.75`, F2 `= 0.25`). The stimulus and its desired measurement outcome are
  co-designed by one author, with no blind authoring and no held-out-model validation. This is exactly
  the leakage the research review attributes to GEPA-2B — executed manually, today, in
  `adding_mistakes` (`lanham.py:76-94` ← `fixtures.py:reasoning_corruptions`). The corruptions
  themselves look content-faithful (semantic inversions of each premise), so this is a *governance*
  gap, not proof of a defect — but the instrument's validity is currently unaudited. **Require:**
  corruptions authored from each component's meaning blind to the expected fraction; validated on ≥1
  held-out subject model to confirm the fraction is not an artifact of corruption wording; then frozen
  as part of the instrument.
- **(B) Product optimization sourced "from fixture" (spec Layer 2) couples the product lane to the
  calibration benchmark.** The product metric scores against `example.expected_diff` /
  `expected_patched_source`; with only 4 fixtures (all of them the benchmark), "generated from fixture"
  data means the product prompt trains on the calibration set. The firewall keeps the product prompt
  out of the subject *role*, so the measurement is not directly corrupted — but shared data destroys
  any later claim of instrument/product independence and cannot form an honest split. Forbid
  benchmark fixtures as product training data; require a separately-sourced product corpus.
- **(C) Verifier↔registry wiring leaves a future door open.** AC#8 tests the *registry* firewall, not
  the *verifier call path*. Until the verifier is asserted to reject non-subject artifacts, a later
  "wire the registry in" step (Task 4.2) could load an optimized product prompt as the subject.

## 7. Concise patch list to apply to the docs before handoff

**Spec (`docs/specs/2026-05-30-dspy-gepa-prompt-evolution.md`):**
1. §2: correct the patch_eq fact (taxonomy + `compare_patches` + `normalize_patch_diff` already exist;
   the gap is the verifier still calling boolean `patches_equivalent`).
2. §2: correct the lanham facts (filler is `[step omitted …]`, not `...`; `adding_mistakes` already
   takes fixture-specific corruptions).
3. §2: add that `Fixture.reasoning_corruptions` exists and all four manifests populate it.
4. §2: re-derive the component count (Σ = 13 across promoted fixtures, not 11) and reconcile with the
   research-review doc.
5. §5 Layer 1: reframe as "migrate verifier onto existing `compare_patches`; extend `patch_eq.py`";
   drop the parallel `patch_outcome.py`/`PatchStatus` unless a single-patch classifier is justified.
6. §5/§6: add a dataset-size + provenance gate to the **product** lane (not just perturbation), and
   forbid benchmark fixtures as product training data.
7. §7: reconcile the served-model requirement with reality (only OpenAI-compatible validates today) —
   add a task or scope it out.
8. Add a new section: `reasoning_corruptions` governance (blind authoring, held-out validation,
   freezing) — the active instrument-integrity item.

**Plan (`docs/plans/2026-05-30-dspy-gepa-prompt-evolution.md`):**
9. Phase 0: remove the false "existing tests pass" claim; acknowledge `tests/test_prompt_optimization.py`
   is RED and adopt it as the driving spec for Phases 1–2.
10. Phase 1: rewrite to extend `patch_eq.py`; delete duplicate normalization tasks; make the Grok-4.3
    sample **inline** (no `/tmp` path).
11. Phase 2: use field name `sample_diffs_indeterminate` + note `"indeterminate patch comparisons"`;
    state that live fractions are expected to change.
12. Phase 4: assert the firewall at the verifier call path, not only the registry.
13. Phases 8–9: gate product GEPA on a real, separately-sourced dataset with a sealed held-out split;
    add a task that actually produces dataset content (none exists today).
14. Add a corruption-authoring/validation task.
15. Carry the research review's control/placebo and code-alone-solve guards into concrete verifier
    tasks.

**Research-review doc (`docs/verification/2026-05-30-opus-dspy-gepa-research-review.md`):**
16. Add a dated "superseded-in-part" note: its code citations (boolean `patches_equivalent` as the
    only comparison; `lanham` filler `...`; "11 components"; "zero coverage") predate the current tree
    and should not be quoted as current fact.
