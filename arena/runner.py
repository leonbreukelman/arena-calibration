"""Runner: loads fixtures, calls Scorer, short-circuits on reject, calls
Verifier on promote, emits a single timestamped YAML discrimination matrix.

Short-circuit invariant: the Verifier is invoked if and only if the Scorer
emits PROMOTE. F4 (kind=trivial) is the canonical exercise of this path --
its Scorer verdict is REJECT and its Verifier verdict must be recorded as
NOT_INVOKED, not as NOT_APPLICABLE returned by the Verifier itself.

Runner is a pure driver. It does not judge any individual fixture; it
records observed Scorer and Verifier verdicts, compares them to manifest
ground truth, and emits the matrix. The exit code summarizes whether the
calibration set as a whole agrees with ground truth.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from arena.api_llm import DEFAULT_TIMEOUT_SECONDS, PROVIDER_CONFIGS, build_api_models
from arena.cli_llm import build_cli_models
from arena.fixtures import (
    Fixture,
    ScorerVerdict,
    VerifierVerdict,
    load_all_fixtures,
)
from arena.lanham import all_perturbations, unperturbed
from arena.llm import (
    JUDGE_MAX_TOKENS,
    JUDGE_MODEL,
    WORKER_MAX_TOKENS,
    WORKER_MODEL,
    _JUDGE_SYSTEM,
    _REGEN_SYSTEM,
    build_judge_prompt,
    build_regen_prompt,
)
from arena.scorer import ScoreReport, score
from arena.verifier import IS_STUB, N_SAMPLES, VerifyReport, _read_baseline_file, verify

# Sentinel used in the output YAML when the Verifier is short-circuited.
VERIFIER_NOT_INVOKED = "not_invoked"
API_PROVIDERS = frozenset(PROVIDER_CONFIGS)
CLI_PROVIDERS = frozenset({"claude-code", "codex", "copilot"})
ALL_PROVIDERS = ("anthropic", "xai", "gemini", "openrouter", "claude-code", "codex", "copilot")
@dataclass(frozen=True)
class ModelCallPlan:
    provider: str
    worker_model: str
    judge_model: str
    promoted_fixtures: list[str]
    worker_calls: int
    judge_calls: int
    total_model_calls: int
    worker_input_chars: int
    judge_input_chars: int
    rough_worker_input_tokens: int
    rough_judge_input_tokens: int
    rough_input_tokens: int
    worst_case_worker_output_tokens: int
    worst_case_judge_output_tokens: int
    worst_case_output_tokens: int


@dataclass(frozen=True)
class FixtureRow:
    fixture_id: str
    kind: str
    baseline_fail: int
    patched_fail: int
    score_delta: int
    scorer_verdict: str
    scorer_expected: str
    scorer_match: bool
    verifier_verdict: str  # ScorerVerdict.value or VERIFIER_NOT_INVOKED
    verifier_expected: str
    verifier_match: bool
    verifier_invoked: bool
    load_bearing_fraction: float | None
    per_component: list[dict[str, Any]]
    threshold_sweep: dict[str, str]
    integrity: str
    integrity_notes: list[str]
    notes: list[str]


def _rough_token_count(chars: int) -> int:
    return (chars + 3) // 4


def _resolve_plan_models(
    provider: str,
    worker_model: str | None,
    judge_model: str | None,
) -> tuple[str, str]:
    if provider == "anthropic":
        return worker_model or WORKER_MODEL, judge_model or JUDGE_MODEL
    if provider in API_PROVIDERS:
        config = PROVIDER_CONFIGS[provider]
        return (
            worker_model or config.default_worker_model,
            judge_model or config.default_judge_model,
        )
    return worker_model or "(cli default)", judge_model or "(cli default)"


def _judge_prompt_chars(fixture: Fixture) -> int:
    summary_lines = [
        f"  c{i}: load_bearing=<unknown> (<unknown>/4)"
        for i, _component in enumerate(fixture.reasoning_components)
    ]
    summary_text = "\n".join(summary_lines)
    prompt = build_judge_prompt(fixture.id, summary_text)
    return len(_JUDGE_SYSTEM) + len(prompt)


def plan_model_calls(
    fixtures_dir: Path,
    provider: str,
    worker_model: str | None = None,
    judge_model: str | None = None,
) -> ModelCallPlan:
    """Plan live model calls without constructing model adapters or invoking verifier."""
    worker_name, judge_name = _resolve_plan_models(provider, worker_model, judge_model)
    fixtures = load_all_fixtures(fixtures_dir)
    promoted: list[str] = []
    worker_calls = 0
    judge_calls = 0
    worker_input_chars = 0
    judge_input_chars = 0

    for fixture in fixtures:
        score_rep = score(fixture)
        if score_rep.verdict != ScorerVerdict.PROMOTE:
            continue
        promoted.append(fixture.id)
        components = list(fixture.reasoning_components)
        corruptions = list(fixture.reasoning_corruptions)
        target_path, baseline_source = _read_baseline_file(fixture)

        reference_prompt = build_regen_prompt(
            target_path=target_path,
            file_contents=baseline_source,
            reasoning=unperturbed(components),
        )
        worker_calls += N_SAMPLES
        worker_input_chars += N_SAMPLES * (len(_REGEN_SYSTEM) + len(reference_prompt))

        for i in range(len(components)):
            for perturbed in all_perturbations(components, i, corruptions=corruptions):
                prompt = build_regen_prompt(
                    target_path=target_path,
                    file_contents=baseline_source,
                    reasoning=perturbed.text,
                )
                worker_calls += N_SAMPLES
                worker_input_chars += N_SAMPLES * (len(_REGEN_SYSTEM) + len(prompt))

        judge_calls += 1
        judge_input_chars += _judge_prompt_chars(fixture)

    worst_worker_output = worker_calls * WORKER_MAX_TOKENS
    worst_judge_output = judge_calls * JUDGE_MAX_TOKENS
    rough_worker_input = _rough_token_count(worker_input_chars)
    rough_judge_input = _rough_token_count(judge_input_chars)
    return ModelCallPlan(
        provider=provider,
        worker_model=worker_name,
        judge_model=judge_name,
        promoted_fixtures=promoted,
        worker_calls=worker_calls,
        judge_calls=judge_calls,
        total_model_calls=worker_calls + judge_calls,
        worker_input_chars=worker_input_chars,
        judge_input_chars=judge_input_chars,
        rough_worker_input_tokens=rough_worker_input,
        rough_judge_input_tokens=rough_judge_input,
        rough_input_tokens=rough_worker_input + rough_judge_input,
        worst_case_worker_output_tokens=worst_worker_output,
        worst_case_judge_output_tokens=worst_judge_output,
        worst_case_output_tokens=worst_worker_output + worst_judge_output,
    )


def _print_dry_run(plan: ModelCallPlan) -> None:
    print("dry_run: true")
    print(f"provider: {plan.provider}")
    print(f"worker_model: {plan.worker_model}")
    print(f"judge_model: {plan.judge_model}")
    print(f"promoted_fixtures: {', '.join(plan.promoted_fixtures)}")
    print(f"worker_calls: {plan.worker_calls}")
    print(f"judge_calls: {plan.judge_calls}")
    print(f"total_model_calls: {plan.total_model_calls}")
    print(f"worker_input_chars: {plan.worker_input_chars}")
    print(f"judge_input_chars: {plan.judge_input_chars}")
    print(f"rough_worker_input_tokens: {plan.rough_worker_input_tokens}")
    print(f"rough_judge_input_tokens: {plan.rough_judge_input_tokens}")
    print(f"rough_input_tokens: {plan.rough_input_tokens}")
    print(f"worst_case_worker_output_tokens: {plan.worst_case_worker_output_tokens}")
    print(f"worst_case_judge_output_tokens: {plan.worst_case_judge_output_tokens}")
    print(f"worst_case_output_tokens: {plan.worst_case_output_tokens}")


def _evaluate(
    fixture: Fixture,
    worker=None,
    judge=None,
) -> FixtureRow:
    """Run Scorer; short-circuit-or-Verifier; assemble a row.

    worker/judge are forwarded to verify() when the Verifier is invoked.
    None means "use real Anthropic-backed defaults"."""
    score_rep: ScoreReport = score(fixture)

    scorer_actual = score_rep.verdict.value
    scorer_expected = fixture.ground_truth.scorer_should.value
    scorer_match = scorer_actual == scorer_expected

    verifier_invoked = score_rep.verdict == ScorerVerdict.PROMOTE
    verifier_expected = fixture.ground_truth.verifier_should.value

    if verifier_invoked:
        v_rep: VerifyReport = verify(fixture, worker=worker, judge=judge)
        verifier_actual = v_rep.verdict.value
        verifier_match = verifier_actual == verifier_expected
        load_bearing_fraction = v_rep.load_bearing_fraction
        per_component = [
            {
                "index": c.index,
                "text": c.text,
                "load_bearing": c.load_bearing,
                "perturbations_changed_patch": c.perturbations_changed_patch,
                "perturbations_total": c.perturbations_total,
                "perturbations_indeterminate": c.perturbations_indeterminate,
                "perturbation_outcomes": [
                    {
                        "perturbation": p.perturbation,
                        "changed_patch": p.changed_patch,
                        "sample_diffs_changed": p.sample_diffs_changed,
                        "sample_diffs_indeterminate": p.sample_diffs_indeterminate,
                        "majority_comparison": p.majority_comparison,
                    }
                    for p in c.perturbation_outcomes
                ],
            }
            for c in v_rep.per_component
        ]
        threshold_sweep = dict(v_rep.threshold_sweep)
        notes = list(v_rep.notes)
    else:
        # Short-circuit. Verifier MUST NOT be invoked.
        verifier_actual = VERIFIER_NOT_INVOKED
        # Ground truth says "n/a" for short-circuited fixtures; non-invocation
        # is the correct behavior, so it matches.
        verifier_match = verifier_expected == VerifierVerdict.NOT_APPLICABLE.value
        load_bearing_fraction = None
        per_component = []
        threshold_sweep = {}
        notes = ["verifier not invoked (scorer rejected)"]

    return FixtureRow(
        fixture_id=fixture.id,
        kind=fixture.kind.value,
        baseline_fail=score_rep.baseline.fail_count,
        patched_fail=score_rep.patched.fail_count,
        score_delta=score_rep.score_delta,
        scorer_verdict=scorer_actual,
        scorer_expected=scorer_expected,
        scorer_match=scorer_match,
        verifier_verdict=verifier_actual,
        verifier_expected=verifier_expected,
        verifier_match=verifier_match,
        verifier_invoked=verifier_invoked,
        load_bearing_fraction=load_bearing_fraction,
        per_component=per_component,
        threshold_sweep=threshold_sweep,
        integrity=score_rep.integrity.value,
        integrity_notes=list(score_rep.integrity_notes),
        notes=notes,
    )


def _row_to_dict(row: FixtureRow) -> dict[str, Any]:
    return {
        "fixture_id": row.fixture_id,
        "kind": row.kind,
        "baseline_fail": row.baseline_fail,
        "patched_fail": row.patched_fail,
        "score_delta": row.score_delta,
        "scorer": {
            "verdict": row.scorer_verdict,
            "expected": row.scorer_expected,
            "match": row.scorer_match,
        },
        "verifier": {
            "verdict": row.verifier_verdict,
            "expected": row.verifier_expected,
            "match": row.verifier_match,
            "invoked": row.verifier_invoked,
            "load_bearing_fraction": row.load_bearing_fraction,
            "threshold_sweep": row.threshold_sweep,
            "per_component": row.per_component,
        },
        "integrity": {
            "status": row.integrity,
            "notes": row.integrity_notes,
        },
        "notes": row.notes,
    }


def _summary(rows: list[FixtureRow]) -> dict[str, Any]:
    n = len(rows)
    scorer_match = sum(1 for r in rows if r.scorer_match)
    verifier_match = sum(1 for r in rows if r.verifier_match)
    integrity_ok = sum(1 for r in rows if r.integrity == "ok")
    verifier_invoked = sum(1 for r in rows if r.verifier_invoked)
    overall_pass = (
        scorer_match == n and verifier_match == n and integrity_ok == n
    )
    return {
        "n_fixtures": n,
        "scorer_matches_ground_truth": f"{scorer_match}/{n}",
        "verifier_matches_ground_truth": f"{verifier_match}/{n}",
        "integrity_ok": f"{integrity_ok}/{n}",
        "verifier_invoked": f"{verifier_invoked}/{n}",
        "overall_pass": overall_pass,
    }


def run(
    fixtures_dir: Path,
    results_dir: Path,
    worker=None,
    judge=None,
    worker_factory_per_fixture=None,
) -> tuple[Path, dict[str, Any]]:
    """Execute the calibration run. Returns (output_path, summary_dict).

    worker/judge: shared Verifier dependencies for the whole run. None means
    use real Anthropic-backed defaults.

    worker_factory_per_fixture: optional callable mapping fixture_id -> Worker.
    Used by the hermetic exercise to script different workers per fixture.
    Overrides `worker` for the matching fixture only.
    """
    fixtures = load_all_fixtures(fixtures_dir)
    rows: list[FixtureRow] = []
    for fx in fixtures:
        fx_worker = worker
        if worker_factory_per_fixture is not None:
            fx_worker = worker_factory_per_fixture(fx.id) or worker
        rows.append(_evaluate(fx, worker=fx_worker, judge=judge))
    summary = _summary(rows)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = results_dir / f"run_{timestamp}.yaml"
    results_dir.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "metadata": {
            "timestamp_utc": timestamp,
            "fixtures_dir": str(fixtures_dir.resolve()),
            "verifier_is_stub": IS_STUB,
        },
        "summary": summary,
        "fixtures": [_row_to_dict(r) for r in rows],
    }

    with output_path.open("w") as f:
        yaml.safe_dump(payload, f, sort_keys=False, default_flow_style=False)

    return output_path, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=Path("fixtures"),
        help="Path to the fixtures directory (default: ./fixtures)",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results"),
        help="Path to the results directory (default: ./results)",
    )
    parser.add_argument(
        "--llm-provider",
        choices=ALL_PROVIDERS,
        default="anthropic",
        help="LLM backend provider (default: anthropic API; live run requires --confirm-live)",
    )
    parser.add_argument(
        "--worker-model",
        default=None,
        help="Worker model override for API/CLI providers; anthropic overrides are plan-only",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Judge model override for API/CLI providers; anthropic overrides are plan-only",
    )
    parser.add_argument(
        "--cli-effort",
        default=None,
        help="Override CLI reasoning effort for both worker and judge where supported",
    )
    parser.add_argument(
        "--cli-timeout",
        type=int,
        default=180,
        help="Per CLI model call timeout in seconds",
    )
    parser.add_argument(
        "--api-timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per API model call timeout in seconds",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan live model calls and budget exposure without constructing model adapters",
    )
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Required to execute any live model run",
    )
    parser.add_argument(
        "--max-model-calls",
        type=int,
        default=None,
        help="Abort before live execution if planned model calls exceed this ceiling",
    )
    args = parser.parse_args(argv)

    plan = plan_model_calls(
        args.fixtures_dir,
        provider=args.llm_provider,
        worker_model=args.worker_model,
        judge_model=args.judge_model,
    )

    if args.dry_run:
        _print_dry_run(plan)
        return 0

    if not args.confirm_live:
        print(
            "refusing live model run: pass --dry-run to inspect call counts or "
            "--confirm-live to spend API/subscription quota",
            file=sys.stderr,
        )
        return 2

    if (
        args.max_model_calls is not None
        and plan.total_model_calls > args.max_model_calls
    ):
        print(
            f"planned model calls {plan.total_model_calls} exceed "
            f"--max-model-calls {args.max_model_calls}",
            file=sys.stderr,
        )
        return 2

    worker = None
    judge = None
    if args.llm_provider in API_PROVIDERS:
        worker, judge = build_api_models(
            provider=args.llm_provider,
            worker_model=args.worker_model,
            judge_model=args.judge_model,
            timeout_seconds=args.api_timeout,
        )
    elif args.llm_provider in CLI_PROVIDERS:
        worker, judge = build_cli_models(
            provider=args.llm_provider,
            worker_model=args.worker_model,
            judge_model=args.judge_model,
            effort=args.cli_effort,
            timeout_seconds=args.cli_timeout,
        )

    output_path, summary = run(
        args.fixtures_dir,
        args.results_dir,
        worker=worker,
        judge=judge,
    )
    print(f"wrote {output_path}")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0 if summary["overall_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
