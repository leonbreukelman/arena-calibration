"""Project Model v0 fixture loader and hermetic advisory-signal checker.

This module is intentionally a calibration adapter, not the owner of the
Project Model v0 contract. The contract source of truth is the parent
build-arena issue/docs; this code only checks that local fixtures carry the
versioned shape and that recorded Elenchus advisory signals match expected
fixture labels/signals with field-level evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_MODEL_CONTRACT_SOURCE = "https://github.com/leonbreukelman/build-arena/issues/2"
PROJECT_MODEL_SCHEMA_SOURCE = (
    "https://github.com/leonbreukelman/build-arena/blob/"
    "issue-2-project-model-v0/docs/schemas/project-model-v0.schema.json"
)
PROJECT_MODEL_SCHEMA_VERSION = "project-model/v0"
ADVISORY_SIGNAL_SCHEMA_VERSION = "project-model-advisory-signal/v0"
REQUIRED_PROJECT_MODEL_FIELDS = (
    "schemaVersion",
    "id",
    "source",
    "goal",
    "nonGoals",
    "components",
    "dependencies",
    "invariants",
    "observableChecks",
    "evidenceRequirements",
    "assumptions",
    "risks",
    "nearNeighborAlternatives",
    "heldOutProbes",
    "verificationGaps",
    "unclassifiedProjectSurface",
    "advisorySignalHandoff",
)
REQUIRED_ADVISORY_FIELDS = (
    "componentAlignment",
    "invariantViolations",
    "dependencyViolations",
    "unsupportedAssumptions",
    "evidenceGroundingGaps",
    "nearNeighborResistance",
    "fLabelHint",
)
F_LABELS = frozenset({"F1", "F2", "F3", "F4"})
CONFIDENCE_LEVELS = frozenset({"low", "medium", "high"})
_ID_PATTERN = re.compile(r"^F[1-4]_[a-z0-9_]+$")
_DIRECTIONAL_DEPENDENCY_KINDS = frozenset({"requires", "precedes", "blocks"})
_VAGUE_MARKERS = frozenset({"misc", "general", "stuff", "various", "other", "unknown"})


@dataclass(frozen=True)
class ProjectModelFixture:
    id: str
    expected_failure_mode_label: str
    expected_deep_verification: bool
    project_model: dict[str, Any]
    proposal: str
    public_rationale: str
    expected_signal: dict[str, Any]
    observed_signal: dict[str, Any]
    label_explanation: str
    root: Path


# ---------------------------------------------------------------------------
# Loading / validation
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict[str, Any]:
    with path.open() as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"expected JSON object at {path}")
    return raw


def _required(raw: dict[str, Any], key: str, fixture_id: str) -> Any:
    if key not in raw:
        raise ValueError(f"project-model fixture {fixture_id} missing {key}")
    return raw[key]


def _path_from_manifest(root: Path, raw: dict[str, Any], key: str, fixture_id: str) -> Path:
    rel = _required(raw, key, fixture_id)
    if not isinstance(rel, str) or not rel.strip():
        raise ValueError(f"project-model fixture {fixture_id} has invalid {key}")
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"project-model fixture {fixture_id} has unsafe {key}: {rel}")
    path = root / candidate
    if not path.is_file():
        raise FileNotFoundError(f"project-model fixture {fixture_id} missing {key}: {rel}")
    return path


def _validate_signal_shape(signal: dict[str, Any], fixture_id: str, *, field_name: str) -> None:
    required = (
        "schemaVersion",
        "projectModelId",
        "candidateId",
        *REQUIRED_ADVISORY_FIELDS,
    )
    missing = [key for key in required if key not in signal]
    if missing:
        raise ValueError(f"{fixture_id} {field_name} missing fields: {', '.join(missing)}")
    if signal["schemaVersion"] != ADVISORY_SIGNAL_SCHEMA_VERSION:
        raise ValueError(
            f"{fixture_id} {field_name} schemaVersion must be {ADVISORY_SIGNAL_SCHEMA_VERSION}"
        )
    hint = signal["fLabelHint"]
    if not isinstance(hint, dict):
        raise ValueError(f"{fixture_id} {field_name} fLabelHint must be an object")
    label = hint.get("label")
    if label not in F_LABELS:
        raise ValueError(f"{fixture_id} {field_name} has invalid F-label hint {label!r}")
    confidence = hint.get("confidence")
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"{fixture_id} {field_name} has invalid confidence {confidence!r}")
    for key in REQUIRED_ADVISORY_FIELDS[:-1]:
        if not isinstance(signal[key], list):
            raise ValueError(f"{fixture_id} {field_name} {key} must be a list")


def load_project_model_fixture(manifest_path: Path | str) -> ProjectModelFixture:
    """Load one Project Model v0 calibration fixture."""
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"project-model fixture manifest not found: {manifest_path}")
    raw = yaml.safe_load(manifest_path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"project-model fixture manifest must be a mapping: {manifest_path}")

    fixture_id = _required(raw, "id", str(manifest_path))
    if not isinstance(fixture_id, str) or not _ID_PATTERN.match(fixture_id):
        raise ValueError(f"invalid project-model fixture id {fixture_id!r}")
    expected_label = _required(raw, "expected_failure_mode_label", fixture_id)
    if expected_label not in F_LABELS:
        raise ValueError(f"{fixture_id} has invalid expected_failure_mode_label {expected_label!r}")

    root = manifest_path.parent
    project_model = _read_json(_path_from_manifest(root, raw, "project_model_path", fixture_id))
    expected_signal = _read_json(_path_from_manifest(root, raw, "expected_signal_path", fixture_id))
    observed_signal = _read_json(_path_from_manifest(root, raw, "observed_signal_path", fixture_id))
    proposal = _path_from_manifest(root, raw, "proposal_path", fixture_id).read_text().strip()
    public_rationale = _path_from_manifest(root, raw, "public_rationale_path", fixture_id).read_text().strip()
    label_explanation = str(_required(raw, "label_explanation", fixture_id)).strip()
    expected_deep_verification = bool(raw.get("expected_deep_verification", expected_label != "F4"))

    if project_model.get("schemaVersion") != PROJECT_MODEL_SCHEMA_VERSION:
        raise ValueError(f"{fixture_id} project_model must use {PROJECT_MODEL_SCHEMA_VERSION}")
    if not proposal:
        raise ValueError(f"{fixture_id} proposal is empty")
    if not public_rationale:
        raise ValueError(f"{fixture_id} public_rationale is empty")
    if not label_explanation:
        raise ValueError(f"{fixture_id} label_explanation is empty")
    _validate_signal_shape(expected_signal, fixture_id, field_name="expected_signal")
    _validate_signal_shape(observed_signal, fixture_id, field_name="observed_signal")
    if expected_signal["fLabelHint"]["label"] != expected_label:
        raise ValueError(f"{fixture_id} expected_signal label does not match manifest label")

    return ProjectModelFixture(
        id=fixture_id,
        expected_failure_mode_label=expected_label,
        expected_deep_verification=expected_deep_verification,
        project_model=project_model,
        proposal=proposal,
        public_rationale=public_rationale,
        expected_signal=expected_signal,
        observed_signal=observed_signal,
        label_explanation=label_explanation,
        root=root,
    )


def _manifest_paths(fixtures_dir: Path) -> list[Path]:
    if (fixtures_dir / "manifest.yaml").is_file():
        return [fixtures_dir / "manifest.yaml"]
    return sorted(fixtures_dir.glob("*/manifest.yaml"))


def load_all_project_model_fixtures(fixtures_dir: Path | str) -> list[ProjectModelFixture]:
    """Load a directory of Project Model v0 fixtures, sorted by fixture id."""
    root = Path(fixtures_dir)
    manifests = _manifest_paths(root)
    if not manifests:
        raise FileNotFoundError(f"no project-model fixture manifests found under {root}")
    fixtures = [load_project_model_fixture(path) for path in manifests]
    return sorted(fixtures, key=lambda fixture: fixture.id)


# ---------------------------------------------------------------------------
# Project Model v0 compatibility / quality feedback
# ---------------------------------------------------------------------------

def _quality_issue(code: str, message: str, location: str) -> dict[str, str]:
    return {
        "code": code,
        "message": message,
        "location": location,
        "feedback": "build-arena Project Model v0",
    }


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _has_vague_marker(text: str) -> bool:
    words = {part.strip("-_ .,:;()[]{}").lower() for part in text.split()}
    return bool(words & _VAGUE_MARKERS)


def _has_directional_cycle(edges: list[tuple[str, str]]) -> bool:
    graph: dict[str, list[str]] = {}
    for src, dst in edges:
        graph.setdefault(src, []).append(dst)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for neighbor in graph.get(node, []):
            if visit(neighbor):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def evaluate_project_model_quality(model: dict[str, Any]) -> list[dict[str, str]]:
    """Return Project Model v0 quality/compatibility issues.

    These checks are the local calibration harness's compatibility guard for
    the parent Project Model v0 contract. They intentionally report bad or
    incomplete Project Models as build-arena feedback instead of being mistaken
    for an Elenchus advisory-signal failure. They do not make arena-calibration
    the owner of Project Model semantics; the compatibility target remains
    build-arena issue #2 and its schema/docs.
    """
    issues: list[dict[str, str]] = []
    if model.get("schemaVersion") != PROJECT_MODEL_SCHEMA_VERSION:
        issues.append(_quality_issue(
            "unsupported_schema_version",
            f"schemaVersion must be {PROJECT_MODEL_SCHEMA_VERSION}",
            "schemaVersion",
        ))
    for field in REQUIRED_PROJECT_MODEL_FIELDS:
        if field not in model:
            issues.append(_quality_issue(
                "missing_required_field",
                f"Project Model v0 requires top-level field {field}",
                field,
            ))

    components = [item for item in _as_list(model.get("components")) if isinstance(item, dict)]
    checks = [item for item in _as_list(model.get("observableChecks")) if isinstance(item, dict)]
    dependencies = [item for item in _as_list(model.get("dependencies")) if isinstance(item, dict)]
    probes = [item for item in _as_list(model.get("heldOutProbes")) if isinstance(item, dict)]
    unclassified = [
        item for item in _as_list(model.get("unclassifiedProjectSurface")) if isinstance(item, dict)
    ]

    if not components:
        issues.append(_quality_issue(
            "missing_components",
            "Project Model v0 requires at least one component",
            "components",
        ))
    if not checks:
        issues.append(_quality_issue(
            "missing_observable_checks",
            "Project Model v0 requires at least one observable check",
            "observableChecks",
        ))

    component_ids = {str(component.get("id")) for component in components if component.get("id")}
    check_by_id = {str(check.get("id")): check for check in checks if check.get("id")}
    probes_by_component: dict[str, int] = {}
    for probe in probes:
        component_id = str(probe.get("componentId", ""))
        probes_by_component[component_id] = probes_by_component.get(component_id, 0) + 1

    for component in components:
        component_id = str(component.get("id", "<missing>"))
        check_ids = [str(check_id) for check_id in _as_list(component.get("observableCheckIds"))]
        if not check_ids:
            issues.append(_quality_issue(
                "component_without_observable_check",
                "component has no observableCheckIds",
                f"components.{component_id}.observableCheckIds",
            ))
        for check_id in check_ids:
            check = check_by_id.get(check_id)
            if check is None:
                issues.append(_quality_issue(
                    "missing_observable_check_reference",
                    f"component references unknown observable check {check_id}",
                    f"components.{component_id}.observableCheckIds",
                ))
            elif check.get("componentId") != component_id:
                issues.append(_quality_issue(
                    "observable_check_component_mismatch",
                    f"observable check {check_id} belongs to {check.get('componentId')}",
                    f"components.{component_id}.observableCheckIds",
                ))
        name = str(component.get("name", ""))
        responsibilities = " ".join(str(item) for item in _as_list(component.get("responsibilities")))
        if component.get("kind") == "unknown" or _has_vague_marker(name) or _has_vague_marker(responsibilities):
            issues.append(_quality_issue(
                "vague_decomposition",
                "component is vague rather than a responsibility boundary",
                f"components.{component_id}",
            ))
        if component.get("riskLevel") == "high" and probes_by_component.get(component_id, 0) == 0:
            issues.append(_quality_issue(
                "missing_held_out_probe",
                "high-risk component has no held-out probe or counterexample",
                f"components.{component_id}",
            ))

    for check in checks:
        component_id = str(check.get("componentId", ""))
        if component_id and component_id not in component_ids:
            issues.append(_quality_issue(
                "unknown_observable_check_component",
                f"observable check points to unknown component {component_id}",
                f"observableChecks.{check.get('id', '<missing>')}.componentId",
            ))

    if len(components) > 1 and not dependencies:
        issues.append(_quality_issue(
            "missing_dependencies",
            "multiple components exist but no dependency or sequencing constraints are declared",
            "dependencies",
        ))

    directional_edges: list[tuple[str, str]] = []
    directional_edge_set: set[tuple[str, str]] = set()
    for dependency in dependencies:
        dep_id = str(dependency.get("id", "<missing>"))
        src = str(dependency.get("fromComponent", ""))
        dst = str(dependency.get("toComponent", ""))
        if src and src not in component_ids:
            issues.append(_quality_issue(
                "unknown_dependency_component",
                f"dependency source {src} is not a component",
                f"dependencies.{dep_id}.fromComponent",
            ))
        if dst and dst not in component_ids:
            issues.append(_quality_issue(
                "unknown_dependency_component",
                f"dependency target {dst} is not a component",
                f"dependencies.{dep_id}.toComponent",
            ))
        for check_id in _as_list(dependency.get("observableCheckIds")):
            if str(check_id) not in check_by_id:
                issues.append(_quality_issue(
                    "missing_observable_check_reference",
                    f"dependency references unknown observable check {check_id}",
                    f"dependencies.{dep_id}.observableCheckIds",
                ))
        if dependency.get("kind") in _DIRECTIONAL_DEPENDENCY_KINDS:
            edge = (src, dst)
            reverse = (dst, src)
            if reverse in directional_edge_set:
                issues.append(_quality_issue(
                    "contradictory_dependencies",
                    "directional dependency directly reverses another dependency",
                    f"dependencies.{dep_id}",
                ))
            directional_edges.append(edge)
            directional_edge_set.add(edge)
    if directional_edges and _has_directional_cycle(directional_edges):
        issues.append(_quality_issue(
            "contradictory_dependencies",
            "directional dependency cycle detected",
            "dependencies",
        ))

    for surface in unclassified:
        issues.append(_quality_issue(
            "unclassified_project_surface",
            str(surface.get("description", "significant surface is unclassified")),
            f"unclassifiedProjectSurface.{surface.get('id', '<missing>')}",
        ))

    handoff_fields = set(_as_list(model.get("advisorySignalHandoff", {}).get("expectedFields")))
    for field in REQUIRED_ADVISORY_FIELDS:
        if field not in handoff_fields:
            issues.append(_quality_issue(
                "missing_advisory_handoff_field",
                f"advisorySignalHandoff omits {field}",
                "advisorySignalHandoff.expectedFields",
            ))

    return issues


# ---------------------------------------------------------------------------
# Advisory-signal comparison
# ---------------------------------------------------------------------------

def _mismatch(field: str, expected: Any, observed: Any) -> dict[str, Any]:
    return {"field": field, "expected": expected, "observed": observed}


def _compare_scalar(
    mismatches: list[dict[str, Any]],
    field: str,
    expected: dict[str, Any],
    observed: dict[str, Any],
) -> None:
    if expected.get(field) != observed.get(field):
        mismatches.append(_mismatch(field, expected.get(field), observed.get(field)))


def _items_by_key(items: Any, key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {str(item[key]): item for item in items if isinstance(item, dict) and key in item}


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _compare_items_by_id(
    mismatches: list[dict[str, Any]],
    field: str,
    key: str,
    expected_items: Any,
    observed_items: Any,
) -> None:
    expected_by_id = _items_by_key(expected_items, key)
    observed_by_id = _items_by_key(observed_items, key)
    expected_ids = set(expected_by_id)
    observed_ids = set(observed_by_id)
    if expected_ids != observed_ids:
        mismatches.append(_mismatch(f"{field}.{key}s", sorted(expected_ids), sorted(observed_ids)))
    for item_id in sorted(expected_ids & observed_ids):
        expected_item = expected_by_id[item_id]
        observed_item = observed_by_id[item_id]
        for item_field in sorted((set(expected_item) | set(observed_item)) - {key}):
            expected_value = _canonical(expected_item.get(item_field))
            observed_value = _canonical(observed_item.get(item_field))
            if expected_value != observed_value:
                mismatches.append(_mismatch(
                    f"{field}.{item_id}.{item_field}",
                    expected_value,
                    observed_value,
                ))


def compare_advisory_signals(expected: dict[str, Any], observed: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare advisory signals by stable ids/statuses, not prose similarity."""
    mismatches: list[dict[str, Any]] = []
    for field in ("schemaVersion", "projectModelId", "candidateId"):
        _compare_scalar(mismatches, field, expected, observed)
    _compare_items_by_id(
        mismatches,
        "componentAlignment",
        "componentId",
        expected.get("componentAlignment"),
        observed.get("componentAlignment"),
    )
    _compare_items_by_id(
        mismatches,
        "invariantViolations",
        "invariantId",
        expected.get("invariantViolations"),
        observed.get("invariantViolations"),
    )
    _compare_items_by_id(
        mismatches,
        "dependencyViolations",
        "dependencyId",
        expected.get("dependencyViolations"),
        observed.get("dependencyViolations"),
    )
    _compare_items_by_id(
        mismatches,
        "unsupportedAssumptions",
        "assumptionId",
        expected.get("unsupportedAssumptions"),
        observed.get("unsupportedAssumptions"),
    )
    _compare_items_by_id(
        mismatches,
        "evidenceGroundingGaps",
        "checkId",
        expected.get("evidenceGroundingGaps"),
        observed.get("evidenceGroundingGaps"),
    )
    _compare_items_by_id(
        mismatches,
        "nearNeighborResistance",
        "alternativeId",
        expected.get("nearNeighborResistance"),
        observed.get("nearNeighborResistance"),
    )
    expected_hint = expected.get("fLabelHint", {})
    observed_hint = observed.get("fLabelHint", {})
    for field in sorted(set(expected_hint) | set(observed_hint)):
        expected_value = _canonical(expected_hint.get(field))
        observed_value = _canonical(observed_hint.get(field))
        if expected_value != observed_value:
            mismatches.append(_mismatch(
                f"fLabelHint.{field}",
                expected_value,
                observed_value,
            ))
    return mismatches


# ---------------------------------------------------------------------------
# Runner / report
# ---------------------------------------------------------------------------

def _observed_signal_for_fixture(fixture: ProjectModelFixture, observed_dir: Path | None) -> dict[str, Any]:
    if observed_dir is None:
        return fixture.observed_signal
    observed_path = observed_dir / f"{fixture.id}.json"
    if not observed_path.is_file():
        raise FileNotFoundError(f"observed signal not found for {fixture.id}: {observed_path}")
    signal = _read_json(observed_path)
    _validate_signal_shape(signal, fixture.id, field_name="observed_signal")
    return signal


def _row_for_fixture(fixture: ProjectModelFixture, observed_signal: dict[str, Any]) -> dict[str, Any]:
    project_model_quality_issues = evaluate_project_model_quality(fixture.project_model)
    signal_mismatches = compare_advisory_signals(fixture.expected_signal, observed_signal)
    observed_label = observed_signal.get("fLabelHint", {}).get("label")
    f_label_match = observed_label == fixture.expected_failure_mode_label
    feedback_required: list[str] = []
    if project_model_quality_issues:
        feedback_required.append("build-arena Project Model v0")
    if signal_mismatches or not f_label_match:
        feedback_required.append("elenchus-core advisory signal shape")
    return {
        "fixture_id": fixture.id,
        "project_model_id": fixture.project_model.get("id"),
        "candidate_id": fixture.expected_signal.get("candidateId"),
        "expected_failure_mode_label": fixture.expected_failure_mode_label,
        "observed_f_label_hint": observed_label,
        "f_label_match": f_label_match,
        "expected_deep_verification": fixture.expected_deep_verification,
        "project_model_quality_pass": not project_model_quality_issues,
        "project_model_quality_issues": project_model_quality_issues,
        "signal_match": not signal_mismatches,
        "signal_mismatches": signal_mismatches,
        "feedback_required": feedback_required,
        "label_explanation": fixture.label_explanation,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    f_label_matches = sum(1 for row in rows if row["f_label_match"])
    signal_matches = sum(1 for row in rows if row["signal_match"])
    quality_passes = sum(1 for row in rows if row["project_model_quality_pass"])
    return {
        "n_fixtures": n,
        "f_label_matches": f"{f_label_matches}/{n}",
        "signal_matches": f"{signal_matches}/{n}",
        "project_model_quality_passes": f"{quality_passes}/{n}",
        "overall_pass": f_label_matches == n and signal_matches == n and quality_passes == n,
    }


def run_project_model_fixture_checks(
    fixtures_dir: Path | str,
    *,
    observed_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Compare observed advisory signals to expected fixture signals."""
    observed_root = Path(observed_dir) if observed_dir is not None else None
    fixtures = load_all_project_model_fixtures(fixtures_dir)
    rows = [
        _row_for_fixture(fixture, _observed_signal_for_fixture(fixture, observed_root))
        for fixture in fixtures
    ]
    return {
        "metadata": {
            "fixtures_dir": str(Path(fixtures_dir).resolve()),
            "observed_dir": str(observed_root.resolve()) if observed_root is not None else "fixture-local",
            "project_model_schema_version": PROJECT_MODEL_SCHEMA_VERSION,
            "advisory_signal_schema_version": ADVISORY_SIGNAL_SCHEMA_VERSION,
        },
        "summary": _summary(rows),
        "fixtures": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Project Model v0 advisory-signal fixtures.")
    parser.add_argument("--fixtures-dir", type=Path, default=Path("fixtures/project_model_v0"))
    parser.add_argument("--observed-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a compact text report")
    args = parser.parse_args(argv)

    report = run_project_model_fixture_checks(args.fixtures_dir, observed_dir=args.observed_dir)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=False))
    else:
        print("Project Model v0 fixture check")
        for key, value in report["summary"].items():
            print(f"  {key}: {value}")
        for row in report["fixtures"]:
            print(
                f"  {row['fixture_id']}: label={row['observed_f_label_hint']} "
                f"signal_match={row['signal_match']} model_quality={row['project_model_quality_pass']}"
            )
            for mismatch in row["signal_mismatches"]:
                print(f"    signal mismatch {mismatch['field']}: expected={mismatch['expected']} observed={mismatch['observed']}")
            for issue in row["project_model_quality_issues"]:
                print(f"    model issue {issue['code']}: {issue['message']}")
    return 0 if report["summary"]["overall_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
