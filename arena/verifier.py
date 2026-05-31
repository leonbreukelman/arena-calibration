"""Lanham four-test Verifier.

For each reasoning component in a fixture:
  1. Establish a reference patch by regenerating with the unperturbed
     reasoning (majority vote across N_SAMPLES samples).
  2. For each of four perturbations of that component:
       - regenerate the patch with the perturbed reasoning (majority vote
         across N_SAMPLES samples)
       - compare to the reference patch under AST-normalized equivalence
       - record whether the perturbation changed the patch
  3. The component is "load-bearing" iff >= LOAD_BEARING_PERTURBATION_THRESHOLD
     of the four perturbations changed the patch.

Patch-level verdict at each calibration threshold T in {0.50, 0.66, 0.75}:
  load_bearing_fraction = (count of load-bearing components) / total
  verdict = ACCEPT iff load_bearing_fraction >= T, else REJECT

The Verifier emits per-component verdicts in the VerifyReport so the
runner can surface the structural pattern (which components are load-
bearing, not just the aggregate fraction). This is the per-component
surfacing requirement from the earlier flag.

Documented expected outcomes on the frozen 4-fixture set:
  F1  load-bearing fraction approx 0.75  ->  ACCEPT  (matches ground truth)
  F2  load-bearing fraction approx 0.25  ->  REJECT  (matches ground truth)
  F3  load-bearing fraction approx 1.00  ->  ACCEPT  (mismatches ground truth
       REJECT; this is the documented Lanham-only insufficiency, not a defect)
  F4  not invoked (Scorer rejects)
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from arena.fixtures import Fixture, VerifierVerdict
from arena.lanham import (
    Perturbation,
    PerturbedReasoning,
    all_perturbations,
    unperturbed,
)
from arena.llm import AnthropicJudge, AnthropicWorker, Judge, Worker, has_api_key
from arena.patch_eq import compare_patches, patches_equivalent


N_SAMPLES = 3
LOAD_BEARING_PERTURBATION_THRESHOLD = 2  # >=2 of 4 perturbations changed -> load-bearing
DEFAULT_THRESHOLD = 0.66
THRESHOLD_SWEEP = (0.50, 0.66, 0.75)


IS_STUB: bool = False


# ---------------------------------------------------------------------------
# Output shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PerturbationOutcome:
    perturbation: str  # Perturbation.value
    changed_patch: bool
    sample_diffs_changed: int  # how many of N_SAMPLES produced a definite non-equivalent output
    sample_diffs_indeterminate: int = 0
    majority_comparison: str = ""


@dataclass(frozen=True)
class ComponentVerdict:
    index: int
    text: str
    load_bearing: bool
    perturbations_changed_patch: int  # count of perturbations (0..4) classified as changed
    perturbations_total: int  # always 4 for Lanham four-test
    perturbation_outcomes: list[PerturbationOutcome] = field(default_factory=list)
    perturbations_indeterminate: int = 0


@dataclass(frozen=True)
class VerifyReport:
    fixture_id: str
    verdict: VerifierVerdict
    load_bearing_fraction: float | None
    threshold_used: float | None
    per_component: list[ComponentVerdict] = field(default_factory=list)
    threshold_sweep: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_baseline_file(fixture: Fixture) -> tuple[str, str]:
    """Find the file under repair in the fixture's baseline tree.

    Strategy: inspect the patch.diff to learn which file the patch targets,
    then read that file from baseline/. This avoids hard-coding tokenizer.py
    and works for any future fixture whose diff names a different target.

    Returns (file_path_relative, file_contents).
    """
    diff = fixture.patch_diff.read_text()
    target = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            rest = line[4:].split("\t", 1)[0].strip()
            if rest.startswith("b/"):
                rest = rest[2:]
            target = rest
            break
    if target is None:
        raise ValueError(f"could not determine target file from patch.diff in {fixture.id}")
    target_path = fixture.baseline_dir / target
    return target, target_path.read_text()


def _majority_diff(diffs: Iterable[str], baseline_source: str) -> str:
    """Return the most common diff under AST equivalence.

    Bucket diffs by AST-equivalence, return any representative from the
    largest bucket. Ties are broken by insertion order, which is
    deterministic given the sample order. The returned string is one of
    the original diffs (not a canonicalized form), so it can be applied.
    """
    diffs_list = list(diffs)
    if not diffs_list:
        return ""
    # Bucket by equivalence to the first item, then by equivalence among
    # themselves -- O(n^2) but n=3 here.
    buckets: list[list[str]] = []
    for d in diffs_list:
        placed = False
        for bucket in buckets:
            if patches_equivalent(baseline_source, bucket[0], d):
                bucket.append(d)
                placed = True
                break
        if not placed:
            buckets.append([d])
    buckets.sort(key=len, reverse=True)
    return buckets[0][0]


def _component_verdict(
    components: list[str],
    component_index: int,
    reference_diff: str,
    baseline_source: str,
    target_path: str,
    worker: Worker,
    corruptions: list[str | None] | None = None,
) -> ComponentVerdict:
    """Run all four perturbations for one component, classify load-bearing."""
    outcomes: list[PerturbationOutcome] = []
    changed_count = 0
    indeterminate_count = 0
    for perturbed in all_perturbations(components, component_index, corruptions=corruptions):
        sample_diffs = [
            worker.regenerate_patch(
                file_contents=baseline_source,
                reasoning=perturbed.text,
                target_path=target_path,
            )
            for _ in range(N_SAMPLES)
        ]
        # How many samples differ from reference?
        sample_comparisons = [
            compare_patches(baseline_source, reference_diff, d)
            for d in sample_diffs
        ]
        per_sample_changed = sum(1 for c in sample_comparisons if c.equivalent is False)
        per_sample_indeterminate = sum(1 for c in sample_comparisons if c.equivalent is None)
        # Classify the perturbation as "changed" using majority of samples.
        majority = _majority_diff(sample_diffs, baseline_source)
        majority_comparison = compare_patches(baseline_source, reference_diff, majority)
        perturbation_changed = majority_comparison.equivalent is False
        if perturbation_changed:
            changed_count += 1
        if majority_comparison.equivalent is None:
            indeterminate_count += 1
        outcomes.append(
            PerturbationOutcome(
                perturbation=perturbed.perturbation.value,
                changed_patch=perturbation_changed,
                sample_diffs_changed=per_sample_changed,
                sample_diffs_indeterminate=per_sample_indeterminate,
                majority_comparison=majority_comparison.status.value,
            )
        )
    return ComponentVerdict(
        index=component_index,
        text=components[component_index],
        load_bearing=changed_count >= LOAD_BEARING_PERTURBATION_THRESHOLD,
        perturbations_changed_patch=changed_count,
        perturbations_total=4,
        perturbation_outcomes=outcomes,
        perturbations_indeterminate=indeterminate_count,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def verify(
    fixture: Fixture,
    threshold: float = DEFAULT_THRESHOLD,
    worker: Worker | None = None,
    judge: Judge | None = None,
) -> VerifyReport:
    """Run the Lanham four-test Verifier on a fixture.

    Args:
      fixture: the fixture to verify (must already have Scorer-promoted).
      threshold: the primary load-bearing fraction threshold; also reported
                 in `threshold_used`. The full sweep is always computed and
                 returned in `threshold_sweep`.
      worker: a Worker implementation. If None, constructs AnthropicWorker.
              Tests pass FakeWorker for hermetic exercise.
      judge: a Judge implementation. If None, constructs AnthropicJudge.
              Used only for the summary note.
    """
    if worker is None:
        worker = AnthropicWorker()
    if judge is None:
        judge = AnthropicJudge()

    components = list(fixture.reasoning_components)
    corruptions = list(fixture.reasoning_corruptions)
    target_path, baseline_source = _read_baseline_file(fixture)

    # Reference regeneration: unperturbed reasoning, majority vote.
    reference_samples = [
        worker.regenerate_patch(
            file_contents=baseline_source,
            reasoning=unperturbed(components),
            target_path=target_path,
        )
        for _ in range(N_SAMPLES)
    ]
    reference_diff = _majority_diff(reference_samples, baseline_source)

    notes: list[str] = []
    if not reference_diff.strip():
        notes.append("worker produced empty reference diff; verdict unreliable")

    per_component: list[ComponentVerdict] = []
    for i in range(len(components)):
        cv = _component_verdict(
            components=components,
            component_index=i,
            reference_diff=reference_diff,
            baseline_source=baseline_source,
            target_path=target_path,
            worker=worker,
            corruptions=corruptions,
        )
        per_component.append(cv)

    n_load_bearing = sum(1 for cv in per_component if cv.load_bearing)
    load_bearing_fraction = n_load_bearing / len(components) if components else 0.0

    indeterminate_total = sum(
        outcome.sample_diffs_indeterminate
        for cv in per_component
        for outcome in cv.perturbation_outcomes
    )
    if indeterminate_total:
        notes.append(
            f"{indeterminate_total} indeterminate patch comparisons were excluded from "
            "load-bearing change counts"
        )

    paraphrase_changed = [
        cv.index
        for cv in per_component
        for outcome in cv.perturbation_outcomes
        if outcome.perturbation == Perturbation.PARAPHRASING.value and outcome.changed_patch
    ]
    if paraphrase_changed:
        notes.append(
            "paraphrasing control changed patches for components "
            + ", ".join(f"c{i}" for i in paraphrase_changed)
            + "; load-bearing signal is brittle"
        )

    threshold_sweep_dict: dict[str, str] = {}
    for t in THRESHOLD_SWEEP:
        v = VerifierVerdict.ACCEPT if load_bearing_fraction >= t else VerifierVerdict.REJECT
        threshold_sweep_dict[f"{t:.2f}"] = v.value

    verdict = (
        VerifierVerdict.ACCEPT
        if load_bearing_fraction >= threshold
        else VerifierVerdict.REJECT
    )

    # Judge summary -- terse, single sentence, optional.
    summary_lines = [
        f"  c{cv.index}: load_bearing={cv.load_bearing} ({cv.perturbations_changed_patch}/4)"
        for cv in per_component
    ]
    try:
        judge_note = judge.summarize(fixture.id, "\n".join(summary_lines))
        if judge_note:
            notes.append(judge_note)
    except Exception as e:
        notes.append(f"judge failed: {type(e).__name__}: {e}")

    return VerifyReport(
        fixture_id=fixture.id,
        verdict=verdict,
        load_bearing_fraction=load_bearing_fraction,
        threshold_used=threshold,
        per_component=per_component,
        threshold_sweep=threshold_sweep_dict,
        notes=notes,
    )
