from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def test_runner_default_provider_does_not_construct_cli_models(monkeypatch, tmp_path):
    from arena import runner

    captured = {}

    def fake_run(fixtures_dir, results_dir, *, worker=None, judge=None):
        captured["fixtures_dir"] = fixtures_dir
        captured["results_dir"] = results_dir
        captured["worker"] = worker
        captured["judge"] = judge
        return tmp_path / "run.yaml", {"overall_pass": True}

    def fail_build_cli_models(*args, **kwargs):
        raise AssertionError("CLI models must not be built for default provider")

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(runner, "build_cli_models", fail_build_cli_models)
    monkeypatch.setattr(
        runner,
        "plan_model_calls",
        lambda *args, **kwargs: SimpleNamespace(total_model_calls=0),
    )

    code = runner.main([
        "--fixtures-dir",
        "fixtures",
        "--results-dir",
        str(tmp_path),
        "--confirm-live",
    ])

    assert code == 0
    assert captured["fixtures_dir"] == Path("fixtures")
    assert captured["results_dir"] == tmp_path
    assert captured["worker"] is None
    assert captured["judge"] is None


def test_runner_claude_code_provider_constructs_cli_models(monkeypatch, tmp_path):
    from arena import runner

    fake_worker = object()
    fake_judge = object()
    captured = {}

    def fake_build_cli_models(**kwargs):
        captured["build_kwargs"] = kwargs
        return fake_worker, fake_judge

    def fake_run(fixtures_dir, results_dir, *, worker=None, judge=None):
        captured["worker"] = worker
        captured["judge"] = judge
        return tmp_path / "run.yaml", {"overall_pass": True}

    monkeypatch.setattr(runner, "build_cli_models", fake_build_cli_models)
    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(
        runner,
        "plan_model_calls",
        lambda *args, **kwargs: SimpleNamespace(total_model_calls=0),
    )

    code = runner.main([
        "--fixtures-dir",
        "fixtures",
        "--results-dir",
        str(tmp_path),
        "--llm-provider",
        "claude-code",
        "--worker-model",
        "haiku",
        "--judge-model",
        "opus",
        "--cli-effort",
        "max",
        "--cli-timeout",
        "321",
        "--confirm-live",
    ])

    assert code == 0
    assert captured["build_kwargs"] == {
        "provider": "claude-code",
        "worker_model": "haiku",
        "judge_model": "opus",
        "effort": "max",
        "timeout_seconds": 321,
    }
    assert captured["worker"] is fake_worker
    assert captured["judge"] is fake_judge


def test_runner_anthropic_ignores_cli_model_flags_and_preserves_default_api_path(monkeypatch, tmp_path):
    from arena import runner

    captured = {}

    def fake_run(fixtures_dir, results_dir, *, worker=None, judge=None):
        captured["worker"] = worker
        captured["judge"] = judge
        return tmp_path / "run.yaml", {"overall_pass": True}

    def fail_build_cli_models(*args, **kwargs):
        raise AssertionError("CLI models must not be built for anthropic provider")

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(runner, "build_cli_models", fail_build_cli_models)
    monkeypatch.setattr(
        runner,
        "plan_model_calls",
        lambda *args, **kwargs: SimpleNamespace(total_model_calls=0),
    )

    code = runner.main([
        "--fixtures-dir",
        "fixtures",
        "--results-dir",
        str(tmp_path),
        "--llm-provider",
        "anthropic",
        "--worker-model",
        "ignored-worker",
        "--judge-model",
        "ignored-judge",
        "--cli-effort",
        "ignored-effort",
        "--confirm-live",
    ])

    assert code == 0
    assert captured["worker"] is None
    assert captured["judge"] is None
