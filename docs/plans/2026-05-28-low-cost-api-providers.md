# Low-Cost API Providers Implementation Plan

> **For Hermes:** Implement directly with strict TDD. Do not modify `fixtures/`, `exercise_verifier.py`, or frozen fixture data. Do not run live model generations without explicit authorization after tests pass.

**Goal:** Add low-cost API-backed live providers so the harness can run against xAI/Grok first, with optional Gemini/OpenRouter support, while preserving existing Anthropic and CLI paths.

**Architecture:** Keep `arena.llm` as the prompt/protocol source. Add `arena.api_llm` for OpenAI-compatible HTTP chat-completions adapters using Python stdlib only. Wire `arena.runner` provider selection to build either Anthropic defaults, CLI adapters, or API adapters. Add dry-run/budget guards so full harness call count and rough token/cost exposure can be measured without a live generation.

**Tech Stack:** Python stdlib (`urllib.request`, `json`, `os`, `dataclasses`), pytest, existing `arena` package. No new required dependency.

---

## Confirmed discovery

- Active checkout: `/home/leonb/projects/arena-calibration`.
- Current tree was clean before this plan file.
- Active shell did not contain API keys, but `/home/leonb/.hermes/.env` contains `XAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, and `ANTHROPIC_API_KEY` names.
- xAI model-list probe using `XAI_API_KEY` succeeded without printing the key.
- xAI returned 8 models; Grok models included `grok-4.3`, `grok-4.20-0309-reasoning`, `grok-4.20-0309-non-reasoning`, `grok-4.20-multi-agent-0309`, and `grok-build-0.1`.
- Default xAI model for this pass: `grok-4.3`, because the live model API exposes it as the current simple Grok chat model and the user asked for latest Grok.

## Non-goals

- No full live calibration run in this implementation pass.
- No fixture/harness semantic changes.
- No SDK dependency addition unless stdlib HTTP proves insufficient.
- No Anthropic spend path as the default live test route.
- No claims that xAI/Gemini/OpenRouter results are scientifically equivalent to Anthropic/Claude payloads; only the visible harness task prompt is equivalent.

## Opus plan review status

Review artifact:
- `/tmp/arena-lowcost-plan-review.stdout.json`

Verdict:
- `ACCEPT_WITH_CHANGES`

Accepted changes incorporated before implementation:
- Add a hard live-run gate. Non-dry-run execution must require `--confirm-live` and must abort before constructing model adapters otherwise.
- Add `--max-model-calls` as a spend ceiling; abort before live execution when planned calls exceed it.
- Add explicit HTTP timeout plumbing for API providers.
- Derive dry-run/call counts from shared planning logic, not a duplicated side calculation.
- Include worst-case output-token exposure from configured `max_tokens` alongside rough input-token estimates.
- Add tests for no-network dry-run, no-key dry-run, secret/prompt non-leakage, content-part parsing, timeout propagation, and budget-gate aborts.
- Do not auto-load `/home/leonb/.hermes/.env`; operators must export keys into the execution environment.

## Acceptance criteria

1. `python -m arena.runner --llm-provider xai --dry-run` performs no live generation, prints call-count/budget metadata, and exits 0.
2. Any non-dry-run execution aborts before model construction unless `--confirm-live` is supplied.
3. `--max-model-calls N` aborts before model construction when the planned call count exceeds `N`.
4. `xai` provider can be constructed without Anthropic SDK or CLI tools.
5. xAI default worker and judge model resolve to `grok-4.3`, with `--worker-model` / `--judge-model` overrides preserved.
6. OpenRouter and Gemini OpenAI-compatible adapters are available but not default.
7. Missing API key fails fast with a typed error and does not leak prompt text or secrets.
8. API payload tests prove system/user prompt parity, temperature/max token settings, model selection, endpoint URL, auth header shape, timeout propagation, and response parsing.
9. Dry-run tests prove full current run exposure: 165 worker calls, 3 judge calls, 168 total calls on the 4-fixture set.
10. Existing CLI tests and hermetic verifier still pass.

## TDD tasks

### Task 1: API adapter tests

**Files:**
- Create: `tests/test_api_llm.py`

Write failing tests for:
- `XAIWorker` calls OpenAI-compatible `/chat/completions` with `model="grok-4.3"`, `temperature=0`, `max_tokens=1024`, system prompt `_REGEN_SYSTEM`, user prompt from `_REGEN_USER_TEMPLATE`, and `Authorization: Bearer ...` without exposing prompt in the URL.
- `XAIJudge` uses `max_tokens=512` and same chat-completions response parser.
- `build_api_models("xai")` returns xAI worker/judge defaulting to `grok-4.3`.
- `build_api_models("gemini")` defaults to `gemini-2.5-flash-lite` and Gemini OpenAI-compatible endpoint.
- `build_api_models("openrouter")` defaults to `x-ai/grok-4.3` or user-supplied model against OpenRouter endpoint.
- missing key raises `ApiModelError` naming provider/key name but not prompt content.
- HTTP error raises `ApiModelError` with provider/status and bounded sanitized body.
- malformed response raises `ApiModelError` without prompt leakage.

**RED command:** `. .venv/bin/activate && python -m pytest tests/test_api_llm.py -q`

Expected before implementation: import failure for `arena.api_llm`.

### Task 2: Implement `arena.api_llm`

**Files:**
- Create: `arena/api_llm.py`

Implementation requirements:
- Define `ApiModelError` and `ApiProviderConfig`.
- Use only stdlib HTTP and never `shell=True`.
- Read API keys from environment by default. Tests can inject `api_key` directly.
- Do not auto-source `/home/leonb/.hermes/.env` from project code.
- Provider defaults:
  - xAI: base URL `https://api.x.ai/v1`, key env `XAI_API_KEY`, worker/judge `grok-4.3`.
  - Gemini: base URL `https://generativelanguage.googleapis.com/v1beta/openai`, key env priority `GEMINI_API_KEY`, then `GOOGLE_API_KEY`, worker/judge `gemini-2.5-flash-lite`.
  - OpenRouter: base URL `https://openrouter.ai/api/v1`, key env `OPENROUTER_API_KEY`, worker/judge default `x-ai/grok-4.3` unless overridden.
- Response parser should support standard OpenAI chat-completions shape: `choices[0].message.content` string or content parts.
- Parser should ignore reasoning-side fields and fail cleanly if visible message content is absent.
- Return raw text exactly enough to preserve unified diffs; do not strip semantic newlines except when response content itself is absent.
- Sanitize errors: provider/status/key name ok; prompt, file contents, reasoning, API key not ok.
- Pass an explicit per-call HTTP timeout; default 180 seconds unless overridden.

### Task 3: Runner provider wiring and dry-run budget

**Files:**
- Modify: `arena/runner.py`
- Test: `tests/test_runner_cli_provider.py` or new `tests/test_runner_api_provider.py`

Behavior:
- Extend `--llm-provider` choices to `anthropic`, `xai`, `gemini`, `openrouter`, `claude-code`, `codex`, `copilot`.
- Rename help text so `--worker-model` / `--judge-model` apply to all non-default providers, not only CLI providers.
- Add `--dry-run` to compute scorer-only fixture promotion and expected live model call counts without constructing live API/CLI models or invoking verifier.
- Add `--confirm-live`; abort every non-dry-run invocation before model construction unless this flag is present.
- Add `--max-model-calls`; abort before model construction if planned calls exceed the supplied ceiling.
- Dry-run output should include promoted fixtures, worker calls, judge calls, total calls, rough input chars/tokens, worst-case output tokens, provider, worker model, judge model.
- Dry-run must not require API keys.
- Default no-flag `python -m arena.runner` now fails closed with a clear message instructing operators to use `--dry-run` or explicit `--confirm-live`.

### Task 4: Documentation update

**Files:**
- Modify: `README.md`

Document:
- Recommended low-cost path: `python -m arena.runner --llm-provider xai --dry-run` first.
- xAI live smoke requires `XAI_API_KEY`; full run still requires explicit user authorization.
- `grok-4.3` is the default xAI model observed from xAI Models API.
- Current full 4-fixture run count: 168 model calls.
- Anthropic remains available but not recommended for budget-sensitive testing.

## Verification commands

Run after implementation:

```bash
. .venv/bin/activate
python -m pytest tests/test_api_llm.py -q
python -m pytest tests/test_runner_cli_provider.py tests/test_api_llm.py -q
python -m pytest tests -q
python exercise_verifier.py
python -m arena.runner --llm-provider xai --dry-run
python -m py_compile arena/api_llm.py arena/runner.py
```

No live model generation is authorized during this plan. After all checks pass, stop and report readiness for an authorized xAI smoke/test run.
