# CLI LLM Wrappers Implementation Plan

> **For Hermes:** Implement this plan directly with strict TDD. Do not modify `fixtures/` or `exercise_verifier.py`. Keep existing Anthropic API behavior as the default path.

**Goal:** Add CLI-backed Worker/Judge wrappers for Claude Code, Codex, and GitHub Copilot CLI while preserving the existing Anthropic API components and runner behavior.

**Architecture:** Keep `arena.llm` as the canonical protocol/prompt source. Add `arena.cli_llm` to adapt local CLI subprocesses to the existing `Worker` and `Judge` protocols, then extend `arena.runner` with optional provider-selection flags. The default `python -m arena.runner` path remains unchanged and still uses Anthropic API classes.

**Tech Stack:** Python stdlib (`subprocess`, `json`, `tempfile`, `dataclasses`, `shutil`), pytest, existing `arena` package. No new required runtime dependency.

---

## Opus review status

Review artifact:
- `docs/verification/2026-05-28-opus-plan-review.stdout.json` (stored in this repo; older metadata may retain the absolute path from the original review run)

Reviewer command:
- Claude Code Opus alias, `--effort max`, `--tools ""`, `--output-format json`, read-only.

Verdict:
- `ACCEPT_WITH_CHANGES`

Accepted adjustments incorporated here:
- Verify real CLI flags with `--help` before hard-coding command tests.
- Use stdin where supported to avoid argv length limits.
- Explicitly test prompt assembly/parity.
- Add tests for `build_cli_models` mapping/defaults/errors.
- Add timeout/error redaction tests.
- Add Codex tempfile cleanup tests.
- Label un-smoked CLI providers experimental until explicit live smoke authorization.
- Do not hard-code full-run call count as a success claim; document current 4-fixture estimate with why judge calls are 3.

## Verified zero-quota CLI contract checks

Observed from local `--help` output:

Claude Code 2.1.152 supports:
- `-p` / `--print`
- prompt via stdin when `--print` is used and no prompt arg is supplied
- `--model <model>` with aliases such as `opus`
- `--effort <low|medium|high|xhigh|max>`
- `--tools <tools...>` where `""` disables all tools
- `--output-format json`
- `--max-turns <n>`
- `--no-session-persistence`
- `--disable-slash-commands`
- `--system-prompt <prompt>`

Codex 0.133.0 supports:
- `codex exec`
- prompt via stdin when prompt is omitted or `-`
- `--skip-git-repo-check`
- `--sandbox read-only`
- `--ephemeral`
- `--ignore-rules`
- `--model <model>`
- `--output-last-message <FILE>` / `-o <FILE>`

Copilot 1.0.54 supports:
- `-p` / `--prompt <text>`; missing argument errors, so prompt must be argv for this CLI
- `--model <model>`
- `--effort <none|low|medium|high|xhigh|max>`
- `--output-format json`
- `--stream off`
- `--no-custom-instructions`
- `--disable-builtin-mcps`
- `--no-remote`
- `--no-ask-user`
- `--secret-env-vars=...`
- `--available-tools=...`; use `--available-tools=` to expose no tools

## Baseline and constraints

Confirmed baseline:
- Existing live API path is `arena.llm.AnthropicWorker` / `arena.llm.AnthropicJudge`.
- Existing prompts live in `arena.llm` as `_REGEN_SYSTEM`, `_REGEN_USER_TEMPLATE`, `_JUDGE_SYSTEM`.
- Existing runner already supports dependency injection via `run(..., worker=..., judge=...)`.
- `python -m arena.runner` currently has no provider-selection CLI.
- `build-arena` is not a git repo; Codex wrapper must include `--skip-git-repo-check`.

Non-goals:
- Do not change fixture content.
- Do not change `exercise_verifier.py`.
- Do not remove or rename Anthropic API classes.
- Do not run full live CLI-backed harness without explicit spend/quota authorization.
- Do not silently rewrite bad CLI/model output into valid diffs; bad output remains observable model behavior.

## Interface contract

CLI wrappers must satisfy existing protocols:

```python
class Worker(Protocol):
    def regenerate_patch(self, file_contents: str, reasoning: str, target_path: str) -> str: ...

class Judge(Protocol):
    def summarize(self, fixture_id: str, per_component_summary: str) -> str: ...
```

Provider selectors:
- `anthropic`: existing default; no behavior change.
- `claude-code`: use `claude -p` print mode.
- `codex`: use `codex exec` non-interactive mode.
- `copilot`: use `copilot -p` non-interactive mode.

Prompt assembly:
- Worker prompt body must contain the existing `_REGEN_SYSTEM` followed by the existing `_REGEN_USER_TEMPLATE` populated with target path, file contents, and reasoning.
- Judge prompt body must contain the existing `_JUDGE_SYSTEM` followed by fixture/per-component summary text equivalent to `AnthropicJudge.summarize`.
- For Claude Code, pass system text with `--system-prompt` and user text through stdin.
- For Codex, concatenate system and user sections into stdin because `codex exec` does not expose a stable dedicated system-prompt flag in observed help.
- For Copilot, concatenate system and user sections into the `-p` argument because `copilot -p` requires a prompt argument in observed help.

## Task 1: Add failing tests for CLI subprocess adapters

**Objective:** Specify subprocess command construction, prompt parity, output parsing, timeout/error behavior, tool-isolation flags, and prompt transport before production code.

**Files:**
- Create: `tests/test_cli_llm.py`

Required tests:

1. `test_claude_code_worker_invokes_print_mode_with_stdin_and_extracts_json_result`
   - Monkeypatch `subprocess.run`.
   - Instantiate `ClaudeCodeWorker(model="opus", effort="max")`.
   - Call `regenerate_patch("SOURCE", "REASON", "tokenizer.py")`.
   - Assert command includes `claude`, `-p`, `--model opus`, `--effort max`, `--tools ""`, `--output-format json`, `--max-turns 1`, `--no-session-persistence`, `--disable-slash-commands`, `--system-prompt`.
   - Assert no prompt body is present as an argv element.
   - Assert `input=` contains `SOURCE`, `REASON`, and `tokenizer.py`.
   - Mock stdout JSON with `result` and assert returned diff equals result.

2. `test_worker_prompt_assembly_preserves_existing_template_content`
   - Use a fake CLI response.
   - Assert worker prompt includes strict diff instruction from `_REGEN_SYSTEM` and populated user fields from `_REGEN_USER_TEMPLATE`.

3. `test_judge_prompt_assembly_preserves_existing_summary_contract`
   - Use a fake CLI response.
   - Assert judge prompt includes terse-summary instruction, fixture id, and component summary.

4. `test_claude_code_error_includes_provider_and_exit_code_without_prompt_leakage`
   - Mock non-zero return code with stderr that echoes input-like content.
   - Assert `CliModelError` names provider and exit code but excludes file contents/reasoning prompt substrings.

5. `test_timeout_converts_to_cli_model_error_without_prompt_leakage`
   - Mock `subprocess.run` raising `subprocess.TimeoutExpired`.
   - Assert provider appears and prompt content does not.

6. `test_codex_worker_uses_read_only_ephemeral_stdin_output_file_and_cleans_up`
   - Monkeypatch `subprocess.run` to inspect args and write the path after `--output-last-message`.
   - Assert command includes `codex exec`, `--skip-git-repo-check`, `--sandbox read-only`, `--ephemeral`, `--ignore-rules`, `--output-last-message <tmpfile>`.
   - Assert prompt is sent via stdin.
   - Assert temp output file is removed after success.

7. `test_codex_empty_output_file_falls_back_to_stdout_and_cleans_up`
   - Mock empty output file and stdout text.
   - Assert stdout is returned and temp file is removed.

8. `test_copilot_judge_uses_noninteractive_no_tool_flags_and_parses_jsonl`
   - Monkeypatch `subprocess.run`.
   - Assert command includes `copilot`, `-p`, `--output-format json`, `--stream off`, `--no-custom-instructions`, `--disable-builtin-mcps`, `--no-remote`, `--no-ask-user`, `--available-tools=`, and `--secret-env-vars=...`.
   - Assert prompt is present in the `-p` argument because Copilot requires it.
   - Return JSONL and assert parsed final note.

9. `test_malformed_json_output_falls_back_to_raw_stdout_for_claude_and_copilot`
   - Assert non-JSON stdout returns stripped raw text rather than raising.

10. `test_missing_cli_binary_raises_clear_error`
   - Monkeypatch `shutil.which` to return `None`.
   - Assert error says executable is missing and does not include prompt content.

11. `test_build_cli_models_maps_providers_defaults_and_rejects_unknown_provider`
   - Assert provider mapping for all three CLI providers.
   - Assert default models/efforts are filled.
   - Assert unknown provider raises `ValueError`.

**RED command:**

```bash
. .venv/bin/activate && python -m pytest tests/test_cli_llm.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'arena.cli_llm'`.

## Task 2: Implement `arena.cli_llm`

**Objective:** Add CLI-backed Worker/Judge implementations behind existing protocols.

**Files:**
- Create: `arena/cli_llm.py`

Required structure:

```python
class CliModelError(RuntimeError): ...

@dataclass(frozen=True)
class ProviderDefaults:
    worker_model: str | None
    judge_model: str | None
    worker_effort: str | None
    judge_effort: str | None
```

Implementation requirements:
- Validate `shutil.which(executable)` before invoking.
- Never use `shell=True`.
- Use prompt stdin for Claude Code and Codex.
- Use prompt argv for Copilot because observed CLI requires `-p <text>`.
- Do not include full prompt/file contents/reasoning in exceptions.
- Include provider, executable, exit code, timeout, and bounded sanitized stdout/stderr snippet in errors.
- Catch `subprocess.TimeoutExpired`.
- Remove Codex temp output file in `finally`.
- Keep wrappers stateless so each harness sample is independent.
- Use shared helpers; avoid duplicating subprocess/error/parser logic across all classes.

Default model policy:
- Let users override models with `--worker-model` / `--judge-model`.
- Provide conservative defaults matching installed CLI aliases where known:
  - Claude Code: worker `haiku`, judge `opus`; worker effort `low`, judge effort `max`.
  - Codex: no hard-coded model by default (`None`) so Codex uses its configured/default model unless user supplies one.
  - Copilot: no hard-coded model by default (`None`) so Copilot uses its configured/default model unless user supplies one; worker effort `low`, judge effort `max`.

Command builders:

Claude Code:
```bash
claude -p --model <model-if-set> --effort <effort-if-set> --tools "" --output-format json --max-turns 1 --no-session-persistence --disable-slash-commands --system-prompt <system>
```
with user prompt on stdin.

Codex:
```bash
codex exec --skip-git-repo-check --sandbox read-only --ephemeral --ignore-rules --output-last-message <tmpfile> --model <model-if-set> -
```
with combined prompt on stdin.

Copilot:
```bash
copilot -p <combined-prompt> --model <model-if-set> --effort <effort-if-set> --output-format json --stream off --no-custom-instructions --disable-builtin-mcps --no-remote --no-ask-user --available-tools= --secret-env-vars=ANTHROPIC_API_KEY,OPENROUTER_API_KEY,XAI_API_KEY
```

Parsers:
- Claude: parse JSON object; prefer `result`, else `content`, else raw stdout.
- Codex: read output file; fallback to stdout if file empty.
- Copilot: parse JSONL/JSON if possible; prefer final textual fields; else raw stdout.

## Task 3: Add failing tests for runner provider selection

**Objective:** Specify user-facing CLI integration while preserving default API path.

**Files:**
- Create: `tests/test_runner_cli_provider.py`

Required tests:

1. `test_runner_default_provider_does_not_construct_cli_models`
   - Monkeypatch `arena.runner.run` to capture `worker`/`judge`.
   - Call `arena.runner.main(["--fixtures-dir", "fixtures", "--results-dir", tmp])`.
   - Assert `worker is None` and `judge is None`.

2. `test_runner_claude_code_provider_constructs_cli_models`
   - Monkeypatch `arena.runner.build_cli_models` to capture provider/model/timeout args and return fake worker/judge.
   - Monkeypatch `arena.runner.run`.
   - Call `main([... "--llm-provider", "claude-code", "--worker-model", "haiku", "--judge-model", "opus", "--cli-effort", "max", "--cli-timeout", "321"])`.
   - Assert fake objects are passed to `run`.

3. `test_runner_anthropic_ignores_cli_model_flags_and_preserves_default_api_path`
   - Call `main([... "--llm-provider", "anthropic", "--worker-model", "ignored", "--judge-model", "ignored"])` with `run` monkeypatched.
   - Assert `worker is None` and `judge is None`.

**RED command:**

```bash
. .venv/bin/activate && python -m pytest tests/test_runner_cli_provider.py -q
```

Expected: fail because `--llm-provider` is unknown.

## Task 4: Extend `arena.runner` CLI without changing default behavior

**Objective:** Add provider selection flags and instantiate CLI wrappers only when requested.

**Files:**
- Modify: `arena/runner.py`

Implementation requirements:
- Lazy import or module-level import `build_cli_models` so tests can monkeypatch `arena.runner.build_cli_models`.
- Add argparse options:

```python
parser.add_argument("--llm-provider", choices=["anthropic", "claude-code", "codex", "copilot"], default="anthropic")
parser.add_argument("--worker-model", default=None, help="CLI provider worker model override")
parser.add_argument("--judge-model", default=None, help="CLI provider judge model override")
parser.add_argument("--cli-effort", default=None, help="Override CLI effort for both worker and judge where supported")
parser.add_argument("--cli-timeout", type=int, default=180, help="Per CLI model call timeout in seconds")
```

- In `main`, call `build_cli_models` only if provider is not `anthropic`.
- Preserve printed summary and exit-code behavior.

## Task 5: Documentation update

**Objective:** Document how to run with each backend and warn about quota-consuming behavior.

**Files:**
- Modify: `README.md`

Add section:
- API default: `python -m arena.runner`
- Claude Code: `python -m arena.runner --llm-provider claude-code --worker-model haiku --judge-model opus`
- Codex: `python -m arena.runner --llm-provider codex` or explicit `--worker-model ... --judge-model ...`
- Copilot: `python -m arena.runner --llm-provider copilot` or explicit `--worker-model ... --judge-model ...`
- Warn that CLI wrappers use subscription/quota-backed services unless Codex OSS/local-provider is configured separately.
- Current 4-fixture live-run estimate: 165 worker calls and 3 judge calls because F4 is scorer-rejected and the verifier/judge is not invoked for it.
- Mark CLI providers experimental until a provider-specific live smoke succeeds.

## Task 6: Full verification after implementation

Commands:

```bash
. .venv/bin/activate && python -m pytest tests/test_cli_llm.py tests/test_runner_cli_provider.py -q
. .venv/bin/activate && python exercise_verifier.py
. .venv/bin/activate && python -m arena.runner --help
```

Expected:
- pytest passes.
- hermetic verifier exits 0 and prints `ALL HARNESS PREDICTIONS HOLD`.
- `--help` lists `--llm-provider`, `--worker-model`, `--judge-model`, `--cli-effort`, `--cli-timeout`.

## Task 7: Optional live smokes only after explicit authorization

Do not run automatically during implementation.

Suggested one-call smoke per provider, not full harness:
- Instantiate one Worker wrapper.
- Call `regenerate_patch` on a tiny toy source/reasoning prompt.
- Check only process exit and returned text shape.

Full 4-fixture estimate per provider:
- 165 worker calls.
- 3 judge calls.
- 168 total model calls.
