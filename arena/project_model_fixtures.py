"""Project Model v0 fixture loader and hermetic advisory-signal checker.

This module is intentionally a calibration adapter, not the owner of the
Project Model v0 contract. The contract source of truth is the parent
build-arena issue/docs; this code only checks that local fixtures carry the
versioned shape and that recorded Elenchus advisory signals match expected
fixture labels/signals with field-level evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

PROJECT_MODEL_CONTRACT_SOURCE = "https://github.com/leonbreukelman/build-arena/issues/2"
PROJECT_MODEL_SCHEMA_SOURCE = (
    "https://github.com/leonbreukelman/build-arena/blob/"
    "issue-2-project-model-v0/docs/schemas/project-model-v0.schema.json"
)
PROJECT_MODEL_SCHEMA_VERSION = "project-model/v0"
ADVISORY_SIGNAL_SCHEMA_VERSION = "project-model-advisory-signal/v0"
REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_MODEL_V1_CONTRACT_SOURCE = "https://github.com/leonbreukelman/build-arena/issues/4"
PROJECT_MODEL_V1_SCHEMA_SOURCE = (
    "https://github.com/leonbreukelman/build-arena/blob/"
    "6aab52cc3a92ad65efe645ac6dd5e20338e96999/docs/schemas/project-model-v1.schema.json"
)
PROJECT_MODEL_V1_SCHEMA_PATH = REPO_ROOT / "docs/schemas/project-model-v1.schema.json"
PROJECT_MODEL_V1_SCHEMA_SHA256_PATH = REPO_ROOT / "docs/schemas/project-model-v1.schema.json.sha256"
PROJECT_MODEL_V1_SCHEMA_VERSION = "project-model/v1"
PROJECT_MODEL_V1_SIGNAL_SCHEMA_VERSION = "project-model-v1-calibration-signal/v0"
REQUIRED_V1_FAILURE_CASES = (
    "F1_project_model_v1_aligned",
    "F2_project_model_v1_decorative",
    "F3_project_model_v1_code_too_narrow",
    "F3_project_model_v1_missing_graph_edge",
    "F3_project_model_v1_process_wrong_sequence",
    "F3_project_model_v1_reversed_contract_direction",
    "F3_project_model_v1_weak_held_out_probe",
    "F4_project_model_v1_fabricated_provenance_ref",
    "F4_project_model_v1_protected_ownership_leak",
    "F4_project_model_v1_self_referential_contract",
    "F4_project_model_v1_trivial",
    "F4_project_model_v1_verification_gap_mislabeled_success",
)
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


@dataclass(frozen=True)
class ProjectModelV1Fixture:
    id: str
    expected_failure_mode_label: str
    expected_deep_verification: bool
    project_model: dict[str, Any]
    proposal: str
    public_rationale: str
    expected_signal: dict[str, Any]
    observed_signal: dict[str, Any]
    label_explanation: str
    expected_v1_quality_issue_codes: list[str]
    case_description: str
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
    _validate_signal_payload(signal, fixture_id, field_name=field_name)


def _validate_signal_payload(signal: dict[str, Any], fixture_id: str, *, field_name: str) -> None:
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


def _validate_v1_signal_shape(signal: dict[str, Any], fixture_id: str, *, field_name: str) -> None:
    required = (
        "schemaVersion",
        "projectModelId",
        "candidateId",
        *REQUIRED_ADVISORY_FIELDS,
    )
    missing = [key for key in required if key not in signal]
    if missing:
        raise ValueError(f"{fixture_id} {field_name} missing fields: {', '.join(missing)}")
    if signal["schemaVersion"] != PROJECT_MODEL_V1_SIGNAL_SCHEMA_VERSION:
        raise ValueError(
            f"{fixture_id} {field_name} schemaVersion must be {PROJECT_MODEL_V1_SIGNAL_SCHEMA_VERSION}"
        )
    _validate_signal_payload(signal, fixture_id, field_name=field_name)


@lru_cache(maxsize=1)
def _project_model_v1_schema() -> dict[str, Any]:
    if not PROJECT_MODEL_V1_SCHEMA_PATH.is_file():
        raise FileNotFoundError(f"vendored Project Model v1 schema not found: {PROJECT_MODEL_V1_SCHEMA_PATH}")
    if not PROJECT_MODEL_V1_SCHEMA_SHA256_PATH.is_file():
        raise FileNotFoundError(
            f"Project Model v1 schema hash not found: {PROJECT_MODEL_V1_SCHEMA_SHA256_PATH}"
        )
    expected_hash = PROJECT_MODEL_V1_SCHEMA_SHA256_PATH.read_text().strip().split()[0]
    observed_hash = hashlib.sha256(PROJECT_MODEL_V1_SCHEMA_PATH.read_bytes()).hexdigest()
    if observed_hash != expected_hash:
        raise ValueError(
            "vendored Project Model v1 schema hash mismatch: "
            f"expected {expected_hash}, observed {observed_hash}"
        )
    schema = _read_json(PROJECT_MODEL_V1_SCHEMA_PATH)
    expected_draft = "https://json-schema.org/draft/2020-12/schema"
    if schema.get("$schema") != expected_draft:
        raise ValueError(
            "vendored Project Model v1 schema draft changed: "
            f"expected {expected_draft}, observed {schema.get('$schema')!r}"
        )
    return schema


def _json_path(error_path: Any) -> str:
    parts = [str(part) for part in error_path]
    return ".".join(parts) if parts else "root"


def load_project_model_v1_fixture(manifest_path: Path | str) -> ProjectModelV1Fixture:
    """Load one Project Model v1 calibration fixture."""
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"project-model v1 fixture manifest not found: {manifest_path}")
    raw = yaml.safe_load(manifest_path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"project-model v1 fixture manifest must be a mapping: {manifest_path}")

    fixture_id = _required(raw, "id", str(manifest_path))
    if not isinstance(fixture_id, str) or not _ID_PATTERN.match(fixture_id):
        raise ValueError(f"invalid project-model v1 fixture id {fixture_id!r}")
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
    case_description = str(_required(raw, "case_description", fixture_id)).strip()
    expected_deep_verification = bool(raw.get("expected_deep_verification", expected_label != "F4"))
    expected_codes = raw.get("expected_v1_quality_issue_codes", [])
    if not isinstance(expected_codes, list) or not all(isinstance(code, str) for code in expected_codes):
        raise ValueError(f"{fixture_id} expected_v1_quality_issue_codes must be a string list")

    if project_model.get("schemaVersion") != PROJECT_MODEL_V1_SCHEMA_VERSION:
        raise ValueError(f"{fixture_id} project_model must use {PROJECT_MODEL_V1_SCHEMA_VERSION}")
    if not proposal:
        raise ValueError(f"{fixture_id} proposal is empty")
    if not public_rationale:
        raise ValueError(f"{fixture_id} public_rationale is empty")
    if not label_explanation:
        raise ValueError(f"{fixture_id} label_explanation is empty")
    if not case_description:
        raise ValueError(f"{fixture_id} case_description is empty")
    _validate_v1_signal_shape(expected_signal, fixture_id, field_name="expected_signal")
    _validate_v1_signal_shape(observed_signal, fixture_id, field_name="observed_signal")
    if expected_signal["fLabelHint"]["label"] != expected_label:
        raise ValueError(f"{fixture_id} expected_signal label does not match manifest label")

    return ProjectModelV1Fixture(
        id=fixture_id,
        expected_failure_mode_label=expected_label,
        expected_deep_verification=expected_deep_verification,
        project_model=project_model,
        proposal=proposal,
        public_rationale=public_rationale,
        expected_signal=expected_signal,
        observed_signal=observed_signal,
        label_explanation=label_explanation,
        expected_v1_quality_issue_codes=sorted(set(expected_codes)),
        case_description=case_description,
        root=root,
    )


def load_all_project_model_v1_fixtures(fixtures_dir: Path | str) -> list[ProjectModelV1Fixture]:
    """Load a directory of Project Model v1 fixtures, sorted by fixture id."""
    root = Path(fixtures_dir)
    manifests = _manifest_paths(root)
    if not manifests:
        raise FileNotFoundError(f"no project-model v1 fixture manifests found under {root}")
    fixtures = [load_project_model_v1_fixture(path) for path in manifests]
    return sorted(fixtures, key=lambda fixture: fixture.id)


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
# Project Model v1 compatibility / quality feedback
# ---------------------------------------------------------------------------

_V1_PROTECTED_OWNERSHIP_MARKERS = frozenset({"protected", "generated", "scorer", "verifier", "schema"})
_V1_HIGH_GAP_SEVERITIES = frozenset({"high", "blocker", "critical"})


def _v1_quality_issue(code: str, message: str, location: str) -> dict[str, str]:
    return {
        "code": code,
        "message": message,
        "location": location,
        "feedback": "build-arena Project Model v1",
    }


def _v1_issue_sort_key(issue: dict[str, str]) -> tuple[str, str, str]:
    return (issue["code"], issue["location"], issue["message"])


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in _as_list(value) if isinstance(item, dict)]


def _id_map(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in items if item.get("id")}


def _string_refs(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if isinstance(item, str) and item]


def _append_missing_refs(
    issues: list[dict[str, str]],
    *,
    refs: list[str],
    known_ids: set[str],
    code: str,
    owner_location: str,
    noun: str,
) -> None:
    for ref in sorted(set(refs)):
        if ref not in known_ids:
            issues.append(_v1_quality_issue(code, f"references unknown {noun} {ref}", owner_location))


def _schema_validation_issues(model: dict[str, Any]) -> list[dict[str, str]]:
    schema = _project_model_v1_schema()
    validator = Draft202012Validator(schema)
    issues: list[dict[str, str]] = []
    for error in sorted(validator.iter_errors(model), key=lambda item: (_json_path(item.path), item.message)):
        issues.append(_v1_quality_issue(
            "schema_validation_error",
            error.message,
            _json_path(error.path),
        ))
    return issues


def evaluate_project_model_v1_quality(model: dict[str, Any]) -> list[dict[str, str]]:
    """Return Project Model v1 schema/semantic quality issues.

    Build Arena remains the owner of the Project Model v1 schema. This function
    first validates against the vendored, hash-pinned Build Arena schema and then
    applies deterministic calibration checks for issue #4's required failure
    cases: reference resolution, contract/graph direction, declared held-out
    probe strength, gate/gap consistency, and protected ownership leaks.
    """
    issues: list[dict[str, str]] = []
    if model.get("schemaVersion") != PROJECT_MODEL_V1_SCHEMA_VERSION:
        issues.append(_v1_quality_issue(
            "unsupported_schema_version",
            f"schemaVersion must be {PROJECT_MODEL_V1_SCHEMA_VERSION}",
            "schemaVersion",
        ))

    for field in _project_model_v1_schema().get("required", []):
        if field not in model:
            issues.append(_v1_quality_issue(
                "missing_required_field",
                f"Project Model v1 requires top-level field {field}",
                field,
            ))

    issues.extend(_schema_validation_issues(model))

    graph = model.get("projectGraph") if isinstance(model.get("projectGraph"), dict) else {}
    snapshot = model.get("snapshot") if isinstance(model.get("snapshot"), dict) else {}
    gate_report = model.get("gateReport") if isinstance(model.get("gateReport"), dict) else {}

    nodes = _dict_list(graph.get("nodes"))
    edges = _dict_list(graph.get("edges"))
    node_by_id = _id_map(nodes)
    edge_by_id = _id_map(edges)
    node_ids = set(node_by_id)
    edge_ids = set(edge_by_id)

    graph_provenance_ids: set[str] = set()
    for owner in [*nodes, *edges]:
        for ref in _as_list(owner.get("provenance_refs")):
            if isinstance(ref, dict) and ref.get("id"):
                graph_provenance_ids.add(str(ref["id"]))

    components = _dict_list(snapshot.get("components"))
    contracts = _dict_list(snapshot.get("contracts"))
    checks = _dict_list(snapshot.get("observable_checks"))
    probes = _dict_list(snapshot.get("held_out_probes"))
    gaps = _dict_list(snapshot.get("verification_gaps"))
    near_neighbors = _dict_list(snapshot.get("near_neighbor_alternatives"))
    cross_cutting = _dict_list(snapshot.get("cross_cutting_concerns"))

    component_by_id = _id_map(components)
    contract_by_id = _id_map(contracts)
    check_by_id = _id_map(checks)
    gap_by_id = _id_map(gaps)
    near_neighbor_by_id = _id_map(near_neighbors)
    component_ids = set(component_by_id)
    contract_ids = set(contract_by_id)
    check_ids = set(check_by_id)
    gap_ids = set(gap_by_id)
    near_neighbor_ids = set(near_neighbor_by_id)

    component_owned_nodes: dict[str, set[str]] = {}
    for component in components:
        component_id = str(component.get("id", "<missing>"))
        owned_node_ids = set(_string_refs(component.get("owned_node_ids")))
        component_owned_nodes[component_id] = owned_node_ids
        _append_missing_refs(
            issues,
            refs=sorted(owned_node_ids),
            known_ids=node_ids,
            code="missing_graph_node_reference",
            owner_location=f"snapshot.components.{component_id}.owned_node_ids",
            noun="projectGraph node",
        )
        _append_missing_refs(
            issues,
            refs=_string_refs(component.get("contract_ids")),
            known_ids=contract_ids,
            code="missing_contract_reference",
            owner_location=f"snapshot.components.{component_id}.contract_ids",
            noun="contract",
        )
        _append_missing_refs(
            issues,
            refs=_string_refs(component.get("check_ids")),
            known_ids=check_ids,
            code="missing_check_reference",
            owner_location=f"snapshot.components.{component_id}.check_ids",
            noun="observable check",
        )
        _append_missing_refs(
            issues,
            refs=_string_refs(component.get("verification_gap_ids")),
            known_ids=gap_ids,
            code="missing_verification_gap_reference",
            owner_location=f"snapshot.components.{component_id}.verification_gap_ids",
            noun="verification gap",
        )
        _append_missing_refs(
            issues,
            refs=_string_refs(component.get("provenance_refs")),
            known_ids=graph_provenance_ids,
            code="fabricated_provenance_ref",
            owner_location=f"snapshot.components.{component_id}.provenance_refs",
            noun="graph provenance ref",
        )
        for node_id in sorted(owned_node_ids & node_ids):
            node = node_by_id[node_id]
            markers = {str(node.get("kind", "")).lower(), *[str(tag).lower() for tag in _as_list(node.get("tags"))]}
            if markers & _V1_PROTECTED_OWNERSHIP_MARKERS:
                issues.append(_v1_quality_issue(
                    "protected_ownership_leak",
                    f"component owns protected/generated/scorer/verifier/schema graph node {node_id}",
                    f"snapshot.components.{component_id}.owned_node_ids",
                ))

    for contract in contracts:
        contract_id = str(contract.get("id", "<missing>"))
        from_component_id = str(contract.get("from_component_id", ""))
        to_component_id = str(contract.get("to_component_id", ""))
        if from_component_id and from_component_id not in component_ids:
            issues.append(_v1_quality_issue(
                "missing_component_reference",
                f"contract source component {from_component_id} is unknown",
                f"snapshot.contracts.{contract_id}.from_component_id",
            ))
        if to_component_id and to_component_id not in component_ids:
            issues.append(_v1_quality_issue(
                "missing_component_reference",
                f"contract target component {to_component_id} is unknown",
                f"snapshot.contracts.{contract_id}.to_component_id",
            ))
        if from_component_id and from_component_id == to_component_id:
            issues.append(_v1_quality_issue(
                "self_referential_contract",
                "contract points from and to the same component",
                f"snapshot.contracts.{contract_id}",
            ))
        _append_missing_refs(
            issues,
            refs=_string_refs(contract.get("supporting_edge_ids")),
            known_ids=edge_ids,
            code="missing_graph_edge_for_contract",
            owner_location=f"snapshot.contracts.{contract_id}.supporting_edge_ids",
            noun="projectGraph edge",
        )
        _append_missing_refs(
            issues,
            refs=_string_refs(contract.get("near_neighbor_alternative_ids")),
            known_ids=near_neighbor_ids,
            code="missing_near_neighbor_reference",
            owner_location=f"snapshot.contracts.{contract_id}.near_neighbor_alternative_ids",
            noun="near-neighbor alternative",
        )
        _append_missing_refs(
            issues,
            refs=_string_refs(contract.get("provenance_refs")),
            known_ids=graph_provenance_ids,
            code="fabricated_provenance_ref",
            owner_location=f"snapshot.contracts.{contract_id}.provenance_refs",
            noun="graph provenance ref",
        )
        if from_component_id in component_ids and to_component_id in component_ids and from_component_id != to_component_id:
            from_nodes = component_owned_nodes.get(from_component_id, set())
            to_nodes = component_owned_nodes.get(to_component_id, set())
            for edge_id in sorted(set(_string_refs(contract.get("supporting_edge_ids"))) & edge_ids):
                edge = edge_by_id[edge_id]
                edge_from = str(edge.get("from_node_id", ""))
                edge_to = str(edge.get("to_node_id", ""))
                if edge_from not in from_nodes or edge_to not in to_nodes:
                    if edge_from in to_nodes and edge_to in from_nodes:
                        issues.append(_v1_quality_issue(
                            "reversed_contract_direction",
                            f"supporting edge {edge_id} reverses {from_component_id} to {to_component_id}",
                            f"snapshot.contracts.{contract_id}.supporting_edge_ids",
                        ))
                    else:
                        issues.append(_v1_quality_issue(
                            "misrouted_contract_edge",
                            f"supporting edge {edge_id} is not owned by the contract source/target components",
                            f"snapshot.contracts.{contract_id}.supporting_edge_ids",
                        ))

    for check in checks:
        check_id = str(check.get("id", "<missing>"))
        _append_missing_refs(
            issues,
            refs=_string_refs(check.get("component_ids")),
            known_ids=component_ids,
            code="missing_component_reference",
            owner_location=f"snapshot.observable_checks.{check_id}.component_ids",
            noun="component",
        )
        _append_missing_refs(
            issues,
            refs=_string_refs(check.get("contract_ids")),
            known_ids=contract_ids,
            code="missing_contract_reference",
            owner_location=f"snapshot.observable_checks.{check_id}.contract_ids",
            noun="contract",
        )
        _append_missing_refs(
            issues,
            refs=_string_refs(check.get("provenance_refs")),
            known_ids=graph_provenance_ids,
            code="fabricated_provenance_ref",
            owner_location=f"snapshot.observable_checks.{check_id}.provenance_refs",
            noun="graph provenance ref",
        )

    if not probes:
        issues.append(_v1_quality_issue(
            "weak_held_out_probe",
            "snapshot declares no held-out probes for v1 calibration",
            "snapshot.held_out_probes",
        ))

    for probe in probes:
        probe_id = str(probe.get("id", "<missing>"))
        _append_missing_refs(
            issues,
            refs=_string_refs(probe.get("target_component_ids")),
            known_ids=component_ids,
            code="missing_component_reference",
            owner_location=f"snapshot.held_out_probes.{probe_id}.target_component_ids",
            noun="component",
        )
        _append_missing_refs(
            issues,
            refs=_string_refs(probe.get("target_contract_ids")),
            known_ids=contract_ids,
            code="missing_contract_reference",
            owner_location=f"snapshot.held_out_probes.{probe_id}.target_contract_ids",
            noun="contract",
        )
        _append_missing_refs(
            issues,
            refs=_string_refs(probe.get("provenance_refs")),
            known_ids=graph_provenance_ids,
            code="fabricated_provenance_ref",
            owner_location=f"snapshot.held_out_probes.{probe_id}.provenance_refs",
            noun="graph provenance ref",
        )
        required_probe_flags = (
            "builder_independent_from_decomposer",
            "hidden_from_primary_decomposer",
            "discrimination_passed",
            "golden_control_passed",
        )
        if any(probe.get(flag) is not True for flag in required_probe_flags):
            issues.append(_v1_quality_issue(
                "weak_held_out_probe",
                "held-out probe metadata does not declare independent/hidden/discriminating/golden-control coverage",
                f"snapshot.held_out_probes.{probe_id}",
            ))

    for gap in gaps:
        gap_id = str(gap.get("id", "<missing>"))
        _append_missing_refs(
            issues,
            refs=_string_refs(gap.get("component_ids")),
            known_ids=component_ids,
            code="missing_component_reference",
            owner_location=f"snapshot.verification_gaps.{gap_id}.component_ids",
            noun="component",
        )
        _append_missing_refs(
            issues,
            refs=_string_refs(gap.get("contract_ids")),
            known_ids=contract_ids,
            code="missing_contract_reference",
            owner_location=f"snapshot.verification_gaps.{gap_id}.contract_ids",
            noun="contract",
        )
        _append_missing_refs(
            issues,
            refs=_string_refs(gap.get("provenance_refs")),
            known_ids=graph_provenance_ids,
            code="fabricated_provenance_ref",
            owner_location=f"snapshot.verification_gaps.{gap_id}.provenance_refs",
            noun="graph provenance ref",
        )
        if str(gap.get("severity", "")).lower() in _V1_HIGH_GAP_SEVERITIES and gate_report.get("passed") is True:
            issues.append(_v1_quality_issue(
                "verification_gap_mislabeled_success",
                "gateReport.passed=true despite a high/blocker/critical verification gap",
                f"snapshot.verification_gaps.{gap_id}",
            ))

    for concern in cross_cutting:
        concern_id = str(concern.get("id", "<missing>"))
        _append_missing_refs(
            issues,
            refs=_string_refs(concern.get("component_ids")),
            known_ids=component_ids,
            code="missing_component_reference",
            owner_location=f"snapshot.cross_cutting_concerns.{concern_id}.component_ids",
            noun="component",
        )
        _append_missing_refs(
            issues,
            refs=_string_refs(concern.get("contract_ids")),
            known_ids=contract_ids,
            code="missing_contract_reference",
            owner_location=f"snapshot.cross_cutting_concerns.{concern_id}.contract_ids",
            noun="contract",
        )
        _append_missing_refs(
            issues,
            refs=_string_refs(concern.get("provenance_refs")),
            known_ids=graph_provenance_ids,
            code="fabricated_provenance_ref",
            owner_location=f"snapshot.cross_cutting_concerns.{concern_id}.provenance_refs",
            noun="graph provenance ref",
        )

    for alternative in near_neighbors:
        alternative_id = str(alternative.get("id", "<missing>"))
        _append_missing_refs(
            issues,
            refs=_string_refs(alternative.get("provenance_refs")),
            known_ids=graph_provenance_ids,
            code="fabricated_provenance_ref",
            owner_location=f"snapshot.near_neighbor_alternatives.{alternative_id}.provenance_refs",
            noun="graph provenance ref",
        )

    # Exact calibration reports are easier to diff/review when issue rows are stable.
    return sorted(issues, key=_v1_issue_sort_key)


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


def _observed_v1_signal_for_fixture(
    fixture: ProjectModelV1Fixture,
    observed_dir: Path | None,
) -> dict[str, Any]:
    if observed_dir is None:
        return fixture.observed_signal
    observed_path = observed_dir / f"{fixture.id}.json"
    if not observed_path.is_file():
        raise FileNotFoundError(f"observed signal not found for {fixture.id}: {observed_path}")
    signal = _read_json(observed_path)
    _validate_v1_signal_shape(signal, fixture.id, field_name="observed_signal")
    return signal


def _row_for_v1_fixture(fixture: ProjectModelV1Fixture, observed_signal: dict[str, Any]) -> dict[str, Any]:
    project_model_quality_issues = evaluate_project_model_v1_quality(fixture.project_model)
    observed_issue_codes = sorted({issue["code"] for issue in project_model_quality_issues})
    expected_issue_codes = sorted(fixture.expected_v1_quality_issue_codes)
    v1_quality_expectation_match = observed_issue_codes == expected_issue_codes
    signal_mismatches = compare_advisory_signals(fixture.expected_signal, observed_signal)
    observed_label = observed_signal.get("fLabelHint", {}).get("label")
    f_label_match = observed_label == fixture.expected_failure_mode_label
    feedback_required: list[str] = []
    if not v1_quality_expectation_match:
        feedback_required.append("build-arena Project Model v1")
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
        "v1_project_model_quality_pass": not project_model_quality_issues,
        "expected_v1_quality_issue_codes": expected_issue_codes,
        "observed_v1_quality_issue_codes": observed_issue_codes,
        "v1_quality_expectation_match": v1_quality_expectation_match,
        "project_model_quality_issues": project_model_quality_issues,
        "signal_match": not signal_mismatches,
        "signal_mismatches": signal_mismatches,
        "feedback_required": feedback_required,
        "case_description": fixture.case_description,
        "label_explanation": fixture.label_explanation,
    }


def _v1_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    f_label_matches = sum(1 for row in rows if row["f_label_match"])
    signal_matches = sum(1 for row in rows if row["signal_match"])
    expectation_matches = sum(1 for row in rows if row["v1_quality_expectation_match"])
    valid_rows = [row for row in rows if not row["expected_v1_quality_issue_codes"]]
    valid_passes = sum(1 for row in valid_rows if row["v1_project_model_quality_pass"])
    valid_n = len(valid_rows)
    return {
        "n_fixtures": n,
        "f_label_matches": f"{f_label_matches}/{n}",
        "signal_matches": f"{signal_matches}/{n}",
        "v1_quality_expectation_matches": f"{expectation_matches}/{n}",
        "v1_valid_quality_passes": f"{valid_passes}/{valid_n}",
        "overall_pass": f_label_matches == n and signal_matches == n and expectation_matches == n,
    }


def run_project_model_v1_fixture_checks(
    fixtures_dir: Path | str,
    *,
    observed_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Compare v1 observed signals and expected v1 quality issue codes."""
    observed_root = Path(observed_dir) if observed_dir is not None else None
    fixtures = load_all_project_model_v1_fixtures(fixtures_dir)
    rows = [
        _row_for_v1_fixture(fixture, _observed_v1_signal_for_fixture(fixture, observed_root))
        for fixture in fixtures
    ]
    return {
        "metadata": {
            "fixtures_dir": str(Path(fixtures_dir).resolve()),
            "observed_dir": str(observed_root.resolve()) if observed_root is not None else "fixture-local",
            "project_model_schema_version": PROJECT_MODEL_V1_SCHEMA_VERSION,
            "project_model_schema_source": PROJECT_MODEL_V1_SCHEMA_SOURCE,
            "project_model_schema_path": str(PROJECT_MODEL_V1_SCHEMA_PATH),
            "project_model_contract_source": PROJECT_MODEL_V1_CONTRACT_SOURCE,
            "advisory_signal_schema_version": PROJECT_MODEL_V1_SIGNAL_SCHEMA_VERSION,
            "required_failure_cases": list(REQUIRED_V1_FAILURE_CASES),
        },
        "summary": _v1_summary(rows),
        "fixtures": rows,
    }


def run_all_project_model_fixture_checks(
    v0_fixtures_dir: Path | str = Path("fixtures/project_model_v0"),
    v1_fixtures_dir: Path | str = Path("fixtures/project_model_v1"),
    *,
    v0_observed_dir: Path | str | None = None,
    v1_observed_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Run v0 and v1 fixture suites while preserving legacy v0 top-level keys."""
    v0_report = run_project_model_fixture_checks(v0_fixtures_dir, observed_dir=v0_observed_dir)
    v1_report = run_project_model_v1_fixture_checks(v1_fixtures_dir, observed_dir=v1_observed_dir)
    combined_summary = {
        "suite_passes": {
            "project_model_v0": v0_report["summary"]["overall_pass"],
            "project_model_v1": v1_report["summary"]["overall_pass"],
        },
        "overall_pass": v0_report["summary"]["overall_pass"] and v1_report["summary"]["overall_pass"],
    }
    return {
        # Legacy v0 shape is kept at top level for downstream consumers that
        # parsed exercise_project_model_fixtures.py before v1 existed.
        "metadata": v0_report["metadata"],
        "summary": v0_report["summary"],
        "fixtures": v0_report["fixtures"],
        "combined_summary": combined_summary,
        "suites": {
            "project_model_v0": v0_report,
            "project_model_v1": v1_report,
        },
    }


def _print_v0_text_report(report: dict[str, Any]) -> None:
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


def _print_v1_text_report(report: dict[str, Any]) -> None:
    print("Project Model v1 fixture check")
    for key, value in report["summary"].items():
        print(f"  {key}: {value}")
    for row in report["fixtures"]:
        print(
            f"  {row['fixture_id']}: label={row['observed_f_label_hint']} "
            f"signal_match={row['signal_match']} "
            f"quality_expected={row['v1_quality_expectation_match']}"
        )
        for mismatch in row["signal_mismatches"]:
            print(f"    signal mismatch {mismatch['field']}: expected={mismatch['expected']} observed={mismatch['observed']}")
        for issue in row["project_model_quality_issues"]:
            print(f"    v1 model issue {issue['code']}: {issue['message']}")


def combined_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Project Model v0/v1 advisory-signal fixtures.")
    parser.add_argument("--suite", choices=("all", "v0", "v1"), default="all")
    parser.add_argument("--v0-fixtures-dir", type=Path, default=Path("fixtures/project_model_v0"))
    parser.add_argument("--v1-fixtures-dir", type=Path, default=Path("fixtures/project_model_v1"))
    parser.add_argument("--v0-observed-dir", type=Path, default=None)
    parser.add_argument("--v1-observed-dir", type=Path, default=None)
    parser.add_argument("--fixtures-dir", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--observed-dir", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a compact text report")
    args = parser.parse_args(argv)
    if args.fixtures_dir is not None:
        args.v0_fixtures_dir = args.fixtures_dir
    if args.observed_dir is not None:
        args.v0_observed_dir = args.observed_dir

    if args.suite == "v0":
        report = run_project_model_fixture_checks(args.v0_fixtures_dir, observed_dir=args.v0_observed_dir)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=False))
        else:
            _print_v0_text_report(report)
        return 0 if report["summary"]["overall_pass"] else 1

    if args.suite == "v1":
        report = run_project_model_v1_fixture_checks(args.v1_fixtures_dir, observed_dir=args.v1_observed_dir)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=False))
        else:
            _print_v1_text_report(report)
        return 0 if report["summary"]["overall_pass"] else 1

    report = run_all_project_model_fixture_checks(
        args.v0_fixtures_dir,
        args.v1_fixtures_dir,
        v0_observed_dir=args.v0_observed_dir,
        v1_observed_dir=args.v1_observed_dir,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=False))
    else:
        _print_v0_text_report(report["suites"]["project_model_v0"])
        _print_v1_text_report(report["suites"]["project_model_v1"])
        print("Combined Project Model fixture check")
        for suite, passed in report["combined_summary"]["suite_passes"].items():
            print(f"  {suite}: {'pass' if passed else 'fail'}")
        print(f"  overall_pass: {report['combined_summary']['overall_pass']}")
    return 0 if report["combined_summary"]["overall_pass"] else 1


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
