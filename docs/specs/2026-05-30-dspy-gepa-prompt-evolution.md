# DSPy/GEPA Prompt Evolution Architecture Spec

> Status: draft, reconciled with the current working tree after repository inspection, DSPy/GEPA research, and two Opus reviews.
>
> Primary decision: `arena-calibration` is first a calibration instrument, not a patch-bot product. DSPy/GEPA may enhance the project, but only behind a strict subject/product firewall.

## 1. Goal

Architect where DSPy and GEPA can enhance `arena-calibration` without invalidating the verifier's measurement.

The desired end state is:

1. a more reliable calibration instrument with structured patch-comparison outcomes and auditable traces,
2. governed, frozen subject prompts and perturbation stimuli,
3. a separate product-only prompt-optimization lane using DSPy/GEPA, and
4. a clear implementation plan that does not optimize the subject-under-test prompt, verifier thresholds, or load-bearing rule.

## 2. Current repository facts

Confirmed in this checkout:

- Worker/Judge protocols live in `arena/llm.py`.
- The Worker contract is `regenerate_patch(file_contents, reasoning, target_path) -> str`.
- `arena/llm.py` contains the worker prompt contract. The current system prompt already uses a constrained senior-engineer framing and tells the model the reasoning artifact is authoritative.
- `arena/runner.py` already has live-provider guards:
  - `--dry-run`,
  - `--confirm-live`,
  - `--max-model-calls`,
  - provider choices: `anthropic`, `xai`, `gemini`, `openrouter`, `claude-code`, `codex`, `copilot`.
- Current fixture component counts:
  - F1: 4 components,
  - F2: 4 components,
  - F3: 5 components,
  - promoted total: 13 components.
- Current dry-run budget for F1-F3 is 165 worker calls + 3 judge calls = 168 total model calls.
- `arena/patch_eq.py` already has a structured comparison taxonomy:
  - `PatchComparisonStatus.EQUIVALENT`,
  - `PatchComparisonStatus.SEMANTIC_MISMATCH`,
  - `PatchComparisonStatus.INDETERMINATE_BOTH_FAILED`,
  - `PatchComparisonStatus.INDETERMINATE_APPLY_FAILED`.
- `arena/patch_eq.py` already has `normalize_patch_diff()`, including CRLF normalization, markdown diff-fence stripping, exactly-one-final-newline normalization, and sandbox target-path validation.
- The legacy `patches_equivalent()` wrapper still collapses indeterminate comparisons to `False`; calibration code should use `compare_patches()` instead.
- `arena/verifier.py` currently imports `compare_patches()` and includes indeterminate accounting fields such as `sample_diffs_indeterminate` and `majority_comparison`.
- `arena/fixtures.py` already loads `Fixture.reasoning_corruptions`, and all four fixture manifests currently populate corruption data parallel to `reasoning_components`.
- `arena/lanham.py` currently supports fixture-specific corruptions for `adding_mistakes`; its fallback is `It is NOT the case that ...`, and filler now uses `[step omitted: reasoning for this component is unavailable]` rather than `...`.
- `tests/test_prompt_optimization.py` exists as the current RED/GREEN driver for prompt-contract, corruption, diff-normalization, and indeterminate-comparison behavior.
- `dspy` and `gepa` are not installed in the core project environment. They should remain optional dependencies.
- The implementation branch has a local verification baseline: `uv run --extra dev pytest tests -q`, `uv run --extra dev python exercise_verifier.py`, and `uv run --extra dev python -m arena.runner --llm-provider xai --dry-run`.

## 3. Research summary

DSPy:

- DSPy represents LM programs declaratively with Signatures, Modules, and Metrics.
- DSPy optimizers tune prompts/instructions/few-shot examples against user-provided metrics.
- Relevant optimizers include MIPROv2 and GEPA.
- DSPy is useful when the task can be expressed as structured inputs/outputs plus a mechanical or feedback-rich metric.

GEPA:

- GEPA means Genetic-Pareto.
- In DSPy, `dspy.GEPA` is a reflective instruction optimizer.
- It uses metrics that can return `dspy.Prediction(score=..., feedback=...)`; rich textual feedback reaches the reflection model.
- It mutates textual components such as prompts, samples from a Pareto frontier, and supports bounded runs with `max_metric_calls`, `reflection_lm`, `track_stats`, `log_dir`, and detailed candidate results.
- GEPA is strongest when failures can be explained with rich diagnostics: parse errors, diff validation failures, unit-test output, AST mismatch details, tool traces, and per-objective scores.
- Standalone `gepa.optimize_anything` can optimize arbitrary text artifacts, but DSPy is the cleaner fit for LM prompt programs.

Research implication:

- Arena has strong mechanical patch-quality metrics, making DSPy/GEPA attractive for product prompt optimization.
- Arena's calibration measurement is fragile to prompt optimization. The prompt is part of the measurement stimulus; optimizing it can manufacture either reasoning-sensitivity or code-alone solving.

## 4. Opus review conclusions incorporated

Two Opus passes were run:

- Research/architecture review: `docs/verification/2026-05-30-opus-dspy-gepa-research-review.md`.
- Final spec/plan review: `docs/verification/2026-05-30-opus-dspy-gepa-final-review.md`.

Accepted review conclusions:

1. Keep the calibration subject prompt hand-designed, neutral, frozen, and served-model/version pinned.
2. Do not use GEPA to tune the subject prompt, verifier verdict, thresholds, or load-bearing rule.
3. Keep DSPy/GEPA out of the live verifier path.
4. Scope near-term GEPA to product patch-quality prompt evolution only.
5. Gate product GEPA on a real, separately sourced dataset; do not train on the calibration benchmark fixtures.
6. Treat fixture-specific reasoning corruptions as measurement stimuli requiring governance, blind authoring, provenance, and held-out validation.
7. Use the existing `compare_patches()` taxonomy as the foundation; do not fork a duplicate `patch_outcome.py` unless a future single-patch quality classifier is justified.

## 5. Core architecture

The project should have three layers.

### Layer 1: Calibration instrument, no optimization

Purpose:

- Measure reasoning-dependence under frozen subject prompt and frozen perturbation policy.
- Produce auditable traces and structured outcomes.

Rules:

- No DSPy/GEPA optimizer in the live verifier path.
- No retry loop for subject Worker calls; retries change the measurement.
- No optimized product prompt can be used as the subject prompt.
- Invalid/apply-failed diff output is indeterminate, not semantic mismatch, and must not silently count as load-bearing.
- Every live call should record provider, requested model, served model where available, prompt hash, raw output hash/path, normalized diff/comparison status, and perturbation metadata.

Current foundation:

- Keep extending `arena/patch_eq.py`, especially `compare_patches()` and `PatchComparisonStatus`.
- Keep verifier migration centered on `compare_patches()` and indeterminate accounting.
- Do not add a parallel comparison module unless there is a distinct, tested single-output classification requirement.

Verifier interpretation:

- `EQUIVALENT`: candidate patch is semantically equivalent to the reference patch.
- `SEMANTIC_MISMATCH`: candidate patch applies and differs semantically from the reference patch; this can count toward load-bearing.
- `INDETERMINATE_BOTH_FAILED` and `INDETERMINATE_APPLY_FAILED`: candidate/reference comparison is not a trustworthy reasoning-dependency signal; record and exclude from changed-patch counts.

### Layer 2: Governed datasets and trace corpus

Purpose:

- Provide enough examples for product prompt optimization and instrument validation.
- Avoid tuning on the calibration benchmark fixtures.
- Preserve run evidence for later replay and diagnosis.

Trace artifacts to add:

- `results/<run_id>/calls/<call_id>.json`
- `results/<run_id>/raw/<call_id>.txt`

Trace fields:

- provider,
- requested model,
- served model or explicit `unverified_cli_model`,
- fixture id,
- component index,
- perturbation kind,
- sample index,
- prompt hash,
- raw output path/hash,
- normalized diff hash,
- comparison status,
- timestamps.

Product optimization datasets:

- `datasets/patch_quality/train.jsonl`
- `datasets/patch_quality/dev.jsonl`
- `datasets/patch_quality/heldout.jsonl`

Dataset rules:

- Do not use the calibration benchmark fixtures as product training data.
- Do not optimize on sealed held-out fixtures.
- Record provenance for each example: external corpus, hand-authored, generated, or live trace.
- Product GEPA is not runnable until a real separately sourced train/dev/heldout split exists.

Reasoning-corruption governance:

- `reasoning_corruptions` are measurement stimuli, not implementation details.
- Corruptions should be authored from component meaning without looking at desired aggregate verifier fractions when possible.
- Corruptions require provenance metadata and review status.
- Corruptions should be validated on at least one held-out subject model before instrument numbers are treated as stable.
- Once accepted, corruptions are frozen with fixture version metadata.

### Layer 3: Offline/product optimization lane with DSPy/GEPA

Purpose:

- Improve a product patch-regeneration prompt for valid, applyable, semantically correct diffs.
- Produce versioned product prompt artifacts and optimization audit trails.

Rules:

- Product-only. Never load optimized artifacts into the calibration-subject role.
- Not part of normal `arena.runner` verifier execution.
- Live optimization requires explicit confirmation and a model-call/metric-call ceiling.
- Dry-run mode must work without credentials and without live calls.
- Opus can be used as `reflection_lm` when explicitly authorized; cheap/local task LMs should be preferred for frequent task rollouts.

New modules/scripts when implementation proceeds:

- `arena/prompt_registry.py`
  - loads frozen subject prompt artifacts and product prompt artifacts from separate namespaces,
  - enforces role separation,
  - verifier can load only `role: calibration_subject`.
- `arena/run_artifacts.py`
  - writes per-call trace JSON and raw output text.
- `arena/optimization/datasets.py`
  - JSONL load/validate helpers.
- `arena/optimization/dspy_programs.py`
  - `PatchFromReasoning` signature,
  - `PatchCompiler` product module.
- `arena/optimization/metrics.py`
  - `patch_quality_metric()` returning `dspy.Prediction(score, feedback)` when DSPy is installed.
- `tools/optimize_patch_prompt.py`
  - product-only GEPA driver.

Prompt artifact namespaces:

- `prompts/subject/worker_v1.yaml`
- `prompts/product/patch_compiler_seed_v1.yaml`
- `prompts/product/optimized/<run_id>.json`

## 6. Exactly where to use DSPy/GEPA

Use DSPy now for:

1. Product patch prompt module definition.
2. Structured product metrics around `compare_patches()` and patch application.
3. Optional typed output/retry wrappers in product workflows only.
4. Product prompt artifact save/load experiments.

Use GEPA now for:

1. Product patch-quality prompt evolution against a real train/dev corpus.
2. Comparing product prompt candidates under bounded, auditable metric calls.
3. Mining failure feedback from patch-comparison taxonomy and traces.

Use Opus now for:

1. Independent research/spec/plan reviews.
2. GEPA reflection model for explicitly authorized product-prompt optimization runs.
3. One-off authoring/review of fixture-specific perturbation candidates, with governance.

Do not use DSPy/GEPA now for:

1. The subject-under-test Worker prompt.
2. The verifier's load-bearing rule or thresholds.
3. Closed-loop perturbation optimization against current fixtures or one subject model.
4. Live verifier execution.
5. Judge summary wording, unless later proved consequential.

Defer GEPA for perturbation policy until:

- there are dozens of labeled fixtures,
- there is a sealed held-out set,
- there are held-out subject models,
- the `reasoning_corruptions` governance process is in place,
- the outcome taxonomy and trace corpus are stable,
- cross-model validity can be measured,
- there is a clear anti-leakage protocol.

## 7. Safety and reproducibility

Live cost controls:

- Keep `--dry-run` and `--max-model-calls` mandatory for live verifier runs.
- Add `--confirm-live-optimization` and `--max-metric-calls` for optimization commands.
- Print planned task-LM calls, reflection-LM calls, worst-case output tokens, provider, model, and rough token exposure before live optimization.

Credential hygiene:

- Do not write API keys to artifacts.
- Store request headers nowhere.
- Redact known env values and common key patterns from metadata.

Served-model pinning:

- OpenAI-compatible API providers currently validate `served_model` in `arena/api_llm.py`; preserve that.
- Anthropic and CLI providers should record requested model plus explicit served-model status:
  - `served_model` when provider exposes it,
  - `unverified_api_model` or `unverified_cli_model` otherwise.
- Prompt artifacts must include the model/provider they were authored or optimized against.

Artifact firewall:

- Subject artifacts have `role: calibration_subject`.
- Product artifacts have `role: product_patch_compiler`.
- The registry must reject role mismatches.
- The verifier call path must reject any non-subject prompt artifact, not just rely on registry tests.

## 8. Acceptance criteria

The architecture is implemented when:

1. Existing prompt/corruption/diff-normalization tests in `tests/test_prompt_optimization.py` pass.
2. Verifier uses `compare_patches()` and no longer counts indeterminate format/apply failures as semantic load-bearing changes.
3. `_majority_diff` behavior for all-indeterminate sample sets is explicitly tested.
4. Per-call artifacts can be saved for live runs without leaking keys.
5. Subject/product prompt registry exists and enforces the role firewall at both registry and verifier call paths.
6. `reasoning_corruptions` have provenance/governance metadata or an explicit temporary-experimental marker.
7. Product dataset JSONL loaders validate train/dev/heldout examples and forbid benchmark-fixture training data by default.
8. DSPy/GEPA dependencies are optional and imports are isolated to the optimization lane.
9. `tools/optimize_patch_prompt.py --dry-run` reports planned calls and exits without credentials.
10. A fake-GEPA/fake-DSPy test proves optimized product artifacts can be saved but cannot be used as subject prompts.
11. Existing verification commands remain green:
    - `uv run --extra dev pytest tests -q`,
    - `uv run --extra dev python exercise_verifier.py`,
    - `uv run --extra dev python -m arena.runner --llm-provider xai --dry-run`.
12. Any live optimization run is separately authorized and records a complete audit bundle.

## 9. Open questions

1. Should indeterminate output make a verifier fixture `uncertain` rather than accept/reject? Recommended near term: keep verdicts but add quality notes and artifact counts; revisit after tests.
2. How large must the dataset be before perturbation-policy research is meaningful? Recommended minimum: dozens of fixtures and multiple subject models.
3. Should product-prompt GEPA use `dspy.GEPA` or standalone `gepa.optimize_anything` first? Recommended: use `dspy.GEPA` for LM prompt optimization; reserve standalone GEPA for non-LM text artifacts.
4. Which cheap task LM should be first for product prompt optimization? Recommended: start with fake/local or xAI under a tiny budget; use Opus only for reflection/review when authorized.
5. Should `N_SAMPLES=3` remain when the subject Worker temperature is 0? Recommended: document why it remains for provider variance and non-zero-temperature experiments, or reduce it in a separate measured change.
