from __future__ import annotations

from pathlib import Path


def test_regen_prompt_contract_makes_reasoning_authoritative_and_calibration_safe():
    import arena.llm as llm

    system = llm._REGEN_SYSTEM
    prompt = llm.build_regen_prompt(
        target_path="tokenizer.py",
        file_contents="def tokenize():\n    pass\n",
        reasoning="1. the supplied reasoning establishes a one-line change",
    )

    assert "senior software engineer" in system
    assert "constrained patch-regeneration" in system
    assert "reasoning artifact is authoritative" in system
    assert "Do not independently diagnose" in system
    assert "incomplete, contradictory, irrelevant, or insufficient" in system
    assert "exactly one trailing newline" in system
    assert "no prose, no markdown fences" in system
    assert "no-op hunk" in system
    assert "provided for location and patch-application context" in prompt
    assert "Do not infer a fix from the file contents alone" in prompt


def test_real_fixtures_expose_machine_readable_corruptions_parallel_to_components():
    from arena.fixtures import load_all_fixtures

    promoted = [
        fixture
        for fixture in load_all_fixtures(Path("fixtures"))
        if fixture.id in {"F1_loadbearing_good", "F2_fabricated_good", "F3_bad_passes_tests"}
    ]

    assert promoted
    for fixture in promoted:
        assert len(fixture.reasoning_corruptions) == len(fixture.reasoning_components)
        assert all(c and "It is NOT the case" not in c for c in fixture.reasoning_corruptions)


def test_all_perturbations_uses_fixture_specific_corruption_and_explicit_gap_marker():
    from arena.lanham import Perturbation, all_perturbations

    perturbations = all_perturbations(
        ["the real component"],
        0,
        corruptions=["the fixture-specific wrong component"],
    )
    by_kind = {p.perturbation: p.text for p in perturbations}

    assert "the fixture-specific wrong component" in by_kind[Perturbation.ADDING_MISTAKES]
    assert "It is NOT the case" not in by_kind[Perturbation.ADDING_MISTAKES]
    assert "[step omitted" in by_kind[Perturbation.FILLER_TOKENS]
    assert "..." not in by_kind[Perturbation.FILLER_TOKENS]


def test_fenced_diff_missing_final_newline_is_normalized_before_apply():
    from arena.patch_eq import apply_patch, normalize_patch_diff

    baseline = "value = 1\n"
    fenced_without_final_newline = "```diff\n--- a/tokenizer.py\n+++ b/tokenizer.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n```"
    crlf_diff = "--- a/tokenizer.py\r\n+++ b/tokenizer.py\r\n@@ -1 +1 @@\r\n-value = 1\r\n+value = 2\r\n"

    assert apply_patch(baseline, fenced_without_final_newline) == "value = 2\n"
    assert "\r" not in normalize_patch_diff(crlf_diff)


def test_patch_target_paths_cannot_escape_temp_apply_directory():
    from arena.patch_eq import _extract_target_name

    assert _extract_target_name("--- a/x.py\n+++ b/../escape.py\n") is None
    assert _extract_target_name("--- a/x.py\n+++ /tmp/escape.py\n") is None


def test_compare_patches_classifies_unappliable_outputs_as_indeterminate_not_changed():
    from arena.patch_eq import PatchComparisonStatus, compare_patches, patches_equivalent

    baseline = "value = 1\n"
    valid = "--- a/tokenizer.py\n+++ b/tokenizer.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"

    both_invalid = compare_patches(baseline, "not a diff", "also not a diff")
    one_invalid = compare_patches(baseline, valid, "not a diff")

    assert both_invalid.equivalent is None
    assert both_invalid.status == PatchComparisonStatus.INDETERMINATE_BOTH_FAILED
    assert one_invalid.equivalent is None
    assert one_invalid.status == PatchComparisonStatus.INDETERMINATE_APPLY_FAILED
    assert patches_equivalent(baseline, valid, "not a diff") is False


def test_verifier_does_not_count_apply_failures_as_load_bearing_changes():
    from arena.fixtures import load_fixture
    from arena.lanham import unperturbed
    from arena.llm import FakeJudge, FakeWorker
    from arena.verifier import verify

    fixture = load_fixture(Path("fixtures/F1_loadbearing_good/manifest.yaml"))
    reference_reasoning = unperturbed(list(fixture.reasoning_components))
    valid_diff = fixture.patch_diff.read_text()

    def responder(reasoning: str, file_contents: str, target_path: str) -> str:
        if reasoning == reference_reasoning:
            return valid_diff
        return "not a unified diff"

    report = verify(fixture, worker=FakeWorker(responder), judge=FakeJudge())

    assert report.load_bearing_fraction == 0.0
    assert report.per_component[0].perturbations_changed_patch == 0
    first_outcome = report.per_component[0].perturbation_outcomes[0]
    assert first_outcome.sample_diffs_changed == 0
    assert first_outcome.sample_diffs_indeterminate == 3
    assert any("indeterminate patch comparisons" in note for note in report.notes)


def test_exercise_verifier_detects_fixture_corruptions_and_gap_markers():
    import importlib.util

    from arena.fixtures import load_fixture
    from arena.lanham import Perturbation, all_perturbations

    spec = importlib.util.spec_from_file_location(
        "exercise_verifier", Path("exercise_verifier.py")
    )
    assert spec and spec.loader
    exercise_verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exercise_verifier)

    fixture = load_fixture(Path("fixtures/F1_loadbearing_good/manifest.yaml"))
    perturbations = all_perturbations(
        list(fixture.reasoning_components),
        0,
        corruptions=list(fixture.reasoning_corruptions),
    )
    by_kind = {p.perturbation: p.text for p in perturbations}

    assert exercise_verifier._detect_perturbation(by_kind[Perturbation.ADDING_MISTAKES]) == (
        Perturbation.ADDING_MISTAKES,
        0,
    )
    assert exercise_verifier._detect_perturbation(by_kind[Perturbation.FILLER_TOKENS]) == (
        Perturbation.FILLER_TOKENS,
        0,
    )


def test_exercise_verifier_scripted_diffs_apply_so_failures_remain_semantic():
    import importlib.util

    from arena.fixtures import load_fixture
    from arena.patch_eq import apply_patch
    from arena.verifier import _read_baseline_file

    spec = importlib.util.spec_from_file_location(
        "exercise_verifier", Path("exercise_verifier.py")
    )
    assert spec and spec.loader
    exercise_verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exercise_verifier)

    checks = {
        "F1_loadbearing_good": ["F1_CORRECT_DIFF", "F1_WRONG_DIFF_NO_FIX"],
        "F2_fabricated_good": ["F2_CORRECT_DIFF", "F2_WRONG_DIFF"],
        "F3_bad_passes_tests": ["F3_CORRECT_DIFF", "F3_WRONG_GENERAL_FIX"],
    }
    for fixture_id, diff_names in checks.items():
        fixture = load_fixture(Path(f"fixtures/{fixture_id}/manifest.yaml"))
        _target_path, baseline_source = _read_baseline_file(fixture)
        for diff_name in diff_names:
            assert apply_patch(baseline_source, getattr(exercise_verifier, diff_name)) is not None, (
                fixture_id,
                diff_name,
            )
