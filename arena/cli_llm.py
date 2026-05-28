"""CLI-backed LLM adapters for the arena Verifier.

These adapters keep the existing Anthropic API path intact while allowing the
runner to inject local agent CLI frontends that satisfy the same Worker/Judge
protocols from :mod:`arena.llm`.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.llm import _JUDGE_SYSTEM, _REGEN_SYSTEM, _REGEN_USER_TEMPLATE

_SECRET_ENV_NAMES = "ANTHROPIC_API_KEY,OPENROUTER_API_KEY,XAI_API_KEY"
_SNIPPET_LIMIT = 500


class CliModelError(RuntimeError):
    """Raised when a CLI-backed model invocation fails before returning text."""


@dataclass(frozen=True)
class ProviderDefaults:
    worker_model: str | None
    judge_model: str | None
    worker_effort: str | None
    judge_effort: str | None


_PROVIDER_DEFAULTS: dict[str, ProviderDefaults] = {
    "claude-code": ProviderDefaults(
        worker_model="haiku",
        judge_model="opus",
        worker_effort="low",
        judge_effort="max",
    ),
    "codex": ProviderDefaults(
        worker_model=None,
        judge_model=None,
        worker_effort=None,
        judge_effort=None,
    ),
    "copilot": ProviderDefaults(
        worker_model=None,
        judge_model=None,
        worker_effort="low",
        judge_effort="max",
    ),
}


def _worker_user_prompt(file_contents: str, reasoning: str, target_path: str) -> str:
    return _REGEN_USER_TEMPLATE.format(
        target_path=target_path,
        file_contents=file_contents,
        reasoning=reasoning,
    )


def _judge_user_prompt(fixture_id: str, per_component_summary: str) -> str:
    return (
        f"Fixture: {fixture_id}\n\n"
        f"Per-component verdicts:\n{per_component_summary}\n\n"
        f"Summarize in one sentence."
    )


def _combined_prompt(system: str, user: str) -> str:
    return f"System instructions:\n{system}\n\nUser request:\n{user}"


def _prompt_tokens(prompt: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-z0-9_./'`:-]{4,}", prompt)
        if len(token) >= 4
    }


def _safe_snippet(text: str | bytes | None, prompt: str) -> str:
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    snippet = text[:_SNIPPET_LIMIT]
    for token in sorted(_prompt_tokens(prompt), key=len, reverse=True):
        snippet = snippet.replace(token, "[redacted]")
    return snippet.replace("\n", "\\n")


def _raise_failure(
    *,
    provider: str,
    executable: str,
    prompt: str,
    message: str,
    stdout: str | bytes | None = None,
    stderr: str | bytes | None = None,
) -> None:
    stdout_snippet = _safe_snippet(stdout, prompt)
    stderr_snippet = _safe_snippet(stderr, prompt)
    details = [f"{provider} invocation failed via {executable}: {message}"]
    if stderr_snippet:
        details.append(f"stderr={stderr_snippet}")
    if stdout_snippet:
        details.append(f"stdout={stdout_snippet}")
    raise CliModelError("; ".join(details))


def _run_cli(
    *,
    provider: str,
    executable: str,
    argv: list[str],
    prompt: str,
    prompt_on_stdin: bool,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    if shutil.which(executable) is None:
        raise CliModelError(
            f"{provider} invocation failed: missing executable {executable!r}"
        )

    try:
        result = subprocess.run(
            argv,
            input=prompt if prompt_on_stdin else None,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        _raise_failure(
            provider=provider,
            executable=executable,
            prompt=prompt,
            message=f"timed out after {timeout_seconds}s",
            stdout=exc.output,
            stderr=exc.stderr,
        )
    if result.returncode != 0:
        _raise_failure(
            provider=provider,
            executable=executable,
            prompt=prompt,
            message=f"exit code {result.returncode}",
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result


def _extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_extract_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("result", "content", "text", "message", "output", "response"):
            if key in value:
                text = _extract_text(value[key])
                if text:
                    return text
        if "data" in value:
            text = _extract_text(value["data"])
            if text:
                return text
    return ""


def _parse_json_or_raw(stdout: str) -> str:
    stripped = stdout.strip()
    if not stripped:
        return ""
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    text = _extract_text(value)
    return text if text else stripped


def _parse_jsonl_or_raw(stdout: str) -> str:
    stripped = stdout.strip()
    if not stripped:
        return ""

    lines = [line for line in stripped.splitlines() if line.strip()]
    extracted: list[str] = []
    all_json = True
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            all_json = False
            break
        text = _extract_text(value)
        if text:
            extracted.append(text)
    if all_json and extracted:
        return extracted[-1]

    return _parse_json_or_raw(stripped)


@dataclass
class ClaudeCodeWorker:
    model: str | None = "haiku"
    effort: str | None = "low"
    timeout_seconds: int = 180

    def regenerate_patch(
        self,
        file_contents: str,
        reasoning: str,
        target_path: str,
    ) -> str:
        user_prompt = _worker_user_prompt(file_contents, reasoning, target_path)
        result = _run_claude_code(
            system_prompt=_REGEN_SYSTEM,
            user_prompt=user_prompt,
            model=self.model,
            effort=self.effort,
            timeout_seconds=self.timeout_seconds,
        )
        return _parse_json_or_raw(result.stdout)


@dataclass
class ClaudeCodeJudge:
    model: str | None = "opus"
    effort: str | None = "max"
    timeout_seconds: int = 180

    def summarize(self, fixture_id: str, per_component_summary: str) -> str:
        user_prompt = _judge_user_prompt(fixture_id, per_component_summary)
        result = _run_claude_code(
            system_prompt=_JUDGE_SYSTEM,
            user_prompt=user_prompt,
            model=self.model,
            effort=self.effort,
            timeout_seconds=self.timeout_seconds,
        )
        return _parse_json_or_raw(result.stdout)


def _run_claude_code(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None,
    effort: str | None,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    argv = [
        "claude",
        "-p",
        "--tools",
        "",
        "--output-format",
        "json",
        "--max-turns",
        "1",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--system-prompt",
        system_prompt,
    ]
    if model:
        argv.extend(["--model", model])
    if effort:
        argv.extend(["--effort", effort])
    return _run_cli(
        provider="claude-code",
        executable="claude",
        argv=argv,
        prompt=user_prompt,
        prompt_on_stdin=True,
        timeout_seconds=timeout_seconds,
    )


@dataclass
class CodexWorker:
    model: str | None = None
    timeout_seconds: int = 180

    def regenerate_patch(
        self,
        file_contents: str,
        reasoning: str,
        target_path: str,
    ) -> str:
        prompt = _combined_prompt(
            _REGEN_SYSTEM,
            _worker_user_prompt(file_contents, reasoning, target_path),
        )
        return _run_codex(prompt, model=self.model, timeout_seconds=self.timeout_seconds)


@dataclass
class CodexJudge:
    model: str | None = None
    timeout_seconds: int = 180

    def summarize(self, fixture_id: str, per_component_summary: str) -> str:
        prompt = _combined_prompt(
            _JUDGE_SYSTEM,
            _judge_user_prompt(fixture_id, per_component_summary),
        )
        return _run_codex(prompt, model=self.model, timeout_seconds=self.timeout_seconds)


def _run_codex(prompt: str, *, model: str | None, timeout_seconds: int) -> str:
    handle = tempfile.NamedTemporaryFile(prefix="arena-codex-last-", suffix=".txt", delete=False)
    output_path = Path(handle.name)
    handle.close()
    try:
        argv = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--ignore-rules",
            "--output-last-message",
            str(output_path),
        ]
        if model:
            argv.extend(["--model", model])
        argv.append("-")
        result = _run_cli(
            provider="codex",
            executable="codex",
            argv=argv,
            prompt=prompt,
            prompt_on_stdin=True,
            timeout_seconds=timeout_seconds,
        )
        file_text = output_path.read_text() if output_path.exists() else ""
        return file_text if file_text else result.stdout
    finally:
        try:
            output_path.unlink()
        except FileNotFoundError:
            pass


@dataclass
class CopilotWorker:
    model: str | None = None
    effort: str | None = "low"
    timeout_seconds: int = 180

    def regenerate_patch(
        self,
        file_contents: str,
        reasoning: str,
        target_path: str,
    ) -> str:
        prompt = _combined_prompt(
            _REGEN_SYSTEM,
            _worker_user_prompt(file_contents, reasoning, target_path),
        )
        result = _run_copilot(
            prompt,
            model=self.model,
            effort=self.effort,
            timeout_seconds=self.timeout_seconds,
        )
        return _parse_jsonl_or_raw(result.stdout)


@dataclass
class CopilotJudge:
    model: str | None = None
    effort: str | None = "max"
    timeout_seconds: int = 180

    def summarize(self, fixture_id: str, per_component_summary: str) -> str:
        prompt = _combined_prompt(
            _JUDGE_SYSTEM,
            _judge_user_prompt(fixture_id, per_component_summary),
        )
        result = _run_copilot(
            prompt,
            model=self.model,
            effort=self.effort,
            timeout_seconds=self.timeout_seconds,
        )
        return _parse_jsonl_or_raw(result.stdout)


def _run_copilot(
    prompt: str,
    *,
    model: str | None,
    effort: str | None,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    argv = [
        "copilot",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--stream",
        "off",
        "--no-custom-instructions",
        "--disable-builtin-mcps",
        "--no-remote",
        "--no-ask-user",
        "--available-tools=",
        f"--secret-env-vars={_SECRET_ENV_NAMES}",
    ]
    if model:
        argv.extend(["--model", model])
    if effort:
        argv.extend(["--effort", effort])
    return _run_cli(
        provider="copilot",
        executable="copilot",
        argv=argv,
        prompt=prompt,
        prompt_on_stdin=False,
        timeout_seconds=timeout_seconds,
    )


def build_cli_models(
    provider: str,
    *,
    worker_model: str | None = None,
    judge_model: str | None = None,
    effort: str | None = None,
    timeout_seconds: int = 180,
):
    """Build Worker/Judge adapters for a CLI provider."""
    if provider not in _PROVIDER_DEFAULTS:
        known = ", ".join(sorted(_PROVIDER_DEFAULTS))
        raise ValueError(f"unknown CLI provider {provider!r}; expected one of: {known}")

    defaults = _PROVIDER_DEFAULTS[provider]
    resolved_worker_model = worker_model if worker_model is not None else defaults.worker_model
    resolved_judge_model = judge_model if judge_model is not None else defaults.judge_model
    resolved_worker_effort = effort if effort is not None else defaults.worker_effort
    resolved_judge_effort = effort if effort is not None else defaults.judge_effort

    if provider == "claude-code":
        return (
            ClaudeCodeWorker(
                model=resolved_worker_model,
                effort=resolved_worker_effort,
                timeout_seconds=timeout_seconds,
            ),
            ClaudeCodeJudge(
                model=resolved_judge_model,
                effort=resolved_judge_effort,
                timeout_seconds=timeout_seconds,
            ),
        )
    if provider == "codex":
        return (
            CodexWorker(model=resolved_worker_model, timeout_seconds=timeout_seconds),
            CodexJudge(model=resolved_judge_model, timeout_seconds=timeout_seconds),
        )
    if provider == "copilot":
        return (
            CopilotWorker(
                model=resolved_worker_model,
                effort=resolved_worker_effort,
                timeout_seconds=timeout_seconds,
            ),
            CopilotJudge(
                model=resolved_judge_model,
                effort=resolved_judge_effort,
                timeout_seconds=timeout_seconds,
            ),
        )

    raise AssertionError(f"unhandled provider {provider!r}")
