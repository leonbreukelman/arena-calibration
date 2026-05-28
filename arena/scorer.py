"""Tier-1 mechanical Scorer.

Runs each fixture's measurement command in baseline and patched working
directories, parses the failure count from pytest stdout, computes a score
delta, and emits a ScorerVerdict under strict-greater-than acceptance.

No LLMs. No judgment calls. Subprocess + regex parse + integer comparison.

The Scorer is responsible only for:
  - executing the measurement
  - parsing the result
  - comparing baseline vs patched
  - emitting promote / reject

It is NOT responsible for:
  - judging whether the patch generalizes (F3 demonstrates this gap; the
    Verifier's patch-generalization axis handles it, not the Scorer)
  - judging whether the reasoning supports the patch (the Verifier's
    reasoning-ablation axis handles it)
  - any LLM-driven check whatsoever
"""
from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from arena.fixtures import Fixture, ScorerVerdict


class FixtureIntegrityStatus(str, Enum):
    """Whether the observed test counts match the manifest's expectations.

    This is integrity reporting on the fixture itself, NOT a Scorer verdict
    on the patch. A fixture in bad integrity means the calibration set is
    broken and the Scorer's verdict on it cannot be trusted -- but the
    Scorer still emits a verdict based on observed counts.
    """
    OK = "ok"
    BASELINE_MISMATCH = "baseline_mismatch"
    PATCHED_MISMATCH = "patched_mismatch"
    BOTH_MISMATCH = "both_mismatch"


@dataclass(frozen=True)
class MeasurementResult:
    """Raw result of running the measurement command in one tree."""
    exit_code: int
    failed: int
    errors: int
    passed: int
    timed_out: bool
    stdout_tail: str
    stderr_tail: str

    @property
    def fail_count(self) -> int:
        """The Scorer's signal: failures + errors. Lower is better."""
        return self.failed + self.errors


@dataclass(frozen=True)
class ScoreReport:
    """Per-fixture Scorer output."""
    fixture_id: str
    baseline: MeasurementResult
    patched: MeasurementResult
    score_delta: int  # baseline.fail_count - patched.fail_count
    verdict: ScorerVerdict
    integrity: FixtureIntegrityStatus
    integrity_notes: list[str] = field(default_factory=list)

    @property
    def integrity_ok(self) -> bool:
        return self.integrity == FixtureIntegrityStatus.OK


# pytest short summary line: "1 failed, 2 passed in 0.02s"
# or         "==== 1 failed in 0.02s ====" / "==== 1 passed in 0.01s ===="
# Match individual count tokens regardless of surrounding line shape.
_COUNT_PATTERN = re.compile(r"(\d+)\s+(failed|passed|error|errors|skipped)\b")
_TAIL_LINES = 40


def _parse_pytest_counts(stdout: str) -> tuple[int, int, int]:
    """Return (failed, errors, passed) from pytest stdout.

    Walks every (count, label) pair found. Last occurrence wins per label,
    because pytest may print intermediate progress and the final summary
    appears last.
    """
    failed = errors = passed = 0
    for match in _COUNT_PATTERN.finditer(stdout):
        n = int(match.group(1))
        label = match.group(2)
        if label == "failed":
            failed = n
        elif label in ("error", "errors"):
            errors = n
        elif label == "passed":
            passed = n
    return failed, errors, passed


def _tail(text: str, n_lines: int = _TAIL_LINES) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n_lines:])


def _run_measurement(
    command: str,
    cwd: Path,
    timeout_seconds: int,
) -> MeasurementResult:
    """Execute the measurement command in cwd. Returns parsed result.

    Uses shlex.split so the command in the manifest is shell-like but the
    actual subprocess invocation is not shell-interpreted -- avoids accidental
    shell injection from manifest content.
    """
    argv = shlex.split(command)
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        exit_code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        exit_code = -1
        timed_out = True

    failed, errors, passed = _parse_pytest_counts(stdout)
    return MeasurementResult(
        exit_code=exit_code,
        failed=failed,
        errors=errors,
        passed=passed,
        timed_out=timed_out,
        stdout_tail=_tail(stdout),
        stderr_tail=_tail(stderr),
    )


def _check_integrity(
    fixture: Fixture,
    baseline: MeasurementResult,
    patched: MeasurementResult,
) -> tuple[FixtureIntegrityStatus, list[str]]:
    notes: list[str] = []
    b_ok = baseline.fail_count == fixture.measurement.expected_baseline_fail
    p_ok = patched.fail_count == fixture.measurement.expected_patched_fail
    if not b_ok:
        notes.append(
            f"baseline observed fail_count={baseline.fail_count}, "
            f"manifest expected={fixture.measurement.expected_baseline_fail}"
        )
    if not p_ok:
        notes.append(
            f"patched observed fail_count={patched.fail_count}, "
            f"manifest expected={fixture.measurement.expected_patched_fail}"
        )
    if baseline.timed_out:
        notes.append("baseline measurement timed out")
    if patched.timed_out:
        notes.append("patched measurement timed out")

    if b_ok and p_ok:
        return FixtureIntegrityStatus.OK, notes
    if not b_ok and not p_ok:
        return FixtureIntegrityStatus.BOTH_MISMATCH, notes
    if not b_ok:
        return FixtureIntegrityStatus.BASELINE_MISMATCH, notes
    return FixtureIntegrityStatus.PATCHED_MISMATCH, notes


def score(fixture: Fixture) -> ScoreReport:
    """Run the Scorer over one fixture. Returns ScoreReport.

    Strict-greater-than acceptance: promote iff score_delta > 0. Ties and
    regressions reject. No LLMs, no judgment calls.
    """
    baseline = _run_measurement(
        command=fixture.measurement.command,
        cwd=fixture.baseline_dir,
        timeout_seconds=fixture.measurement.timeout_seconds,
    )
    patched = _run_measurement(
        command=fixture.measurement.command,
        cwd=fixture.patched_dir,
        timeout_seconds=fixture.measurement.timeout_seconds,
    )

    score_delta = baseline.fail_count - patched.fail_count
    verdict = ScorerVerdict.PROMOTE if score_delta > 0 else ScorerVerdict.REJECT

    integrity, notes = _check_integrity(fixture, baseline, patched)

    return ScoreReport(
        fixture_id=fixture.id,
        baseline=baseline,
        patched=patched,
        score_delta=score_delta,
        verdict=verdict,
        integrity=integrity,
        integrity_notes=notes,
    )
