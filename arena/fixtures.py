"""Fixture manifest loader and validator.

A fixture is a self-contained calibration unit:

  manifest.yaml   ground truth labels and expected verdicts
  baseline/       repo state before the patch
  patched/        repo state after the patch
  patch.diff      unified diff baseline -> patched
  reasoning.md    stated reasoning, structured as numbered components

The manifest is the source of truth for fixture metadata. Baseline and
patched trees are the actual code under test. The loader validates that
the manifest is well-formed and that required paths exist on disk; it
does NOT execute the tests here -- that is the Scorer's job, kept in a
separate module so the Scorer's git SHA can be pinned independently.

Per the build-arena constitution: read before writing, verify externally.
This loader rebuilds fixture state from the filesystem on every call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class FixtureKind(str, Enum):
    LOAD_BEARING_GOOD = "load_bearing_good"
    FABRICATED_GOOD = "fabricated_good"
    BAD_PASSES_TESTS = "bad_passes_tests"
    TRIVIAL = "trivial"
    GOODHART = "goodhart"
    BAD_FAILS_TESTS = "bad_fails_tests"


class ScorerVerdict(str, Enum):
    PROMOTE = "promote"
    REJECT = "reject"


class VerifierVerdict(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    NOT_APPLICABLE = "n/a"


@dataclass(frozen=True)
class GroundTruth:
    scorer_should: ScorerVerdict
    verifier_should: VerifierVerdict
    rationale: str


@dataclass(frozen=True)
class Measurement:
    command: str
    expected_baseline_fail: int
    expected_patched_fail: int
    timeout_seconds: int = 60


@dataclass(frozen=True)
class Fixture:
    id: str
    kind: FixtureKind
    ground_truth: GroundTruth
    reasoning_components: list[str]
    reasoning_corruptions: list[str | None]
    measurement: Measurement
    root: Path

    @property
    def baseline_dir(self) -> Path:
        return self.root / "baseline"

    @property
    def patched_dir(self) -> Path:
        return self.root / "patched"

    @property
    def patch_diff(self) -> Path:
        return self.root / "patch.diff"

    @property
    def reasoning_md(self) -> Path:
        return self.root / "reasoning.md"


_ID_PATTERN = re.compile(r"^F\d+_[a-z0-9_]+$")


def load_fixture(manifest_path: Path | str) -> Fixture:
    """Load and validate a single fixture from its manifest path.

    Raises FileNotFoundError or ValueError if the manifest is malformed or
    if any required fixture file is missing. Does not execute any code.
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    raw: dict[str, Any] = yaml.safe_load(manifest_path.read_text())
    root = manifest_path.parent

    fid = raw["id"]
    if not _ID_PATTERN.match(fid):
        raise ValueError(f"invalid fixture id {fid!r}; expected F<n>_<snake>")

    kind = FixtureKind(raw["kind"])

    gt_raw = raw["ground_truth"]
    ground_truth = GroundTruth(
        scorer_should=ScorerVerdict(gt_raw["scorer_should"]),
        verifier_should=VerifierVerdict(gt_raw["verifier_should"]),
        rationale=gt_raw["rationale"].strip(),
    )

    components = list(raw["reasoning_components"])
    if not components:
        raise ValueError(f"fixture {fid} has empty reasoning_components")
    corruptions_raw = raw.get("reasoning_corruptions", raw.get("corruptions"))
    if corruptions_raw is None:
        corruptions: list[str | None] = [None] * len(components)
    else:
        corruptions = list(corruptions_raw)
        if len(corruptions) != len(components):
            raise ValueError(
                f"fixture {fid} has {len(corruptions)} reasoning_corruptions "
                f"for {len(components)} reasoning_components"
            )

    meas_raw = raw["measurement"]
    measurement = Measurement(
        command=meas_raw["command"],
        expected_baseline_fail=int(meas_raw["expected_baseline_fail"]),
        expected_patched_fail=int(meas_raw["expected_patched_fail"]),
        timeout_seconds=int(meas_raw.get("timeout_seconds", 60)),
    )

    fixture = Fixture(
        id=fid,
        kind=kind,
        ground_truth=ground_truth,
        reasoning_components=components,
        reasoning_corruptions=corruptions,
        measurement=measurement,
        root=root,
    )

    _validate_fixture_layout(fixture)
    return fixture


def _validate_fixture_layout(fx: Fixture) -> None:
    """Verify required files exist on disk. Does not execute anything."""
    required = [
        fx.baseline_dir,
        fx.patched_dir,
        fx.patch_diff,
        fx.reasoning_md,
    ]
    missing = [p for p in required if not p.exists()]
    if missing:
        rels = ", ".join(str(p.relative_to(fx.root)) for p in missing)
        raise FileNotFoundError(f"fixture {fx.id} missing required paths: {rels}")


def load_all_fixtures(fixtures_dir: Path | str) -> list[Fixture]:
    """Load every fixture under fixtures_dir. Returns sorted by id."""
    fixtures_dir = Path(fixtures_dir)
    manifests = sorted(fixtures_dir.glob("*/manifest.yaml"))
    return [load_fixture(m) for m in manifests]
