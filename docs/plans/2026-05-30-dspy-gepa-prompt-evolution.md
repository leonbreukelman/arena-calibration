# DSPy/GEPA Prompt Evolution Implementation Plan

> **For Hermes:** Follow strict TDD. Do not add DSPy/GEPA to the live verifier path. Do not optimize the calibration-subject prompt. Do not run live model optimization without explicit authorization, a metric-call ceiling, and a budget guard.

**Goal:** Implement the safe DSPy/GEPA architecture in `docs/specs/2026-05-30-dspy-gepa-prompt-evolution.md`: harden the calibration instrument, govern perturbation stimuli, add trace artifacts, add a subject/product prompt firewall, then add an optional product-only DSPy/GEPA lane.

**Current-state note:** This plan is reconciled with the current working tree, not pristine `origin/main`. The tree already contains in-progress changes for prompt-contract strengthening, fixture-specific corruptions, patch diff normalization, structured `compare_patches()`, verifier indeterminate accounting, and `tests/test_prompt_optimization.py`. Phase 0 verifies that state instead of pretending the repository is clean.

---

## Review status

Research/architecture Opus review:

- Artifact: `docs/verification/2026-05-30-opus-dspy-gepa-research-review.md`
- Verdict: conditional GO on plumbing and product/offline prompt optimization; NO-GO on GEPA-for-calibration now.

Final Opus spec/plan review:

- Artifact: `docs/verification/2026-05-30-opus-dspy-gepa-final-review.md`
- Verdict: `ACCEPT_WITH_CHANGES`.
- Incorporated changes:
  - rebase the docs on the current tree,
  - use existing `patch_eq.compare_patches()` rather than creating duplicate `patch_outcome.py`,
  - acknowledge and use `tests/test_prompt_optimization.py`,
  - enforce product dataset gates,
  - govern `reasoning_corruptions`,
  - assert firewall at the verifier path.

## Phase 0: Verify current baseline and loose ends

### Task 0.1: Capture current status and run focused existing tests

**Objective:** Establish the true current state before adding new features.

**Files:** none.

**Commands:**

```bash
git status --short --branch
uv run --extra dev pytest tests/test_prompt_optimization.py -q
uv run --extra dev pytest tests -q
uv run --extra dev python exercise_verifier.py
uv run --extra dev python -m arena.runner --llm-provider xai --dry-run
```

**Expected:**

- The implementation branch may be dirty while this plan is being executed; final handoff should leave no untracked or unstaged loose ends.
- `tests/test_prompt_optimization.py` is the focused driver for the current prompt/corruption/normalization/indeterminate behavior.
- Dry-run should still report 168 planned model calls for F1-F3 unless a deliberate fixture/component-count change is made.

### Task 0.2: Decide whether to commit/rebase current in-progress code before proceeding

**Objective:** Avoid mixing architecture docs with unrelated implementation changes.

**Options:**

1. Commit the existing prompt/corruption/patch_eq/verifier migration first.
2. Continue in one branch but keep docs and implementation commits separate.
3. If using worktrees, split the docs/spec pass from code implementation.

**Acceptance:** The PR/commit history makes clear which changes are docs, instrument hardening, and optional optimization scaffolding.

## Phase 1: Complete and harden patch comparison / verifier migration

### Task 1.1: Keep structured comparison in `arena/patch_eq.py`

**Objective:** Use and extend the existing taxonomy instead of creating a duplicate module.

**Current foundation:**

- `PatchComparisonStatus`
- `PatchComparison`
- `normalize_patch_diff()`
- `apply_patch()`
- `compare_patches()`
- legacy `patches_equivalent()`

**Required tests:**

- Existing: `test_fenced_diff_missing_final_newline_is_normalized_before_apply`.
- Existing: `test_compare_patches_classifies_unappliable_outputs_as_indeterminate_not_changed`.
- Add if missing:
  - inline Grok-4.3-style semantically-correct diff missing final newline is normalized before `patch` application,
  - corrupt hunk remains indeterminate rather than semantic mismatch,
  - both-fail and one-fail statuses remain distinct,
  - multi-file or unsupported diffs fail explicitly if not supported.

**Commands:**

```bash
uv run --extra dev pytest tests/test_prompt_optimization.py -q
```

### Task 1.2: Verify `_majority_diff` behavior for all-indeterminate samples

**Objective:** Ensure unapplyable samples cannot form a bogus semantic majority.

**Files:**

- Modify/add tests in `tests/test_prompt_optimization.py` or create `tests/test_verifier_patch_comparisons.py`.

**Test cases:**

- All three candidate diffs are unapplyable: majority comparison is indeterminate and changed count is zero.
- Mixed valid semantic mismatch and indeterminate samples: only valid semantic mismatches count as changed samples; majority behavior is documented and deterministic.

**Implementation target:**

- `arena/verifier.py::_majority_diff()` and `_component_verdict()`.

### Task 1.3: Preserve verifier indeterminate accounting

**Objective:** Ensure format/apply failures are excluded from load-bearing change counts but surfaced in notes.

**Existing driving test:**

- `test_verifier_does_not_count_apply_failures_as_load_bearing_changes`.

**Required behavior:**

- `PerturbationOutcome.sample_diffs_indeterminate` counts indeterminate sample comparisons.
- `PerturbationOutcome.majority_comparison` records comparison status.
- `ComponentVerdict.perturbations_indeterminate` counts indeterminate perturbation majorities.
- Report notes include `indeterminate patch comparisons` when any exist.
- Live fractions may change after this fix; fake valid-diff exercise fractions should remain expected.

**Commands:**

```bash
uv run --extra dev pytest tests/test_prompt_optimization.py -q
uv run --extra dev python exercise_verifier.py
```

## Phase 2: Govern prompt contract and reasoning corruptions

### Task 2.1: Freeze subject prompt contract

**Objective:** Keep the subject prompt explicit but not optimizer-tuned.

**Existing driving test:**

- `test_regen_prompt_contract_makes_reasoning_authoritative_and_calibration_safe`.

**Acceptance:**

- Prompt says the reasoning artifact is authoritative.
- Prompt says file contents are for location and patch-application context.
- Prompt warns not to infer a fix from file contents alone.
- Prompt has strict diff output constraints including no prose/fences and exactly one trailing newline.

### Task 2.2: Add governance metadata for `reasoning_corruptions`

**Objective:** Treat corruptions as measurement stimuli with provenance, not ad hoc implementation details.

**Files:**

- Modify: fixture manifests, or add sidecar docs under `fixtures/<id>/corruptions.md`.
- Modify: `arena/fixtures.py` if manifest schema is extended.
- Add tests in `tests/test_prompt_optimization.py` or `tests/test_fixtures.py`.

**Suggested manifest fields:**

```yaml
reasoning_corruption_governance:
  authoring_mode: hand_authored_semantic_inversion
  blinded_to_expected_fraction: false
  reviewer: pending
  heldout_model_validation: pending
  frozen: false
```

**Acceptance:**

- Loader validates governance metadata or marks fixtures as experimental.
- Docs state that current fixture numbers are not final instrument-validity claims until corruptions are reviewed/frozen.
- Corruptions remain parallel to `reasoning_components`.

### Task 2.3: Add control/placebo and code-alone-solve guard tests

**Objective:** Detect the two major instrument failure modes.

**Test cases:**

- Placebo/noise reasoning on trivial code yields low load-bearing and/or scorer rejection.
- A fake code-alone solver returns the reference patch despite corrupted reasoning; verifier flags low reasoning-dependence rather than accepting faithfulness.
- Paraphrase control changes are reported as brittle.

**Files:**

- Add tests under `tests/test_verifier_controls.py` or extend `tests/test_prompt_optimization.py`.

## Phase 3: Trace artifact capture

### Task 3.1: Write RED tests for call trace writer

**Objective:** Define auditable per-call artifacts without involving live providers.

**Files:**

- Create: `tests/test_run_artifacts.py`

**Test cases:**

- Trace writer saves metadata JSON and raw response text under a run directory.
- Secret-shaped strings are redacted from metadata.
- Raw response can be stored exactly or disabled by flag.
- Artifact paths are stable and collision-safe.
- `served_model` can be one of:
  - provider-confirmed model id,
  - `unverified_api_model`,
  - `unverified_cli_model`.

### Task 3.2: Implement `arena.run_artifacts`

**Files:**

- Create: `arena/run_artifacts.py`

**Requirements:**

- Dataclass `ModelCallTrace` with provider, requested_model, served_model_status, fixture_id, component_index, perturbation, sample_index, prompt hash, raw output path/hash, normalized diff hash, comparison status, timestamps.
- Redaction helper for common API key patterns and explicit env values.
- JSON writer using only stdlib.

### Task 3.3: Thread trace capture through verifier/runner behind a flag

**Files:**

- Modify: `arena/verifier.py`
- Modify: `arena/runner.py`

**Behavior:**

- Add `--trace-dir` to runner.
- If enabled, save one call artifact per Worker/Judge call.
- Dry-run remains no-network and no trace output.

**Verification:**

```bash
uv run --extra dev pytest tests -q
uv run --extra dev python -m arena.runner --llm-provider xai --dry-run
```

## Phase 4: Prompt registry and subject/product firewall

### Task 4.1: Write RED prompt registry tests

**Files:**

- Create: `tests/test_prompt_registry.py`

**Test cases:**

- Load subject artifact with `role: calibration_subject` succeeds for subject use.
- Load product artifact with `role: product_patch_compiler` succeeds for product use.
- Loading product artifact as subject raises a typed error.
- Verifier call path rejects any non-subject prompt artifact.
- Artifact must include `artifact_version`, `role`, `prompt_name`, `system`, `user_template`, and model/provenance metadata.

### Task 4.2: Implement prompt registry and seed artifacts

**Files:**

- Create: `arena/prompt_registry.py`
- Create: `prompts/subject/worker_v1.yaml`
- Create: `prompts/product/patch_compiler_seed_v1.yaml`

**Requirements:**

- Use PyYAML already in project dependencies.
- Subject artifact mirrors current `_REGEN_SYSTEM` / `_REGEN_USER_TEMPLATE` initially.
- Product seed can use stronger patch-product wording, but remains firewalled.
- Verifier accepts only `role: calibration_subject` if prompt artifacts are introduced into its path.

## Phase 5: Product optimization dataset scaffolding

### Task 5.1: Write RED tests for JSONL dataset loader

**Files:**

- Create: `tests/test_optimization_datasets.py`

**Test cases:**

- Valid JSONL example loads to dataclass.
- Missing required fields fails with helpful error.
- Duplicate `example_id` fails.
- Heldout split is never accepted as train unless explicitly overridden.
- Benchmark fixtures under `fixtures/` are rejected as product training sources by default.

### Task 5.2: Implement dataset helpers

**Files:**

- Create: `arena/optimization/__init__.py`
- Create: `arena/optimization/datasets.py`
- Create: `datasets/patch_quality/README.md`

**Requirements:**

- Keep `dspy` imports out.
- Use dataclasses and stdlib JSON.
- Support train/dev/heldout split names.
- Record provenance and source policy.

### Task 5.3: Populate a real product dataset before GEPA

**Objective:** Prevent overfitting to calibration fixtures.

**Requirements:**

- Source examples separately from the calibration benchmark.
- Include train/dev/heldout split.
- Include expected diff or expected patched source.
- Document provenance.

**Gate:** Phase 8/9 product GEPA is not runnable until this task is complete.

## Phase 6: Optional DSPy/GEPA dependency lane

### Task 6.1: Add optional optimization extra

**Files:**

- Modify: `pyproject.toml`
- Create: `tests/test_optimization_imports.py`

**Behavior:**

```toml
[project.optional-dependencies]
optimization = [
  "dspy>=3.0",
  "gepa>=0.1",
]
```

- Core tests must not require optimization extra.
- Optimization modules raise helpful errors when optional dependencies are missing.

### Task 6.2: Add DSPy product patch program with fakes/monkeypatches

**Files:**

- Create: `tests/test_dspy_patch_program.py`
- Create: `arena/optimization/dspy_programs.py`

**Test cases:**

- `PatchFromReasoning` signature exposes `target_path`, `file_contents`, `reasoning`, `diff`.
- `PatchCompiler` returns `diff` from the underlying predictor.
- Product prompt instructions come from product prompt artifact.
- Subject artifacts are rejected by product optimizer if the role is wrong.

**Rules:**

- Lazy import `dspy`.
- No optimizer invocation here.
- No connection to `arena.verifier`.

## Phase 7: GEPA metric and optimizer driver

### Task 7.1: Add GEPA-friendly patch-quality metric

**Files:**

- Create: `tests/test_optimization_metrics.py`
- Create: `arena/optimization/metrics.py`

**Test cases:**

- AST-equivalent patch gets high/perfect score.
- Markdown-fenced but normalized-valid patch gets lower score plus feedback mentioning fence if that metadata is available.
- Invalid diff gets low score plus exact diagnostic feedback.
- Semantic mismatch gets low score plus mismatch status.

**Rules:**

- Metric is deterministic.
- Metric uses mechanical patch comparison, not LLM-as-judge.
- Metric returns `dspy.Prediction(score=..., feedback=...)` when DSPy is installed.

### Task 7.2: Add optimizer CLI budget gates

**Files:**

- Create: `tests/test_optimize_patch_prompt_cli.py`
- Create: `tools/optimize_patch_prompt.py`

**CLI behavior:**

- `--dry-run` prints dataset sizes, max metric calls, task model, reflection model, and exits without credentials.
- Missing `--confirm-live-optimization` aborts before constructing DSPy LM or GEPA.
- `--max-metric-calls` is required for live optimization.
- Output artifact role is always `product_patch_compiler`.
- Refuse to run when train/dev/heldout dataset gate is not satisfied.

**Suggested flags:**

```bash
--trainset datasets/patch_quality/train.jsonl
--valset datasets/patch_quality/dev.jsonl
--seed-prompt prompts/product/patch_compiler_seed_v1.yaml
--task-model ...
--reflection-model opus
--max-metric-calls N
--dry-run
--confirm-live-optimization
--output prompts/product/optimized/<run_id>.json
--log-dir results/optimization/<run_id>
```

## Phase 8: Non-live proof

### Task 8.1: Run full hermetic verification

**Commands:**

```bash
git diff --check
uv run --extra dev pytest tests/test_prompt_optimization.py -q
uv run --extra dev pytest tests -q
uv run --extra dev python exercise_verifier.py
uv run --extra dev python -m arena.runner --llm-provider xai --dry-run
uv run --extra dev python tools/optimize_patch_prompt.py --dry-run --trainset datasets/patch_quality/train.jsonl --valset datasets/patch_quality/dev.jsonl --seed-prompt prompts/product/patch_compiler_seed_v1.yaml --task-model fake --reflection-model opus --max-metric-calls 10
```

**Expected:**

- The first four commands pass once instrument hardening is complete.
- The optimizer dry-run must refuse to run if the real product dataset gate is not satisfied; that refusal is a pass until Task 5.3 is complete.

## Phase 9: Optional bounded live product optimization

### Task 9.1: Ask for explicit authorization

**Objective:** Do not spend Opus/task-provider quota without a fresh explicit go-ahead.

**Required operator decisions:**

- Product dataset to use.
- Task LM/provider/model.
- Reflection LM/provider/model; Opus if desired.
- Max metric calls.
- Max dollar budget if using Claude/API.
- Whether raw prompt/response traces may be saved.

### Task 9.2: Run one tiny live smoke only after authorization and dataset gate

**Example shape, not pre-authorized by this plan:**

```bash
uv run --extra dev --extra optimization python tools/optimize_patch_prompt.py \
  --trainset datasets/patch_quality/train.jsonl \
  --valset datasets/patch_quality/dev.jsonl \
  --seed-prompt prompts/product/patch_compiler_seed_v1.yaml \
  --task-model xai/grok-4.3 \
  --reflection-model anthropic/opus \
  --max-metric-calls 10 \
  --confirm-live-optimization \
  --output prompts/product/optimized/smoke.json \
  --log-dir results/optimization/smoke
```

**Expected:** Product artifact saved with `role: product_patch_compiler`; artifact cannot be loaded as subject prompt.

## Phase 10: Documentation and final checks

### Task 10.1: Update README

**Files:**

- Modify: `README.md`

**Content:**

- Structured patch comparison and indeterminate behavior.
- Trace capture usage.
- Subject/product prompt firewall.
- Reasoning-corruption governance.
- Optional optimization extra.
- GEPA lane is product-only and dataset-gated.

### Task 10.2: Final verification

**Commands:**

```bash
git diff --check
uv run --extra dev pytest tests -q
uv run --extra dev python exercise_verifier.py
uv run --extra dev python -m arena.runner --llm-provider xai --dry-run
git status --short --branch
```

**Acceptance:**

- Tests pass.
- Dry-run call count remains explainable.
- No secrets in diff.
- New artifacts are intentional and documented.

## Explicit non-goals

- Do not optimize the calibration-subject prompt.
- Do not change fixture ground truth to make live models look better.
- Do not use GEPA to tune verifier thresholds.
- Do not run full 168-call live verifier inside GEPA.
- Do not treat invalid diff formatting as semantic load-bearing.
- Do not make DSPy/GEPA required dependencies for core harness usage.
- Do not train product prompt optimization on the calibration benchmark fixtures.
