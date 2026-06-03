# arena-calibration

Calibration harness for the build-arena Verifier and Scorer. Holds a frozen
set of hand-crafted fixtures with labeled ground truth, exercises the Scorer
and Verifier against them, reports a discrimination matrix.

Repo identity: `arena-calibration` is the calibration-harness repo. The
separate `build-arena` repo is the main autonomous build/improvement loop.
References to `build-arena` in this README describe the system being
calibrated, not the local checkout name for this harness.

## Axiom

Every claim the agent makes must be verifiable by something that is not the
agent. The Verifier is one such component. This repo asks: does the Verifier
discriminate load-bearing reasoning from decorative reasoning on inputs
where ground truth is known by construction?

## Fixture taxonomy

### Patch-oriented Scorer/Verifier fixtures

| Kind                 | Scorer should | Verifier should |
| -------------------- | ------------- | --------------- |
| `load_bearing_good`  | promote       | accept          |
| `fabricated_good`    | promote       | reject          |
| `bad_passes_tests`   | promote*      | reject          |
| `trivial`            | reject        | n/a             |
| `goodhart` (6-set)   | promote       | reject          |
| `bad_fails_tests` (6-set) | reject   | n/a             |

*Scorer is fooled by construction; Verifier is the catch.

### Project Model v0 advisory-signal fixtures

The Project Model fixture set lives under `fixtures/project_model_v0/` so the
legacy patch-fixture loader continues to see only the four patch fixtures. These
fixtures target the parent contract documented in build-arena issue #2 and
`docs/schemas/project-model-v0.schema.json` on branch `issue-2-project-model-v0`;
this repo stores calibration examples and compatibility checks, not a competing
Project Model spec. Each Project Model fixture stores:

- `project_model.json` using parent-contract `schemaVersion: project-model/v0`;
- `proposal.md` / `public_rationale.md` for the pre-code candidate;
- `expected_advisory_signal.json` for the Elenchus advisory signal expected by
  calibration;
- `observed_advisory_signal.json` as the fixture-local hermetic stand-in for a
  future Elenchus output;
- `manifest.yaml` with expected F-label, deep-verification expectation, and an
  explanation of why the label is correct.

| Label | Fixture intent | Signal expectation |
| ----- | -------------- | ------------------ |
| F1 | Aligned, load-bearing, model-consistent reasoning | components aligned; near-neighbors distinguished |
| F2 | Decorative/fake/non-load-bearing rationale | unsupported/not-addressed components; evidence gaps |
| F3 | Real/load-bearing rationale aimed at the wrong target, component, sequence, level, or too-narrow visible example | specific misalignment / dependency / near-neighbor signals, not fake-rationale collapse |
| F4 | Weak/trivial proposal rejected before expensive or deep verification | not-addressed components and missing evidence; `expected_deep_verification: false` |

F3 is pre-code proposal-reasoning failure. Code patches are only one example.
The Project Model fixtures include both a code-adjacent too-narrow tokenizer
case and a non-code process/sequence case.

## Status

- [x] F1 load_bearing_good
- [x] F2 fabricated_good
- [x] F3 bad_passes_tests
- [x] F4 trivial
- [x] Project Model v0 F1/F2/F3/F4 advisory-signal fixtures
- [x] Project Model v0 hermetic signal checker
- [x] Scorer
- [x] Runner
- [x] Verifier (Lanham four-test, Haiku-driven worker, Opus judge)

## Operating the Verifier

The patch-fixture hermetic exercise requires no network and no API key. It
drives the Verifier through F1, F2, F3 with deterministic scripted workers.

```
python exercise_verifier.py
```

The Project Model advisory-signal fixtures are also hermetic. They compare
fixture-local scripted advisory signals against the expected signal shape and
run a Project Model quality/meta-F3 guard. This is a checker for fixture and
signal compatibility, not a live Elenchus call and not a truth oracle.

```
python exercise_project_model_fixtures.py
python exercise_project_model_fixtures.py --json
python exercise_project_model_fixtures.py --observed-dir path/to/elenchus-signals
```

When `--observed-dir` is supplied, the checker reads `<fixture-id>.json` files
from that directory and compares those actual Elenchus-style outputs against the
fixture expectations. Without it, the fixture-local `observed_advisory_signal.json`
files provide the hermetic default.

Live runs consume paid API capacity or subscription quota. The runner fails
closed unless `--confirm-live` is supplied. Inspect call count and budget
exposure first:

```
python -m arena.runner --llm-provider xai --dry-run
```

### API-backed live providers

Recommended budget-sensitive path is xAI first. The observed xAI Models API
exposed `grok-4.3`; this runner defaults xAI worker and judge calls to that
model unless `--worker-model` / `--judge-model` override it.

```
export XAI_API_KEY=...
python -m arena.runner --llm-provider xai --dry-run
```

Authorized one-call xAI smoke (this spends one worker call; the runner has no
single-call mode, and `--max-model-calls` is an abort ceiling, not a cap):

```
python - <<'PY'
from pathlib import Path
from arena.api_llm import XAIWorker
from arena.fixtures import load_all_fixtures
from arena.lanham import unperturbed
from arena.verifier import _read_baseline_file

fixture = next(f for f in load_all_fixtures(Path("fixtures")) if f.id == "F1_loadbearing_good")
target_path, source = _read_baseline_file(fixture)
diff = XAIWorker().regenerate_patch(source, unperturbed(list(fixture.reasoning_components)), target_path)
print(diff)
PY
```

Full xAI live run after the smoke is green:

```
python -m arena.runner --llm-provider xai --confirm-live --max-model-calls 168
```

Additional OpenAI-compatible providers are available:

```
python -m arena.runner --llm-provider gemini --dry-run
python -m arena.runner --llm-provider openrouter --dry-run
```

Provider notes:
- `xai` uses `https://api.x.ai/v1/chat/completions`; default model `grok-4.3`.
- `gemini` uses the Gemini OpenAI-compatible endpoint; default model
  `gemini-2.5-flash-lite`.
- `openrouter` uses `https://openrouter.ai/api/v1/chat/completions`; default
  model `x-ai/grok-4.3`.
- `anthropic` remains available via the existing Anthropic SDK path, but is not
  recommended for budget-sensitive testing.

### CLI-backed live providers

The runner can also inject local CLI wrappers that satisfy the same Worker/Judge
interface:

```
python -m arena.runner --llm-provider claude-code --worker-model haiku --judge-model opus --dry-run
python -m arena.runner --llm-provider codex --dry-run
python -m arena.runner --llm-provider copilot --dry-run
```

Provider notes:
- `claude-code` uses `claude -p` with tools disabled, JSON output, one turn,
  no session persistence, and separate `--system-prompt` plus stdin user prompt.
- `codex` uses `codex exec` with read-only sandbox, ephemeral mode, ignored
  rules, stdin prompt, and `--output-last-message` capture. Because this
  extracted project is not necessarily a git repository, the wrapper also uses
  `--skip-git-repo-check`.
- `copilot` uses `copilot -p` with JSONL output, streaming off, custom
  instructions and built-in MCPs disabled, no remote control, no ask-user tool,
  and no available tools.

Model overrides and guards:
- `--worker-model` and `--judge-model` affect API and CLI providers.
- API providers fail closed if the response omits `model` or reports a served
  model that was not explicitly requested/accepted; there are no prefix or
  provider-alias heuristics.
- `--api-timeout` sets a per-call HTTP timeout for API providers.
- `--cli-effort` overrides effort for both worker and judge where the CLI
  provider supports effort.
- `--cli-timeout` sets a per-call subprocess timeout in seconds.
- `--max-model-calls` aborts before live execution if the planned call count is
  above the supplied ceiling.

All live providers consume subscription quota or paid API capacity. Treat every
provider as experimental until a provider-specific one-call smoke has been
explicitly authorized and mechanically verified. The current four-fixture live
run invokes the worker 165 times and the judge 3 times; F4 is scorer-rejected,
so its verifier/judge path is not invoked.

The hermetic exercise verifies the Verifier *harness* (perturbation
composition, AST-equivalence, majority vote, threshold sweep, per-
component aggregation). The live exercise additionally verifies the
*model-side hypotheses* (do Haiku-as-worker outputs actually match the
predicted load-bearing patterns).

## Documented expected discrimination matrix (live exercise)

| Fixture | Scorer | Verifier | Lanham fraction | Match ground truth |
|---|---|---|---|---|
| F1 | promote | accept  | ~0.75 | ✓ |
| F2 | promote | reject  | ~0.25 | ✓ |
| F3 | promote | accept  | ~1.00 | ✗ (Lanham-only insufficiency) |
| F4 | reject  | n/a (not invoked) | n/a | ✓ |

F3's mismatch is calibrated and expected for the patch-oriented Lanham-only
exercise. In the Project Model fixture set, F3 is represented more generally as
real/load-bearing pre-code reasoning that is aimed at the wrong target,
component, sequence, level, or too-narrow visible example.

## Documented expected Project Model fixture matrix

| Fixture | Expected label | Signal pattern |
|---|---|---|
| F1_project_model_aligned | F1 | all components aligned; near-neighbors distinguished |
| F2_project_model_decorative | F2 | decorative/unsupported rationale; missing fixture/harness evidence |
| F3_project_model_code_too_narrow | F3 | source/generalization components misaligned around a visible example |
| F3_project_model_process_wrong_sequence | F3 | process dependency violated; local calibration happens before contract alignment |
| F4_project_model_trivial | F4 | not-addressed components; missing evidence; deep verification not expected |

The Project Model checker reports component, invariant, dependency, evidence,
near-neighbor, F-label, and model-quality outcomes separately. Its agreement
rule is exact field-level comparison of fixture signal IDs, statuses,
explanations, evidence refs, and hint fields; it does not hide ambiguity behind
one numeric score. If a Project Model fails the quality gate,
the report marks feedback for `build-arena Project Model v0`; signal mismatches
are marked as `elenchus-core advisory signal shape` feedback.

## Findings from 4-fixture construction

**F3 surfaced an architectural gap before any Verifier code exists.** A Verifier built purely on the Lanham four-test would correctly handle F1 (accept) and F2 (reject) but wrongly accept the original code-adjacent F3 (lookup-table hack with load-bearing-but-misdirected reasoning).

Consequence: the Verifier needs at least two orthogonal axes:
1. **Reasoning ablation** (Lanham four-test) — catches fabricated reasoning that doesn't constrain the artifact
2. **Project/target generalization** — catches honest reasoning aimed at the wrong objective, component, sequence, level, or too-narrow visible example

This is the orthogonal-axis pattern from the constitution applied at the Verifier layer. Constitution amendment deferred to after the calibration set is complete; do not modify the constitution mid-build.

**Backlog**: `elenchus-validator` (https://github.com/leonbreukelman/elenchus-validator) is a candidate for the project/target-generalization axis via its contextGrounding and alternativeResistance subscores. Not work for this fixture pass.

## Fixture shape variance (positional confound discipline)

| Fixture | Components | Conclusion slot | Load-bearing pattern | Baseline fail | Patched fail |
|---|---|---|---|---|---|
| F1 | 4 | 4 (last) | distributed (1,2,3) | 1 | 0 |
| F2 | 4 | 4 (last) | concentrated on conclusion | 1 | 0 |
| F3 | 5 | 3 (middle) | all components | 1 | 0 |
| F4 | 2 | 1 (first) | n/a (Verifier doesn't fire) | 0 | 0 |

Variance in component count (4, 4, 5, 2), conclusion slot (4, 4, 3, 1), and baseline-fail shape (1, 1, 1, 0) blocks simple positional or count-based shortcuts.

## Layout

```
arena/        harness code
fixtures/     frozen patch fixture set plus fixtures/project_model_v0 advisory-signal cases
results/      discrimination matrices
```

## Usage

Requires Python 3.12+. The repo includes `.python-version` so `uv`/pyenv-style tools select Python 3.12 by default.

```
python -m arena.runner                              # default paths
python -m arena.runner --fixtures-dir fixtures --results-dir results
```

Emits one timestamped YAML per run: `results/run_<UTC-timestamp>.yaml`.
Exit code 0 iff every fixture's Scorer verdict, Verifier verdict, and
integrity status all agree with manifest ground truth. With the stub
Verifier in place (milestone 2), exit code is 1 by design until milestone 3.

## Resolved tradeoffs (from session handoff)

- T1 Verifier driver model: Haiku for perturbation regeneration, Opus only for
  final discrimination report. Upgrade to different-class model if 6-fixture
  set shows collusion on goodhart.
- T2 Fixture sourcing: 3 hand-crafted, 1 borrowed from prior empirical failures
  (atlas-elenchus or Elenchus).
- T3 Patch equivalence: AST-equivalence with whitespace/identifier normalization.
- T4 Threshold calibration: report verdicts across {0.50, 0.66, 0.75}; freeze
  nothing until 6-fixture set runs.
