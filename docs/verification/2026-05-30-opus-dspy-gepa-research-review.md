# Independent Review: DSPy/GEPA for arena-calibration

> Superseded-in-part note, 2026-05-30: this review remains useful for the main architectural critique, but some code citations describe an earlier working-tree snapshot. The current tree already has `PatchComparisonStatus`, `compare_patches()`, `normalize_patch_diff()`, fixture-level `reasoning_corruptions`, and verifier indeterminate fields. Use `docs/specs/2026-05-30-dspy-gepa-prompt-evolution.md` and `docs/plans/2026-05-30-dspy-gepa-prompt-evolution.md` for current implementation guidance.

## Context

The team wants to add DSPy/GEPA prompt evolution to `arena-calibration`. The proposal is to
(1) build an offline optimization lane that freezes versioned prompt artifacts, (2) use GEPA for
*two* objectives — production patch quality **and** the calibration perturbation strategy, (3) first
fix observability/patch-outcome taxonomy, (4) add a train/dev/heldout split, (5) use Opus as the
GEPA reflection LM with cheap task LMs.

This review attacks that direction. The core question is not "can DSPy do this" but "where does
optimization belong in a *measurement instrument*, and where does it destroy the thing being
measured." I read the actual code (`arena/verifier.py`, `lanham.py`, `patch_eq.py`, `llm.py`,
`runner.py`, fixtures, tests) to ground the critique.

---

## VERDICT

**Conditional GO on the plumbing; NO-GO on the GEPA-for-calibration framing. Do not write a GEPA
spec yet.**

Per hypothesis:

| # | Proposal | Call | Why |
|---|----------|------|-----|
| 1 | Offline lane, freeze versioned artifacts | **GO** | Correct instinct. Keep GEPA out of the live path. |
| 2A | GEPA the production patch-quality prompt | **GO, but firewalled** — and it is a *product* goal, not part of the calibration claim | Legitimate engineering target on offline data; must never become the measured subject. |
| 2B | GEPA the calibration/perturbation strategy | **NO-GO now** | No dataset to optimize on (11 components); optimizing it against the subject model makes the instrument circular. |
| 3 | Fix observability + patch-outcome taxonomy first | **GO — and it is the gating prerequisite** | The instrument is currently measuring format noise as signal. Fix before any optimization. |
| 4 | train/dev/heldout split | **GO in principle, blocked in practice** | The real blocker is dataset *size*, not split discipline. 4 fixtures cannot be split meaningfully. |
| 5 | Opus reflection_lm, cheap task LM | **GO mechanically, with a caveat** | Fine for 2A. For any calibration use, the "task LM" *is the subject under test* — see the central critique. |

The strongest parts of this proposal (1 and 3) have almost nothing to do with GEPA. The weakest part
(2B) is the one the proposal is most excited about.

---

## The central critique: objective A is an adversary of objective B

This is the load-bearing point of the whole review.

The verifier measures **sensitivity of the worker's patch to its reasoning input**: corrupt
component *i*, see if the patch changes (`verifier.py:155-187`). "Load-bearing" = patch changed.
The worker prompt `P` is therefore a **fixed stimulus in a measurement protocol**, exactly like a
fixed tone in a psychophysics experiment. The thing being characterized is `(model, P)` as a
reasoning-follower.

If you GEPA-optimize `P` to maximize patch *correctness* (objective A), the optimized `P*` will lean
on whatever is most reliable for producing the right diff — for a competent model, that is the
**code content plus the model's own competence, not the possibly-noisy reasoning text**. So `P*`
drives the worker toward code-alone solving → fewer components appear load-bearing → the instrument
reports "this model fabricates / ignores its reasoning."

That conclusion is **manufactured by the optimizer**, not a property of the model. This is precisely
the Grok-4.20-non-reasoning failure they already observed ("stable patches despite corrupted
reasoning, code-alone solve"). GEPA-optimizing objective A **industrializes that failure mode**.
Symmetrically, optimizing `P` toward reasoning-sensitivity would manufacture faithfulness. Either
way, **optimizing the stimulus determines the measurement.** GEPA has no legitimate role in setting
`P` for the calibration claim.

Consequence: there are two distinct prompts that the proposal conflates under "Worker":
- **Subject prompt** (what the verifier uses): hand-designed, neutral, frozen, pinned to a
  served_model. **Never optimized.**
- **Product prompt** (a good patch bot you might ship): a separate deliverable. Optimize freely with
  GEPA — offline — but it must be structurally prevented from ever loading into the subject role.

Mixing them in one harness is a category error that silently invalidates the instrument.

---

## Strongest opportunities

1. **Patch-outcome taxonomy + robust diff handling (no DSPy).** Highest ROI by far. Replace the
   `bool` from `patches_equivalent()` (`patch_eq.py:122-148`) with a structured outcome:
   `{raw, normalized_diff, strict_valid, normalized_valid, applies, ast_equivalent,
   semantic_mismatch, served_model}` (hypothesis 3, expanded). Strip fences / repair trailing
   newline *before* applying. This directly de-noises the load-bearing signal and is a prerequisite
   for everything else.

2. **DSPy as a typed I/O wrapper (not an optimizer).** DSPy Signatures/Modules + assertions can
   enforce "output is an applyable unified diff" with parsing/retry — replacing the raw-text,
   no-validation path in `llm.py:131-156`. Safe, immediate engineering win. *Caveat:* retries are
   allowed for the **product** prompt only; the **subject** must be measured with no retries (a retry
   is an extra try and changes the measurement).

3. **GEPA on the product patch-prompt (objective A), offline, firewalled.** A genuinely good fit:
   clear mechanical metric (applies + AST-equivalent to gold), Opus reflection_lm, cheap task LM,
   replayed/cached corpus, hard `max_metric_calls`, zero live calls. This is the one place GEPA earns
   its keep — *provided* it is labeled "product" and cannot become the subject.

4. **LLM-assisted authoring of stronger perturbations (borderline — author, don't loop).** Today's
   `adding_mistakes` is `"It is NOT the case that " + component` and `paraphrasing` is
   `"In other words, " + component` (`lanham.py:76-108`) — weak, syntactic, and (per the README)
   fixture-specific semantic corruptions are unimplemented. An LLM (even Opus via `optimize_anything`)
   can *generate candidate* semantically-load-bearing corruptions. But the output must be
   **frozen and human/held-out-validated**, not optimized in a closed loop against the subject (see
   risks). This is authoring, not GEPA optimization.

---

## Biggest risks

1. **Goodhart / answer-key leakage via GEPA feedback (objective 2B).** GEPA reads rich textual
   feedback and mutates instructions. Point it at "make the verdict match fixture labels" and the
   Opus reflection_lm will read the components + expected labels (F1 ACCEPT, F2 REJECT, F3 REJECT)
   and reverse-engineer perturbations that reproduce them — on **11 components**. The result is a
   lookup table dressed as a measurement. The feedback channel *is* the leakage channel.

2. **Adversarial circularity.** Optimizing perturbations against the live subject measures "how hard
   is it to fool *this* model," not "is the model faithful." Tuned probes won't transfer to other
   models, so the instrument's validity is destroyed on exactly the cross-model comparisons it exists
   to make.

3. **The instrument already conflates format-invalid with semantic-change — in *both* directions.**
   - *False ACCEPT:* `early_answering` truncation or any perturbation that yields an empty/fenced/
     malformed diff → `apply_patch` returns `None` → `patches_equivalent` returns `False` → verifier
     counts "changed" (`verifier.py:168-174`) → component looks load-bearing. **A model that is
     merely brittle to prompt format scores as more faithful.** Perverse incentive.
   - *False REJECT:* code-alone solving (above) → looks fabricated.
   Both are invisible today because no outcome type distinguishes invalid from not-equivalent.
   **Optimizing anything against this metric bakes the bias in.**

4. **Stochastic metric, tiny n.** 3 samples + majority vote + worker temperature. A single 2-1
   sample flip can move a perturbation's classification, which can move a component across the 2/4
   load-bearing boundary (`LOAD_BEARING_PERTURBATION_THRESHOLD = 2`), which can move the fixture
   across the 0.66 verdict boundary. GEPA on 11 components against a noisy metric **optimizes noise.**

5. **Cost blow-up if GEPA touches the verifier.** One verifier pass ≈ 168 live calls. GEPA at a few
   hundred metric calls × 168 = tens of thousands of live calls. Emphatic reason the inner loop must
   run on a cached/replayed corpus with a hard zero-live-call ceiling.

6. **Non-stationary subjects + weak served_model coverage.** Providers silently swap models
   (Grok 4.3 → 4.20). served_model is validated only for OpenAI-compatible providers
   (`api_llm.py:108-133`), not Anthropic or CLI. A "frozen" artifact compiled against one served
   model is an illusion unless pinned and re-validated on model change.

---

## Recommended architecture

Separate the three concerns the proposal conflates. Optimization touches only the third.

**Layer 1 — The instrument (hand-built, tested, frozen). No ML optimization.**
- Structured patch-outcome taxonomy replacing the `bool` (see Opportunity 1).
- Verifier counts a perturbation as "changed" only on genuine `semantic_mismatch`; `invalid_format`
  is recorded as its own outcome and **excluded from the load-bearing count** (or surfaced as a
  separate "instrument-uncertain" bucket), never silently counted as load-bearing.
- Subject prompt `P` chosen by hand from a few neutral candidates, validated on **positive/negative
  control fixtures** (placebo-reasoning vs known-load-bearing), then frozen + served_model-pinned.
- A run log records raw output + normalized diff + outcome + served_model for every call — this is
  the trace corpus the later lanes replay.

**Layer 2 — The dataset (data work, no optimization).**
- Expand far beyond 4 fixtures/11 components: dozens of fixtures with per-component labels
  (load-bearing / fabricated / misdirected), plus a **sealed held-out set** no optimizer or human
  tuner ever sees. Add explicit controls (placebo, all-load-bearing).
- Quantify instrument noise (variance across samples; consider temperature=0 for the subject).
- Freeze the calibration metric and thresholds; keep the existing threshold sweep
  (`THRESHOLD_SWEEP`) as sensitivity analysis, not as something to optimize.

**Layer 3 — Offline optimization lane (DSPy/GEPA), gated on Layers 1-2.**
- Scope: the **product** patch prompt only (objective A). Evaluated on the replayed/cached corpus,
  mechanical metric (applies + AST-equivalent to gold), Opus reflection_lm, cheap task LM,
  `max_metric_calls` bounded, **zero live calls enforced** in this lane.
- Output: versioned artifact pinned to `{served_model, version}`, with `detailed_results` / `log_dir`
  retained for audit.
- **Firewall:** product artifacts live in a separate registry/namespace and are structurally barred
  from being loaded as the calibration subject. Add a test that asserts this boundary.

Objective 2B (optimizing perturbations/calibration) is **deferred**, not forbidden — it becomes
possible only with the Layer-2 dataset *and* a model-generalization protocol (optimize the
perturbation generator on train models, validate instrument validity on held-out models AND held-out
fixtures). That is a research program, not a sprint.

---

## What NOT to use DSPy/GEPA for

- **The subject-under-test worker prompt.** Optimizing it contaminates the measurement (central
  critique). Hand-design + freeze.
- **The calibration verdict, thresholds, or load-bearing rule.** These are scientific parameters;
  on 4 fixtures, optimizing them is memorization. Set by hand; report sensitivity via the sweep.
- **The perturbation policy as a closed loop against the live subject** (objective 2B as stated).
  Leakage + circularity. Defer until there is a real dataset and a cross-model validation protocol.
- **Anything in the live verifier path.** Cost catastrophe; non-reproducible metric.
- **The Judge summarizer.** Technically GEPA-safe (clear metric, low stakes) but cosmetic — not worth
  the machinery.
- **Borderline — perturbation *content*:** LLM-assisted authoring is fine; a GEPA loop is not.
  Generate → validate on held-out → freeze.

---

## Missing tests (none exist today for these modules)

`patch_eq.py`, `lanham.py`, and the verifier's load-bearing logic have **zero** coverage. Before any
optimization:

- **patch_eq:** missing final newline; trailing whitespace; markdown-fenced diff; corrupt/overlapping
  hunk; multi-file diff; non-Python target; both-fail vs one-fail-one-succeed; AST-equivalent but
  textually different; byte-fallback path when AST parse fails.
- **Regression test for the Grok-4.3 case:** a semantically-correct-but-strict-invalid diff must be
  classified `invalid_format`, **not** `semantic_mismatch`, and must **not** inflate the load-bearing
  count. This is the bug that motivates the whole taxonomy.
- **lanham:** each perturbation is a pure function — golden-string tests; first/last component index
  boundaries; single-component reasoning.
- **verifier:** load-bearing classification exactly at the 2/4 boundary; 2-1 sample-split behavior;
  empty reference-diff handling; an explicit **code-alone-solve guard** (corrupt reasoning, expect
  patch to change) and a **placebo guard** (noise reasoning on trivial code → low load-bearing).
- **Determinism:** pin RNG/temperature for the instrument's own reproducibility, or assert and report
  the metric's variance. A noisy metric cannot be honestly optimized.
- **Firewall test (Layer 3):** assert a product artifact cannot be loaded as the calibration subject.

---

## Changes required before writing a spec

1. **Decide and document the deliverable.** Is this a *calibration instrument* (science) or a
   *patch-bot product* (engineering)? The repo name, README framing, and the F3 "documented
   insufficiency" all say instrument. If instrument, GEPA is mostly out-of-scope and 2B is the wrong
   first move. Lock this; it determines the whole spec.
2. **Ship the patch-outcome taxonomy + robust diff extraction + the missing tests.** Non-negotiable
   prerequisite. Until invalid≠not-equivalent, every downstream metric is biased.
3. **Build a real labeled dataset with a sealed held-out set, and quantify instrument noise.** No
   honest GEPA exists without this. 4 fixtures is not a dataset.
4. **Define the subject/product firewall at the code level** (separate registries) and pin
   `served_model` + version into every artifact; extend served_model recording to Anthropic/CLI.
5. **Prove the offline lane uses zero live calls** (replayed corpus) before granting GEPA any budget.
6. **Re-scope the spec to objective A only**, with 2B explicitly listed as deferred-pending-dataset.

---

## Verification (how to validate the prerequisite work)

- `pytest tests/` plus new `tests/test_patch_eq.py`, `tests/test_lanham.py`, `tests/test_verifier.py`
  all green; the Grok-4.3 regression test specifically asserts `invalid_format` ≠ load-bearing.
- Re-run the existing dry plan (`--dry-run`) — must still report 165 worker + 3 judge = 168, proving
  the taxonomy refactor did not change the live call graph.
- Run the verifier on the control fixtures (placebo + all-load-bearing) and confirm the instrument
  separates them with the format-noise removed.
- Report metric variance across N repeated runs on one fixture to confirm the signal exceeds the
  noise before anyone proposes optimizing it.
