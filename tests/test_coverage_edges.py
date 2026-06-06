from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest


VALID_DIFF = "--- a/tokenizer.py\n+++ b/tokenizer.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
CHANGED_DIFF = "--- a/tokenizer.py\n+++ b/tokenizer.py\n@@ -1 +1 @@\n-value = 1\n+value = 3\n"


class _RawResponse:
    def __init__(self, raw: str):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.raw.encode("utf-8")


def _fixture_yaml(
    *,
    fixture_id: str = "F9_tmp",
    components: list[str] | None = None,
    corruptions=None,
) -> str:
    import yaml

    raw = {
        "id": fixture_id,
        "kind": "load_bearing_good",
        "ground_truth": {
            "scorer_should": "promote",
            "verifier_should": "accept",
            "rationale": "temporary fixture",
        },
        "reasoning_components": ["component"] if components is None else components,
        "measurement": {
            "command": "pytest -q tests/",
            "expected_baseline_fail": 1,
            "expected_patched_fail": 0,
        },
    }
    if corruptions is not None:
        raw["reasoning_corruptions"] = corruptions
    return yaml.safe_dump(raw, sort_keys=False)


def _write_fixture_root(root: Path, manifest_text: str) -> Path:
    root.mkdir(parents=True)
    (root / "baseline").mkdir()
    (root / "patched").mkdir()
    (root / "patch.diff").write_text(VALID_DIFF)
    (root / "reasoning.md").write_text("reasoning")
    manifest = root / "manifest.yaml"
    manifest.write_text(manifest_text)
    return manifest


def test_api_visible_content_error_and_content_shape_edges(monkeypatch):
    import arena.api_llm as api_llm

    with pytest.raises(api_llm.ApiModelError, match="malformed chat-completions response"):
        api_llm._parse_visible_message_content({"choices": []}, "xai")

    joined = api_llm._parse_visible_message_content(
        {"choices": [{"message": {"content": ["raw ", {"text": "dict"}]}}]},
        "xai",
    )
    assert joined == "raw dict"

    with pytest.raises(api_llm.ApiModelError, match="visible message content"):
        api_llm._parse_visible_message_content(
            {"choices": [{"message": {"content": [{"type": "image"}]}}]},
            "xai",
        )

    with pytest.raises(api_llm.ApiModelError, match="unsupported visible message content type"):
        api_llm._parse_visible_message_content(
            {"choices": [{"message": {"content": {"text": "not accepted"}}}]},
            "xai",
        )

    monkeypatch.setattr(api_llm.urllib.request, "urlopen", lambda request, *, timeout: _RawResponse("not json"))
    test_credential = "xai-test-key"
    client = api_llm.OpenAICompatibleClient(
        provider="xai",
        base_url="https://api.x.ai/v1",
        key_env_names=("XAI_API_KEY",),
        api_key=test_credential,
    )
    with pytest.raises(api_llm.ApiModelError, match="malformed JSON"):
        client.complete_chat(model="grok-4.3", messages=[], max_tokens=1, temperature=0.0)


def test_cli_parsers_redaction_and_remaining_adapters(monkeypatch):
    import arena.cli_llm as cli_llm

    assert cli_llm._safe_snippet(None, "SECRET") == ""
    assert cli_llm._safe_snippet(b"hello SECRET", "SECRET") == "hello [redacted]"
    assert cli_llm._extract_text(None) == ""
    assert cli_llm._extract_text(["a", {"text": "b"}, None]) == "ab"
    assert cli_llm._extract_text({"data": {"output": "from data"}}) == "from data"
    assert cli_llm._parse_json_or_raw("   ") == ""
    assert cli_llm._parse_jsonl_or_raw("\n\t") == ""

    captured = {}

    def fake_run_codex(prompt: str, *, model: str | None, timeout_seconds: int) -> str:
        captured["codex_prompt"] = prompt
        captured["codex_model"] = model
        captured["codex_timeout"] = timeout_seconds
        return "codex summary"

    monkeypatch.setattr(cli_llm, "_run_codex", fake_run_codex)
    assert cli_llm.CodexJudge(model="o4", timeout_seconds=8).summarize("F1", "c0") == "codex summary"
    assert "Fixture: F1" in captured["codex_prompt"]
    assert captured["codex_model"] == "o4"
    assert captured["codex_timeout"] == 8

    def fake_run_copilot(prompt: str, *, model: str | None, effort: str | None, timeout_seconds: int):
        captured["copilot_prompt"] = prompt
        captured["copilot_model"] = model
        captured["copilot_effort"] = effort
        captured["copilot_timeout"] = timeout_seconds
        return SimpleNamespace(stdout=json.dumps({"message": {"content": "copilot diff"}}))

    monkeypatch.setattr(cli_llm, "_run_copilot", fake_run_copilot)
    worker = cli_llm.CopilotWorker(model="gpt", effort="low", timeout_seconds=4)
    assert worker.regenerate_patch("SOURCE", "REASON", "tokenizer.py") == "copilot diff"
    assert "SOURCE" in captured["copilot_prompt"]
    assert captured["copilot_model"] == "gpt"
    assert captured["copilot_effort"] == "low"
    assert captured["copilot_timeout"] == 4

    monkeypatch.setitem(cli_llm._PROVIDER_DEFAULTS, "mystery", cli_llm.ProviderDefaults(None, None, None, None))
    with pytest.raises(AssertionError, match="unhandled provider"):
        cli_llm.build_cli_models("mystery")


def test_codex_cleanup_tolerates_already_removed_output_file(monkeypatch):
    import arena.cli_llm as cli_llm

    def fake_run_cli(**kwargs):
        output_path = Path(kwargs["argv"][kwargs["argv"].index("--output-last-message") + 1])
        output_path.unlink()
        return SimpleNamespace(stdout="stdout fallback")

    monkeypatch.setattr(cli_llm.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(cli_llm, "_run_cli", fake_run_cli)

    assert cli_llm._run_codex("prompt", model=None, timeout_seconds=1) == "stdout fallback"


def test_fixture_loader_rejects_malformed_manifests_and_defaults_corruptions(tmp_path):
    from arena.fixtures import load_fixture

    with pytest.raises(FileNotFoundError, match="manifest not found"):
        load_fixture(tmp_path / "missing.yaml")

    invalid_id = _write_fixture_root(tmp_path / "bad_id", _fixture_yaml(fixture_id="bad"))
    with pytest.raises(ValueError, match="invalid fixture id"):
        load_fixture(invalid_id)

    empty_components = _write_fixture_root(
        tmp_path / "empty_components",
        _fixture_yaml(fixture_id="F9_empty", components=[]),
    )
    with pytest.raises(ValueError, match="empty reasoning_components"):
        load_fixture(empty_components)

    default_corruptions = _write_fixture_root(
        tmp_path / "default_corruptions",
        _fixture_yaml(fixture_id="F9_default", components=["a", "b"], corruptions=None),
    )
    fixture = load_fixture(default_corruptions)
    assert fixture.reasoning_corruptions == [None, None]

    mismatched = _write_fixture_root(
        tmp_path / "mismatched_corruptions",
        _fixture_yaml(fixture_id="F9_mismatch", components=["a", "b"], corruptions=["only one"]),
    )
    with pytest.raises(ValueError, match="reasoning_corruptions"):
        load_fixture(mismatched)

    missing_layout = tmp_path / "missing_layout"
    missing_layout.mkdir()
    manifest = missing_layout / "manifest.yaml"
    manifest.write_text(_fixture_yaml(fixture_id="F9_missing"))
    with pytest.raises(FileNotFoundError, match="missing required paths"):
        load_fixture(manifest)


def test_lanham_default_corruption_and_length_validation():
    from arena.lanham import Perturbation, adding_mistakes, all_perturbations

    assert "It is NOT the case that important" in adding_mistakes(["important"], 0)
    with pytest.raises(ValueError, match="expected 2 corruptions"):
        all_perturbations(["a", "b"], 0, corruptions=["one"])

    perturbations = all_perturbations(["a"], 0)
    assert [p.perturbation for p in perturbations] == list(Perturbation)


def test_anthropic_adapters_use_prompts_and_join_text_blocks(monkeypatch):
    import arena.llm as llm

    captured = {}

    class TextBlock:
        type = "text"

        def __init__(self, text: str):
            self.text = text

    class NonTextBlock:
        type = "tool_use"
        text = "ignored"

    class FakeMessages:
        def create(self, **kwargs):
            captured.setdefault("calls", []).append(kwargs)
            return SimpleNamespace(content=[TextBlock("one"), NonTextBlock(), TextBlock(" two")])

    class FakeAnthropic:
        def __init__(self):
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))

    worker = llm.AnthropicWorker(model="worker-model", max_tokens=11, temperature=0.2)
    assert worker.regenerate_patch("SOURCE", "REASON", "tokenizer.py") == "one two"

    judge = llm.AnthropicJudge(model="judge-model", max_tokens=12, temperature=0.3)
    assert judge.summarize("F1", "summary") == "one two"

    worker_call, judge_call = captured["calls"]
    assert worker_call["model"] == "worker-model"
    assert worker_call["max_tokens"] == 11
    assert worker_call["temperature"] == 0.2
    assert worker_call["system"] == llm._REGEN_SYSTEM
    assert "File path: tokenizer.py" in worker_call["messages"][0]["content"]
    assert judge_call["model"] == "judge-model"
    assert judge_call["max_tokens"] == 12
    assert judge_call["temperature"] == 0.3
    assert judge_call["system"] == llm._JUDGE_SYSTEM
    assert "Fixture: F1" in judge_call["messages"][0]["content"]


def test_has_api_key_reflects_environment(monkeypatch):
    import arena.llm as llm

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm.has_api_key() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    assert llm.has_api_key() is True


def test_patch_equivalence_edge_paths(monkeypatch):
    import arena.patch_eq as patch_eq

    assert patch_eq.normalize_patch_diff("   ") == ""
    assert patch_eq.apply_patch("value = 1\n", "   ") is None
    normalized_docstring_only = patch_eq._normalize('def f():\n    """doc only"""\n')
    assert normalized_docstring_only is not None
    assert "Pass" in normalized_docstring_only

    hunk_mismatch = "--- a/tokenizer.py\n+++ b/tokenizer.py\n@@ -1 +1 @@\n-missing\n+value = 2\n"
    assert patch_eq.apply_patch("value = 1\n", hunk_mismatch) is None

    def fake_run(argv, *, cwd, capture_output, text):
        (Path(cwd) / "tokenizer.py").unlink()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(patch_eq.subprocess, "run", fake_run)
    assert patch_eq.apply_patch("value = 1\n", VALID_DIFF) is None


def test_scorer_parsing_timeout_and_integrity_edges(monkeypatch):
    import arena.scorer as scorer
    from arena.fixtures import Fixture, Measurement, ScorerVerdict

    assert scorer._parse_pytest_counts("1 error, 2 errors, 3 failed, 4 passed") == (3, 2, 4)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=1,
            output=b"2 failed, 1 passed",
            stderr=b"timeout stderr",
        )

    monkeypatch.setattr(scorer.subprocess, "run", fake_run)
    measurement = scorer._run_measurement("pytest -q", Path("."), timeout_seconds=1)
    assert measurement.timed_out is True
    assert measurement.exit_code == -1
    assert measurement.failed == 2
    assert measurement.stderr_tail == "timeout stderr"

    report = scorer.ScoreReport(
        fixture_id="F9",
        baseline=scorer.MeasurementResult(0, 1, 0, 0, False, "", ""),
        patched=scorer.MeasurementResult(0, 0, 0, 1, False, "", ""),
        score_delta=1,
        verdict=ScorerVerdict.PROMOTE,
        integrity=scorer.FixtureIntegrityStatus.OK,
    )
    assert report.integrity_ok is True

    def fixture(expected_baseline: int, expected_patched: int):
        return cast(Fixture, SimpleNamespace(
            measurement=Measurement(
                command="pytest -q",
                expected_baseline_fail=expected_baseline,
                expected_patched_fail=expected_patched,
            )
        ))

    baseline = scorer.MeasurementResult(0, 2, 0, 0, True, "", "")
    patched = scorer.MeasurementResult(0, 3, 0, 0, True, "", "")
    status, notes = scorer._check_integrity(fixture(0, 0), baseline, patched)
    assert status == scorer.FixtureIntegrityStatus.BOTH_MISMATCH
    assert "baseline measurement timed out" in notes
    assert "patched measurement timed out" in notes

    status, _notes = scorer._check_integrity(fixture(0, 3), baseline, patched)
    assert status == scorer.FixtureIntegrityStatus.BASELINE_MISMATCH

    status, _notes = scorer._check_integrity(fixture(2, 0), baseline, patched)
    assert status == scorer.FixtureIntegrityStatus.PATCHED_MISMATCH


def test_runner_model_resolution_worker_factory_and_module_entrypoint(monkeypatch, tmp_path, capsys):
    from arena import runner
    from arena.fixtures import ScorerVerdict, VerifierVerdict

    assert runner._resolve_plan_models("anthropic", None, None) == (
        runner.WORKER_MODEL,
        runner.JUDGE_MODEL,
    )
    assert runner._resolve_plan_models("codex", None, "judge") == ("(cli default)", "judge")

    fixtures = [SimpleNamespace(id="F1"), SimpleNamespace(id="F2")]
    used_workers = []

    def fake_evaluate(fixture, worker=None, judge=None):
        used_workers.append(worker)
        return SimpleNamespace(fixture_id=fixture.id)

    monkeypatch.setattr(runner, "load_all_fixtures", lambda fixtures_dir: fixtures)
    monkeypatch.setattr(runner, "_evaluate", fake_evaluate)
    monkeypatch.setattr(runner, "_summary", lambda rows: {"overall_pass": True, "n_fixtures": len(rows)})
    monkeypatch.setattr(runner, "_row_to_dict", lambda row: {"fixture_id": row.fixture_id})

    fallback_worker = object()
    fixture_worker = object()
    output_path, summary = runner.run(
        Path("fixtures"),
        tmp_path,
        worker=fallback_worker,
        judge=object(),
        worker_factory_per_fixture=lambda fixture_id: fixture_worker if fixture_id == "F1" else None,
    )

    assert output_path.exists()
    assert summary == {"overall_pass": True, "n_fixtures": 2}
    assert used_workers == [fixture_worker, fallback_worker]

    # Execute the module guard without spending model/API quota. The freshly
    # executed module imports this already-monkeypatched scorer.score function.
    import arena.scorer as scorer

    fake_score = scorer.ScoreReport(
        fixture_id="F9",
        baseline=scorer.MeasurementResult(0, 1, 0, 0, False, "", ""),
        patched=scorer.MeasurementResult(0, 1, 0, 0, False, "", ""),
        score_delta=0,
        verdict=ScorerVerdict.REJECT,
        integrity=scorer.FixtureIntegrityStatus.OK,
    )
    fake_fixture = SimpleNamespace(
        id="F9_tmp",
        reasoning_components=["one"],
        reasoning_corruptions=[None],
        ground_truth=SimpleNamespace(verifier_should=VerifierVerdict.NOT_APPLICABLE),
    )
    monkeypatch.setattr("arena.fixtures.load_all_fixtures", lambda fixtures_dir: [fake_fixture])
    monkeypatch.setattr("arena.scorer.score", lambda fixture: fake_score)
    monkeypatch.setattr(sys, "argv", ["python -m arena.runner", "--dry-run", "--llm-provider", "xai"])

    with pytest.raises(SystemExit) as exc:
        import runpy

        with pytest.warns(RuntimeWarning, match="'arena.runner' found in sys.modules"):
            runpy.run_module("arena.runner", run_name="__main__")
    assert exc.value.code == 0
    assert "dry_run: true" in capsys.readouterr().out


def test_verifier_error_paths_changed_counts_and_default_dependencies(monkeypatch, tmp_path):
    import arena.verifier as verifier
    from arena.fixtures import load_fixture
    from arena.llm import FakeJudge, FakeWorker

    from arena.fixtures import Fixture

    no_target = cast(Fixture, SimpleNamespace(
        id="F9_no_target",
        patch_diff=tmp_path / "patch.diff",
        baseline_dir=tmp_path,
    ))
    no_target.patch_diff.write_text("--- a/tokenizer.py\n@@ -1 +1 @@\n-a\n+b\n")
    with pytest.raises(ValueError, match="could not determine target file"):
        verifier._read_baseline_file(no_target)

    assert verifier._majority_diff([], "value = 1\n") == ""

    class AlwaysChangedWorker:
        def regenerate_patch(self, file_contents: str, reasoning: str, target_path: str) -> str:
            return CHANGED_DIFF

    cv = verifier._component_verdict(
        components=["component"],
        component_index=0,
        reference_diff=VALID_DIFF,
        baseline_source="value = 1\n",
        target_path="tokenizer.py",
        worker=AlwaysChangedWorker(),
    )
    assert cv.load_bearing is True
    assert cv.perturbations_changed_patch == 4

    fixture = load_fixture(Path("fixtures/F1_loadbearing_good/manifest.yaml"))

    class EmptyDefaultWorker:
        def regenerate_patch(self, file_contents: str, reasoning: str, target_path: str) -> str:
            return ""

    class RaisingDefaultJudge:
        def summarize(self, fixture_id: str, per_component_summary: str) -> str:
            raise RuntimeError("judge boom")

    monkeypatch.setattr(verifier, "AnthropicWorker", EmptyDefaultWorker)
    monkeypatch.setattr(verifier, "AnthropicJudge", RaisingDefaultJudge)
    report = verifier.verify(fixture)
    assert any("empty reference diff" in note for note in report.notes)
    assert any("judge failed: RuntimeError: judge boom" in note for note in report.notes)

    wrong_but_applyable = (
        "--- a/tokenizer.py\n"
        "+++ b/tokenizer.py\n"
        "@@ -5,5 +5,5 @@\n"
        " \n"
        " \n"
        " def tokenize(text: str, spans: list[Span]) -> list[str]:\n"
        '-    """Return the substring of `text` covered by each span in `spans`."""\n'
        '+    """Return the substring of text covered by each span in spans."""\n'
        "     return [text[start:end] for start, end in spans]\n"
    )

    def paraphrase_responder(reasoning: str, file_contents: str, target_path: str) -> str:
        return wrong_but_applyable if "In other words" in reasoning else fixture.patch_diff.read_text()

    brittle = verifier.verify(
        fixture,
        worker=FakeWorker(paraphrase_responder),
        judge=FakeJudge(template=""),
    )
    assert any("paraphrasing control changed patches" in note for note in brittle.notes)
