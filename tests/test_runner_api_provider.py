from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def test_real_plan_model_calls_proves_current_fixture_budget():
    from arena.runner import plan_model_calls

    plan = plan_model_calls(fixtures_dir=Path("fixtures"), provider="xai")

    assert plan.promoted_fixtures == [
        "F1_loadbearing_good",
        "F2_fabricated_good",
        "F3_bad_passes_tests",
    ]
    assert plan.worker_calls == 165
    assert plan.judge_calls == 3
    assert plan.total_model_calls == 168
    assert plan.worst_case_worker_output_tokens == 165 * 1024
    assert plan.worst_case_judge_output_tokens == 3 * 512
    assert plan.worst_case_output_tokens == 170496


def test_real_run_call_counts_match_plan_model_calls(tmp_path):
    from arena.fixtures import load_all_fixtures
    from arena.runner import plan_model_calls, run
    from arena.verifier import _read_baseline_file

    plan = plan_model_calls(fixtures_dir=Path("fixtures"), provider="xai")
    patch_by_source = {
        _read_baseline_file(fixture)[1]: fixture.patch_diff.read_text()
        for fixture in load_all_fixtures(Path("fixtures"))
    }

    class CountingWorker:
        calls = 0

        def regenerate_patch(self, file_contents: str, reasoning: str, target_path: str) -> str:
            self.calls += 1
            return patch_by_source[file_contents]

    class CountingJudge:
        calls = 0

        def summarize(self, fixture_id: str, per_component_summary: str) -> str:
            self.calls += 1
            return "counted"

    worker = CountingWorker()
    judge = CountingJudge()

    _output_path, _summary = run(
        fixtures_dir=Path("fixtures"),
        results_dir=tmp_path,
        worker=worker,
        judge=judge,
    )

    assert worker.calls == plan.worker_calls == 165
    assert judge.calls == plan.judge_calls == 3
    assert worker.calls + judge.calls == plan.total_model_calls == 168


def test_real_run_aborts_on_worker_exception_without_retrying(tmp_path):
    from arena.runner import run

    class FailingWorker:
        calls = 0

        def regenerate_patch(self, file_contents: str, reasoning: str, target_path: str) -> str:
            self.calls += 1
            raise RuntimeError("worker boom")

    class CountingJudge:
        calls = 0

        def summarize(self, fixture_id: str, per_component_summary: str) -> str:
            self.calls += 1
            return "should not be called"

    worker = FailingWorker()
    judge = CountingJudge()

    with pytest.raises(RuntimeError, match="worker boom"):
        run(Path("fixtures"), tmp_path, worker=worker, judge=judge)

    assert worker.calls == 1
    assert judge.calls == 0


def _plan(total=168):
    return SimpleNamespace(
        provider="xai",
        promoted_fixtures=["F1_loadbearing_good", "F2_fabricated_good", "F3_bad_passes_tests"],
        worker_calls=165 if total == 168 else max(total - 3, 0),
        judge_calls=3 if total == 168 else min(total, 3),
        total_model_calls=total,
        worker_input_chars=227460,
        judge_input_chars=1200,
        rough_worker_input_tokens=56865,
        rough_judge_input_tokens=300,
        rough_input_tokens=57165,
        worst_case_worker_output_tokens=168960,
        worst_case_judge_output_tokens=1536,
        worst_case_output_tokens=170496,
        worker_model="grok-4.3",
        judge_model="grok-4.3",
    )


def test_runner_dry_run_for_xai_requires_no_keys_and_constructs_no_models(monkeypatch, tmp_path, capsys):
    from arena import runner

    def fail(*args, **kwargs):
        raise AssertionError("dry-run must not construct models or call run")

    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr(runner, "plan_model_calls", lambda *args, **kwargs: _plan(), raising=False)
    monkeypatch.setattr(runner, "build_api_models", fail, raising=False)
    monkeypatch.setattr(runner, "build_cli_models", fail)
    monkeypatch.setattr(runner, "run", fail)

    code = runner.main([
        "--fixtures-dir",
        "fixtures",
        "--results-dir",
        str(tmp_path),
        "--llm-provider",
        "xai",
        "--dry-run",
    ])

    out = capsys.readouterr().out
    assert code == 0
    assert "dry_run: true" in out
    assert "provider: xai" in out
    assert "worker_calls: 165" in out
    assert "judge_calls: 3" in out
    assert "total_model_calls: 168" in out
    assert "worst_case_output_tokens: 170496" in out


def test_runner_refuses_live_run_without_confirm_before_model_construction(monkeypatch, tmp_path, capsys):
    from arena import runner

    def fail(*args, **kwargs):
        raise AssertionError("live guard must abort before this call")

    monkeypatch.setattr(runner, "plan_model_calls", lambda *args, **kwargs: _plan(total=2), raising=False)
    monkeypatch.setattr(runner, "build_api_models", fail, raising=False)
    monkeypatch.setattr(runner, "build_cli_models", fail)
    monkeypatch.setattr(runner, "run", fail)

    code = runner.main(["--results-dir", str(tmp_path), "--llm-provider", "xai"])

    captured = capsys.readouterr()
    assert code == 2
    assert "refusing live model run" in captured.err
    assert "--confirm-live" in captured.err


def test_runner_max_model_calls_aborts_before_model_construction(monkeypatch, tmp_path, capsys):
    from arena import runner

    def fail(*args, **kwargs):
        raise AssertionError("budget guard must abort before this call")

    monkeypatch.setattr(runner, "plan_model_calls", lambda *args, **kwargs: _plan(total=168), raising=False)
    monkeypatch.setattr(runner, "build_api_models", fail, raising=False)
    monkeypatch.setattr(runner, "run", fail)

    code = runner.main([
        "--results-dir",
        str(tmp_path),
        "--llm-provider",
        "xai",
        "--confirm-live",
        "--max-model-calls",
        "10",
    ])

    captured = capsys.readouterr()
    assert code == 2
    assert "planned model calls 168 exceed --max-model-calls 10" in captured.err


def test_runner_xai_provider_constructs_api_models_when_live_confirmed(monkeypatch, tmp_path):
    from arena import runner

    fake_worker = object()
    fake_judge = object()
    captured = {}

    def fake_build_api_models(**kwargs):
        captured["build_kwargs"] = kwargs
        return fake_worker, fake_judge

    def fake_run(fixtures_dir, results_dir, *, worker=None, judge=None):
        captured["worker"] = worker
        captured["judge"] = judge
        return tmp_path / "run.yaml", {"overall_pass": True}

    monkeypatch.setattr(runner, "plan_model_calls", lambda *args, **kwargs: _plan(total=2), raising=False)
    monkeypatch.setattr(runner, "build_api_models", fake_build_api_models, raising=False)
    monkeypatch.setattr(runner, "run", fake_run)

    code = runner.main([
        "--fixtures-dir",
        "fixtures",
        "--results-dir",
        str(tmp_path),
        "--llm-provider",
        "xai",
        "--worker-model",
        "grok-worker",
        "--judge-model",
        "grok-judge",
        "--api-timeout",
        "9",
        "--confirm-live",
    ])

    assert code == 0
    assert captured["build_kwargs"] == {
        "provider": "xai",
        "worker_model": "grok-worker",
        "judge_model": "grok-judge",
        "timeout_seconds": 9,
    }
    assert captured["worker"] is fake_worker
    assert captured["judge"] is fake_judge
