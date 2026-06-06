from __future__ import annotations

import json
import runpy
import shutil
import sys
from pathlib import Path

import pytest


def test_project_model_v0_fixtures_have_required_shape_and_f_label_coverage():
    from arena.project_model_fixtures import (
        ADVISORY_SIGNAL_SCHEMA_VERSION,
        PROJECT_MODEL_SCHEMA_VERSION,
        REQUIRED_ADVISORY_FIELDS,
        load_all_project_model_fixtures,
    )

    fixtures = load_all_project_model_fixtures(Path("fixtures/project_model_v0"))

    assert [fixture.id for fixture in fixtures] == [
        "F1_project_model_aligned",
        "F2_project_model_decorative",
        "F3_project_model_code_too_narrow",
        "F3_project_model_process_wrong_sequence",
        "F4_project_model_trivial",
    ]
    labels = [fixture.expected_failure_mode_label for fixture in fixtures]
    assert labels == ["F1", "F2", "F3", "F3", "F4"]

    f3_fixtures = [fixture for fixture in fixtures if fixture.expected_failure_mode_label == "F3"]
    assert len(f3_fixtures) >= 2
    assert any(
        component["kind"] == "source"
        for fixture in f3_fixtures
        for component in fixture.project_model["components"]
    )
    assert any(
        component["kind"] in {"architecture", "process", "strategy"}
        for fixture in f3_fixtures
        for component in fixture.project_model["components"]
    )

    for fixture in fixtures:
        assert fixture.project_model["schemaVersion"] == PROJECT_MODEL_SCHEMA_VERSION
        assert fixture.expected_signal["schemaVersion"] == ADVISORY_SIGNAL_SCHEMA_VERSION
        assert fixture.observed_signal["schemaVersion"] == ADVISORY_SIGNAL_SCHEMA_VERSION
        assert fixture.proposal.strip()
        assert fixture.public_rationale.strip()
        assert fixture.label_explanation.strip()
        assert fixture.expected_signal["fLabelHint"]["label"] == fixture.expected_failure_mode_label
        assert fixture.observed_signal["projectModelId"] == fixture.project_model["id"]
        assert set(REQUIRED_ADVISORY_FIELDS).issubset(
            set(fixture.project_model["advisorySignalHandoff"]["expectedFields"])
        )


def test_project_model_fixture_runner_reports_per_signal_matches_without_single_score():
    from arena.project_model_fixtures import run_project_model_fixture_checks

    report = run_project_model_fixture_checks(Path("fixtures/project_model_v0"))

    assert report["summary"] == {
        "n_fixtures": 5,
        "f_label_matches": "5/5",
        "signal_matches": "5/5",
        "project_model_quality_passes": "5/5",
        "overall_pass": True,
    }
    assert "overall_score" not in report["summary"]
    assert {row["expected_failure_mode_label"] for row in report["fixtures"]} == {
        "F1",
        "F2",
        "F3",
        "F4",
    }
    for row in report["fixtures"]:
        assert row["signal_mismatches"] == []
        assert row["project_model_quality_issues"] == []
        assert row["feedback_required"] == []


def test_project_model_signal_comparison_reports_field_level_mismatches(tmp_path):
    from arena.project_model_fixtures import load_project_model_fixture, run_project_model_fixture_checks

    fixture = load_project_model_fixture(
        Path("fixtures/project_model_v0/F3_project_model_code_too_narrow/manifest.yaml")
    )
    observed_dir = tmp_path / "observed"
    observed_dir.mkdir()
    observed = json.loads(json.dumps(fixture.observed_signal))
    observed["fLabelHint"]["label"] = "F1"
    observed["fLabelHint"]["explanation"] = "wrong explanation"
    observed["componentAlignment"][0]["status"] = "aligned"
    observed["componentAlignment"][0]["explanation"] = "wrong component explanation"
    observed["componentAlignment"][0]["evidenceRefs"] = ["wrong.md"]
    observed["evidenceGroundingGaps"][0]["missingEvidence"] = "wrong missing-evidence note"
    (observed_dir / f"{fixture.id}.json").write_text(json.dumps(observed, indent=2))

    report = run_project_model_fixture_checks(
        Path("fixtures/project_model_v0/F3_project_model_code_too_narrow"),
        observed_dir=observed_dir,
    )

    row = report["fixtures"][0]
    assert report["summary"]["overall_pass"] is False
    assert row["f_label_match"] is False
    assert {mismatch["field"] for mismatch in row["signal_mismatches"]} >= {
        "fLabelHint.label",
        "fLabelHint.explanation",
        "componentAlignment.tokenizer_behavior.status",
        "componentAlignment.tokenizer_behavior.explanation",
        "componentAlignment.tokenizer_behavior.evidenceRefs",
        "evidenceGroundingGaps.held_out_tokenizer_probe.missingEvidence",
    }


def test_project_model_quality_gate_reports_missing_contract_fields_as_spec_feedback():
    from arena.project_model_fixtures import evaluate_project_model_quality

    bad_model = {
        "schemaVersion": "project-model/v999",
        "id": "bad_model",
        "advisorySignalHandoff": {
            "consumer": "elenchus-core",
            "expectedFields": [
                "componentAlignment",
                "invariantViolations",
                "dependencyViolations",
                "unsupportedAssumptions",
                "evidenceGroundingGaps",
                "nearNeighborResistance",
                "fLabelHint",
            ],
            "optionalFLabelHint": True,
        },
    }

    issues = evaluate_project_model_quality(bad_model)

    issue_codes = {issue["code"] for issue in issues}
    assert {
        "unsupported_schema_version",
        "missing_required_field",
        "missing_components",
        "missing_observable_checks",
    }.issubset(issue_codes)
    assert all(issue["feedback"] == "build-arena Project Model v0" for issue in issues)


def test_project_model_quality_gate_reports_bad_model_as_spec_feedback():
    from arena.project_model_fixtures import evaluate_project_model_quality

    bad_model = {
        "schemaVersion": "project-model/v0",
        "id": "bad_model",
        "components": [
            {
                "id": "misc",
                "name": "Misc stuff",
                "kind": "unknown",
                "riskLevel": "high",
                "responsibilities": ["handle everything"],
                "ownedSurfaces": ["all work"],
                "observableCheckIds": [],
            },
            {
                "id": "process",
                "name": "Process",
                "kind": "process",
                "riskLevel": "medium",
                "responsibilities": ["sequence the work"],
                "ownedSurfaces": ["issue body"],
                "observableCheckIds": ["missing_check"],
            },
        ],
        "dependencies": [],
        "observableChecks": [],
        "heldOutProbes": [],
        "unclassifiedProjectSurface": [
            {
                "id": "unknown_surface",
                "description": "The deployment plan is not owned.",
                "reasonUnclassified": "No component owns it yet.",
                "candidateOwners": ["process"],
            }
        ],
        "advisorySignalHandoff": {"expectedFields": []},
    }

    issues = evaluate_project_model_quality(bad_model)

    assert {issue["code"] for issue in issues} >= {
        "component_without_observable_check",
        "vague_decomposition",
        "missing_dependencies",
        "missing_held_out_probe",
        "missing_observable_check_reference",
        "unclassified_project_surface",
        "missing_advisory_handoff_field",
    }
    assert all(issue["feedback"] == "build-arena Project Model v0" for issue in issues)


def test_project_model_quality_gate_accepts_acyclic_shared_dependency_target():
    from arena.project_model_fixtures import evaluate_project_model_quality

    model = {
        "schemaVersion": "project-model/v0",
        "id": "acyclic_shared_target",
        "goal": {"summary": "Check dependency traversal"},
        "components": [
            {
                "id": "a",
                "name": "A",
                "kind": "process",
                "riskLevel": "low",
                "responsibilities": ["own A"],
                "ownedSurfaces": ["A"],
                "observableCheckIds": ["check_a"],
            },
            {
                "id": "b",
                "name": "B",
                "kind": "process",
                "riskLevel": "low",
                "responsibilities": ["own B"],
                "ownedSurfaces": ["B"],
                "observableCheckIds": ["check_b"],
            },
            {
                "id": "c",
                "name": "C",
                "kind": "process",
                "riskLevel": "low",
                "responsibilities": ["own C"],
                "ownedSurfaces": ["C"],
                "observableCheckIds": ["check_c"],
            },
        ],
        "dependencies": [
            {"id": "a_before_b", "fromComponent": "a", "toComponent": "b", "kind": "precedes", "observableCheckIds": ["check_a"]},
            {"id": "a_before_c", "fromComponent": "a", "toComponent": "c", "kind": "precedes", "observableCheckIds": ["check_a"]},
            {"id": "c_before_b", "fromComponent": "c", "toComponent": "b", "kind": "precedes", "observableCheckIds": ["check_c"]},
        ],
        "observableChecks": [
            {"id": "check_a", "componentId": "a", "description": "A check", "method": "inspect"},
            {"id": "check_b", "componentId": "b", "description": "B check", "method": "inspect"},
            {"id": "check_c", "componentId": "c", "description": "C check", "method": "inspect"},
        ],
        "heldOutProbes": [],
        "unclassifiedProjectSurface": [],
        "advisorySignalHandoff": {
            "expectedFields": [
                "componentAlignment",
                "invariantViolations",
                "dependencyViolations",
                "unsupportedAssumptions",
                "evidenceGroundingGaps",
                "nearNeighborResistance",
                "fLabelHint",
            ]
        },
    }

    issue_codes = {issue["code"] for issue in evaluate_project_model_quality(model)}

    assert "contradictory_dependencies" not in issue_codes


def test_existing_patch_fixture_loader_ignores_nested_project_model_fixture_manifests():
    from arena.fixtures import load_all_fixtures

    fixtures = load_all_fixtures(Path("fixtures"))

    assert [fixture.id for fixture in fixtures] == [
        "F1_loadbearing_good",
        "F2_fabricated_good",
        "F3_bad_passes_tests",
        "F4_trivial",
    ]


PROJECT_FIXTURE_ROOT = Path("fixtures/project_model_v0/F1_project_model_aligned")


def _copy_project_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "fixture"
    shutil.copytree(PROJECT_FIXTURE_ROOT, root)
    return root


def _load_manifest(root: Path) -> dict[str, object]:
    return json.loads((root / "manifest.yaml").read_text())


def _write_manifest(root: Path, manifest: dict[str, object]) -> None:
    (root / "manifest.yaml").write_text(json.dumps(manifest, indent=2) + "\n")


@pytest.mark.parametrize(
    ("case", "mutate"),
    [
        (
            "json_non_object",
            lambda root: (root / "project_model.json").write_text("[]\n"),
        ),
        (
            "missing_manifest_key",
            lambda root: (_write_manifest(root, {k: v for k, v in _load_manifest(root).items() if k != "expected_failure_mode_label"})),
        ),
        (
            "invalid_path_value",
            lambda root: (_write_manifest(root, {**_load_manifest(root), "project_model_path": ""})),
        ),
        (
            "missing_path_file",
            lambda root: (_write_manifest(root, {**_load_manifest(root), "project_model_path": "missing.json"})),
        ),
        (
            "absolute_path",
            lambda root: (_write_manifest(root, {**_load_manifest(root), "project_model_path": "/tmp/project_model.json"})),
        ),
        (
            "traversal_path",
            lambda root: (_write_manifest(root, {**_load_manifest(root), "project_model_path": "../project_model.json"})),
        ),
        (
            "signal_missing_field",
            lambda root: _mutate_json(root / "expected_advisory_signal.json", lambda data: data.pop("candidateId")),
        ),
        (
            "signal_bad_schema",
            lambda root: _mutate_json(root / "expected_advisory_signal.json", lambda data: data.__setitem__("schemaVersion", "bad")),
        ),
        (
            "signal_hint_not_object",
            lambda root: _mutate_json(root / "expected_advisory_signal.json", lambda data: data.__setitem__("fLabelHint", "F1")),
        ),
        (
            "signal_bad_label",
            lambda root: _mutate_json(root / "expected_advisory_signal.json", lambda data: data["fLabelHint"].__setitem__("label", "FX")),
        ),
        (
            "signal_bad_confidence",
            lambda root: _mutate_json(root / "expected_advisory_signal.json", lambda data: data["fLabelHint"].__setitem__("confidence", "certain")),
        ),
        (
            "signal_field_not_list",
            lambda root: _mutate_json(root / "expected_advisory_signal.json", lambda data: data.__setitem__("componentAlignment", {})),
        ),
        (
            "invalid_fixture_id",
            lambda root: _write_manifest(root, {**_load_manifest(root), "id": "bad id"}),
        ),
        (
            "bad_expected_label",
            lambda root: _write_manifest(root, {**_load_manifest(root), "expected_failure_mode_label": "FX"}),
        ),
        (
            "bad_project_schema",
            lambda root: _mutate_json(root / "project_model.json", lambda data: data.__setitem__("schemaVersion", "project-model/v999")),
        ),
        (
            "empty_proposal",
            lambda root: (root / "proposal.md").write_text("\n"),
        ),
        (
            "empty_rationale",
            lambda root: (root / "public_rationale.md").write_text("\n"),
        ),
        (
            "empty_label_explanation",
            lambda root: _write_manifest(root, {**_load_manifest(root), "label_explanation": ""}),
        ),
        (
            "label_mismatch",
            lambda root: _mutate_json(root / "expected_advisory_signal.json", lambda data: data["fLabelHint"].__setitem__("label", "F2")),
        ),
    ],
)
def test_project_model_loader_rejects_bad_fixture_shapes(tmp_path, case, mutate):
    from arena.project_model_fixtures import load_project_model_fixture

    root = _copy_project_fixture(tmp_path)
    mutate(root)

    with pytest.raises((FileNotFoundError, ValueError)):
        load_project_model_fixture(root / "manifest.yaml")


def _mutate_json(path: Path, mutate) -> None:
    data = json.loads(path.read_text())
    mutate(data)
    path.write_text(json.dumps(data, indent=2) + "\n")


def test_project_model_loader_rejects_missing_or_non_mapping_manifests(tmp_path):
    from arena.project_model_fixtures import load_all_project_model_fixtures, load_project_model_fixture

    with pytest.raises(FileNotFoundError, match="manifest not found"):
        load_project_model_fixture(tmp_path / "missing.yaml")

    non_mapping = tmp_path / "manifest.yaml"
    non_mapping.write_text("[]\n")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_project_model_fixture(non_mapping)

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="no project-model fixture manifests"):
        load_all_project_model_fixtures(empty_dir)


def test_project_model_quality_gate_reports_reference_and_dependency_problems():
    from arena.project_model_fixtures import evaluate_project_model_quality

    model = json.loads(Path("fixtures/project_model_v0/F3_project_model_process_wrong_sequence/project_model.json").read_text())
    model["components"][0]["observableCheckIds"].append("issue_bodies_reference_target")
    model["observableChecks"][0]["componentId"] = "missing_component"
    model["dependencies"] = [
        {
            "id": "bad_dep",
            "fromComponent": "missing_src",
            "toComponent": "missing_dst",
            "kind": "precedes",
            "description": "Bad dependency",
            "observableCheckIds": ["missing_check"],
        },
        {
            "id": "a_before_b",
            "fromComponent": "contract_authority",
            "toComponent": "child_ticket_alignment",
            "kind": "precedes",
            "description": "A before B",
            "observableCheckIds": [],
        },
        {
            "id": "b_before_a",
            "fromComponent": "child_ticket_alignment",
            "toComponent": "contract_authority",
            "kind": "precedes",
            "description": "B before A",
            "observableCheckIds": [],
        },
    ]

    issues = evaluate_project_model_quality(model)

    assert {issue["code"] for issue in issues} >= {
        "observable_check_component_mismatch",
        "unknown_observable_check_component",
        "unknown_dependency_component",
        "missing_observable_check_reference",
        "contradictory_dependencies",
    }


def test_project_model_signal_comparison_reports_id_and_scalar_edges():
    from arena.project_model_fixtures import compare_advisory_signals, load_project_model_fixture

    fixture = load_project_model_fixture(Path("fixtures/project_model_v0/F1_project_model_aligned/manifest.yaml"))
    expected = json.loads(json.dumps(fixture.expected_signal))
    observed = json.loads(json.dumps(fixture.observed_signal))
    expected["fLabelHint"]["extra"] = {"nested": ["expected"]}
    observed["schemaVersion"] = "bad-signal-version"
    observed["componentAlignment"] = []
    observed["invariantViolations"] = "not-a-list"
    observed["fLabelHint"]["extra"] = {"nested": ["observed"]}

    mismatches = compare_advisory_signals(expected, observed)

    assert {mismatch["field"] for mismatch in mismatches} >= {
        "schemaVersion",
        "componentAlignment.componentIds",
        "fLabelHint.extra",
    }


def test_project_model_runner_reports_missing_observed_file_and_feedback(tmp_path, capsys):
    from arena.project_model_fixtures import main, run_project_model_fixture_checks

    root = _copy_project_fixture(tmp_path)
    missing_observed = tmp_path / "missing_observed"
    missing_observed.mkdir()
    with pytest.raises(FileNotFoundError, match="observed signal not found"):
        run_project_model_fixture_checks(root, observed_dir=missing_observed)

    invalid_observed = tmp_path / "invalid_observed"
    invalid_observed.mkdir()
    invalid_signal = json.loads((root / "observed_advisory_signal.json").read_text())
    invalid_signal.pop("candidateId")
    (invalid_observed / "F1_project_model_aligned.json").write_text(json.dumps(invalid_signal, indent=2) + "\n")
    with pytest.raises(ValueError, match="observed_signal missing fields"):
        run_project_model_fixture_checks(root, observed_dir=invalid_observed)

    _mutate_json(root / "project_model.json", lambda data: data.pop("components"))
    observed_dir = tmp_path / "observed"
    observed_dir.mkdir()
    observed = json.loads((root / "observed_advisory_signal.json").read_text())
    observed["fLabelHint"]["label"] = "F2"
    (observed_dir / "F1_project_model_aligned.json").write_text(json.dumps(observed, indent=2) + "\n")

    rc = main(["--fixtures-dir", str(root), "--observed-dir", str(observed_dir)])

    output = capsys.readouterr().out
    assert rc == 1
    assert "signal mismatch fLabelHint.label" in output
    assert "model issue missing_required_field" in output


def test_project_model_cli_json_and_module_entrypoint(monkeypatch, capsys):
    from arena.project_model_fixtures import main

    assert main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["overall_pass"] is True

    monkeypatch.setattr(sys, "argv", ["project_model_fixtures", "--json"])
    with pytest.warns(RuntimeWarning, match="found in sys.modules"):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_module("arena.project_model_fixtures", run_name="__main__")
    assert excinfo.value.code == 0
