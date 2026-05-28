from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


VALID_DIFF = "--- a/tokenizer.py\n+++ b/tokenizer.py\n@@ -1 +1 @@\n-a\n+b\n"


def _ok(stdout: str = VALID_DIFF):
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def test_claude_code_worker_invokes_print_mode_with_stdin_and_extracts_json_result(monkeypatch):
    import arena.cli_llm as cli_llm

    captured = {}

    def fake_run(argv, *, input, capture_output, text, timeout):
        captured["argv"] = argv
        captured["input"] = input
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        return _ok(json.dumps({"type": "result", "subtype": "success", "result": VALID_DIFF}))

    monkeypatch.setattr(cli_llm.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(cli_llm.subprocess, "run", fake_run)

    worker = cli_llm.ClaudeCodeWorker(model="opus", effort="max", timeout_seconds=77)
    result = worker.regenerate_patch("SOURCE", "REASON", "tokenizer.py")

    assert result == VALID_DIFF
    argv = captured["argv"]
    assert argv[0] == "claude"
    assert "-p" in argv
    assert argv[argv.index("--model") + 1] == "opus"
    assert argv[argv.index("--effort") + 1] == "max"
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--max-turns") + 1] == "1"
    assert "--no-session-persistence" in argv
    assert "--disable-slash-commands" in argv
    assert "--system-prompt" in argv
    assert all("SOURCE" not in arg and "REASON" not in arg for arg in argv)
    assert "SOURCE" in captured["input"]
    assert "REASON" in captured["input"]
    assert "tokenizer.py" in captured["input"]
    assert captured["timeout"] == 77
    assert captured["capture_output"] is True
    assert captured["text"] is True


def test_worker_prompt_assembly_preserves_existing_template_content(monkeypatch):
    import arena.cli_llm as cli_llm

    captured = {}

    def fake_run(argv, *, input, capture_output, text, timeout):
        captured["argv"] = argv
        captured["input"] = input
        return _ok(json.dumps({"result": VALID_DIFF}))

    monkeypatch.setattr(cli_llm.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(cli_llm.subprocess, "run", fake_run)

    cli_llm.ClaudeCodeWorker().regenerate_patch("print('x')", "Use inclusive end", "tokenizer.py")

    system_prompt = captured["argv"][captured["argv"].index("--system-prompt") + 1]
    assert "Output strictly the diff" in system_prompt
    assert "unified diff" in system_prompt
    assert "File path: tokenizer.py" in captured["input"]
    assert "print('x')" in captured["input"]
    assert "Use inclusive end" in captured["input"]


def test_judge_prompt_assembly_preserves_existing_summary_contract(monkeypatch):
    import arena.cli_llm as cli_llm

    captured = {}

    def fake_run(argv, *, input, capture_output, text, timeout):
        captured["argv"] = argv
        captured["input"] = input
        return _ok(json.dumps({"result": "All components were load-bearing."}))

    monkeypatch.setattr(cli_llm.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(cli_llm.subprocess, "run", fake_run)

    result = cli_llm.ClaudeCodeJudge().summarize("F1", "c0: load_bearing=True")

    assert result == "All components were load-bearing."
    system_prompt = captured["argv"][captured["argv"].index("--system-prompt") + 1]
    assert "calibration judge" in system_prompt
    assert "Be terse" in system_prompt
    assert "Fixture: F1" in captured["input"]
    assert "c0: load_bearing=True" in captured["input"]
    assert "Summarize in one sentence." in captured["input"]


def test_claude_code_error_includes_provider_and_exit_code_without_prompt_leakage(monkeypatch):
    import arena.cli_llm as cli_llm

    def fake_run(argv, *, input, capture_output, text, timeout):
        return SimpleNamespace(
            returncode=9,
            stdout="SOURCE leaked to stdout",
            stderr="bad failure REASON leaked to stderr",
        )

    monkeypatch.setattr(cli_llm.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(cli_llm.subprocess, "run", fake_run)

    with pytest.raises(cli_llm.CliModelError) as exc:
        cli_llm.ClaudeCodeWorker().regenerate_patch("SOURCE", "REASON", "tokenizer.py")

    msg = str(exc.value)
    assert "claude-code" in msg
    assert "exit code 9" in msg
    assert "SOURCE" not in msg
    assert "REASON" not in msg


def test_timeout_converts_to_cli_model_error_without_prompt_leakage(monkeypatch):
    import arena.cli_llm as cli_llm

    def fake_run(argv, *, input, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(argv, timeout, output="SOURCE", stderr="REASON")

    monkeypatch.setattr(cli_llm.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(cli_llm.subprocess, "run", fake_run)

    with pytest.raises(cli_llm.CliModelError) as exc:
        cli_llm.ClaudeCodeWorker(timeout_seconds=3).regenerate_patch("SOURCE", "REASON", "tokenizer.py")

    msg = str(exc.value)
    assert "claude-code" in msg
    assert "timed out after 3s" in msg
    assert "SOURCE" not in msg
    assert "REASON" not in msg


def test_codex_worker_uses_read_only_ephemeral_stdin_output_file_and_cleans_up(monkeypatch):
    import arena.cli_llm as cli_llm

    captured = {}

    def fake_run(argv, *, input, capture_output, text, timeout):
        captured["argv"] = argv
        captured["input"] = input
        output_path = Path(argv[argv.index("--output-last-message") + 1])
        captured["output_path"] = output_path
        output_path.write_text(VALID_DIFF)
        return _ok("ignored stdout")

    monkeypatch.setattr(cli_llm.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(cli_llm.subprocess, "run", fake_run)

    result = cli_llm.CodexWorker(model="o3").regenerate_patch("SOURCE", "REASON", "tokenizer.py")

    assert result == VALID_DIFF
    argv = captured["argv"]
    assert argv[:2] == ["codex", "exec"]
    assert "--skip-git-repo-check" in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in argv
    assert "--ignore-rules" in argv
    assert argv[argv.index("--model") + 1] == "o3"
    assert argv[-1] == "-"
    assert "SOURCE" in captured["input"]
    assert not captured["output_path"].exists()


def test_codex_empty_output_file_falls_back_to_stdout_and_cleans_up(monkeypatch):
    import arena.cli_llm as cli_llm

    captured = {}

    def fake_run(argv, *, input, capture_output, text, timeout):
        output_path = Path(argv[argv.index("--output-last-message") + 1])
        captured["output_path"] = output_path
        output_path.write_text("")
        return _ok(VALID_DIFF)

    monkeypatch.setattr(cli_llm.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(cli_llm.subprocess, "run", fake_run)

    result = cli_llm.CodexWorker().regenerate_patch("SOURCE", "REASON", "tokenizer.py")

    assert result == VALID_DIFF
    assert not captured["output_path"].exists()


def test_copilot_judge_uses_noninteractive_no_tool_flags_and_parses_jsonl(monkeypatch):
    import arena.cli_llm as cli_llm

    captured = {}
    stdout = "\n".join([
        json.dumps({"type": "session.started", "data": {}}),
        json.dumps({"type": "message", "role": "assistant", "content": "Copilot summary."}),
    ])

    def fake_run(argv, *, input, capture_output, text, timeout):
        captured["argv"] = argv
        captured["input"] = input
        return _ok(stdout)

    monkeypatch.setattr(cli_llm.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(cli_llm.subprocess, "run", fake_run)

    result = cli_llm.CopilotJudge(model="gpt-5.2", effort="max").summarize("F1", "c0: true")

    assert result == "Copilot summary."
    argv = captured["argv"]
    assert argv[0] == "copilot"
    assert "-p" in argv
    prompt_arg = argv[argv.index("-p") + 1]
    assert "Fixture: F1" in prompt_arg
    assert "c0: true" in prompt_arg
    assert captured["input"] is None
    assert argv[argv.index("--model") + 1] == "gpt-5.2"
    assert argv[argv.index("--effort") + 1] == "max"
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--stream") + 1] == "off"
    assert "--no-custom-instructions" in argv
    assert "--disable-builtin-mcps" in argv
    assert "--no-remote" in argv
    assert "--no-ask-user" in argv
    assert "--available-tools=" in argv
    assert any(arg.startswith("--secret-env-vars=") for arg in argv)


def test_malformed_json_output_falls_back_to_raw_stdout_for_claude_and_copilot(monkeypatch):
    import arena.cli_llm as cli_llm

    def fake_run(argv, *, input, capture_output, text, timeout):
        return _ok("plain text output")

    monkeypatch.setattr(cli_llm.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(cli_llm.subprocess, "run", fake_run)

    assert cli_llm.ClaudeCodeJudge().summarize("F1", "summary") == "plain text output"
    assert cli_llm.CopilotJudge().summarize("F1", "summary") == "plain text output"


def test_missing_cli_binary_raises_clear_error(monkeypatch):
    import arena.cli_llm as cli_llm

    monkeypatch.setattr(cli_llm.shutil, "which", lambda exe: None)

    with pytest.raises(cli_llm.CliModelError) as exc:
        cli_llm.ClaudeCodeWorker().regenerate_patch("SOURCE", "REASON", "tokenizer.py")

    msg = str(exc.value)
    assert "missing executable" in msg
    assert "claude" in msg
    assert "SOURCE" not in msg
    assert "REASON" not in msg


def test_build_cli_models_maps_providers_defaults_and_rejects_unknown_provider():
    import arena.cli_llm as cli_llm

    worker, judge = cli_llm.build_cli_models("claude-code")
    assert isinstance(worker, cli_llm.ClaudeCodeWorker)
    assert isinstance(judge, cli_llm.ClaudeCodeJudge)
    assert worker.model == "haiku"
    assert judge.model == "opus"
    assert worker.effort == "low"
    assert judge.effort == "max"

    worker, judge = cli_llm.build_cli_models("codex")
    assert isinstance(worker, cli_llm.CodexWorker)
    assert isinstance(judge, cli_llm.CodexJudge)
    assert worker.model is None
    assert judge.model is None

    worker, judge = cli_llm.build_cli_models("copilot", worker_model="gpt-x", judge_model="gpt-y", effort="high", timeout_seconds=9)
    assert isinstance(worker, cli_llm.CopilotWorker)
    assert isinstance(judge, cli_llm.CopilotJudge)
    assert worker.model == "gpt-x"
    assert judge.model == "gpt-y"
    assert worker.effort == "high"
    assert judge.effort == "high"
    assert worker.timeout_seconds == 9
    assert judge.timeout_seconds == 9

    with pytest.raises(ValueError):
        cli_llm.build_cli_models("nope")
