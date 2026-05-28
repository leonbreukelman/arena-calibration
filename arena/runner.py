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

from arena.cli_llm import build_cli_models
from arena.fixtures import (
    Fixture,
    ScorerVerdict,
    VerifierVerdict,
    load_all_fixtures,
)
from arena.scorer import ScoreReport, score
from arena.verifier import IS_STUB, VerifyReport, verify

# Sentinel used in the output YAML when the Verifier is short-circuited.
VERIFIER_NOT_INVOKED = "not_invoked"


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
                "perturbation_outcomes": [
                    {
                        "perturbation": p.perturbation,
                        "changed_patch": p.changed_patch,
                        "sample_diffs_changed": p.sample_diffs_changed,
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
        choices=["anthropic", "claude-code", "codex", "copilot"],
        default="anthropic",
        help="LLM backend provider (default: anthropic API)",
    )
    parser.add_argument(
        "--worker-model",
        default=None,
        help="CLI provider worker model override; ignored for anthropic",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="CLI provider judge model override; ignored for anthropic",
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
    args = parser.parse_args(argv)

    worker = None
    judge = None
    if args.llm_provider != "anthropic":
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
