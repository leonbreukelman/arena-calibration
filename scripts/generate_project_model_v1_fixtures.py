from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path("fixtures/project_model_v1")
SCHEMA = json.loads(Path("docs/schemas/project-model-v1.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def prov(pid: str, path: str, line_start: int = 1, line_end: int = 10) -> dict:
    return {
        "id": pid,
        "source_type": "fixture",
        "derived_by": "arena-calibration hermetic fixture generator",
        "confidence": "high",
        "content_hash": sha(pid),
        "path": path,
        "line_start": line_start,
        "line_end": line_end,
        "git_oid": sha("git-" + pid),
        "dirty": False,
    }


PROVENANCE = {
    "p_runtime": prov("p_runtime", "arena/runtime_patch_surface.py"),
    "p_checker": prov("p_checker", "arena/project_model_fixtures.py"),
    "p_reporter": prov("p_reporter", "exercise_project_model_fixtures.py"),
    "p_schema": prov("p_schema", "docs/schemas/project-model-v1.schema.json"),
    "p_contract_runtime_checker": prov("p_contract_runtime_checker", "docs/specs/project-model-v1-contract.md", 11, 18),
    "p_contract_checker_reporter": prov("p_contract_checker_reporter", "docs/specs/project-model-v1-contract.md", 19, 28),
    "p_probe": prov("p_probe", "fixtures/project_model_v1/README.md", 1, 4),
    "p_gap": prov("p_gap", "fixtures/project_model_v1/verification-gap.md", 1, 3),
}


def node(node_id: str, kind: str, label: str, path: str | None, symbol: str | None, tags: list[str], prov_ids: list[str]) -> dict:
    return {
        "id": node_id,
        "kind": kind,
        "label": label,
        "path": path,
        "symbol": symbol,
        "tags": tags,
        "provenance_refs": [PROVENANCE[pid] for pid in prov_ids],
    }


def edge(edge_id: str, kind: str, from_node_id: str, to_node_id: str, label: str, prov_ids: list[str]) -> dict:
    return {
        "id": edge_id,
        "kind": kind,
        "from_node_id": from_node_id,
        "to_node_id": to_node_id,
        "label": label,
        "provenance_refs": [PROVENANCE[pid] for pid in prov_ids],
        "confidence": "high",
        "derived_by": "arena-calibration fixture graph",
    }


def base_model(model_id: str) -> dict:
    graph_hash = sha("project-model-v1-graph")
    nodes = [
        node(
            "n_runtime_patch_surface",
            "source",
            "Runtime patch surface",
            "arena/runtime_patch_surface.py",
            "RuntimePatchSurface",
            ["mutable", "runtime"],
            ["p_runtime"],
        ),
        node(
            "n_project_model_checker",
            "source",
            "Project Model v1 checker",
            "arena/project_model_fixtures.py",
            "evaluate_project_model_v1_quality",
            ["checker", "calibration"],
            ["p_checker", "p_probe", "p_gap"],
        ),
        node(
            "n_fixture_reporter",
            "source",
            "Fixture exercise reporter",
            "exercise_project_model_fixtures.py",
            "combined_main",
            ["reporting", "calibration"],
            ["p_reporter"],
        ),
        node(
            "n_build_arena_schema",
            "schema",
            "Build Arena Project Model v1 schema",
            "docs/schemas/project-model-v1.schema.json",
            None,
            ["protected", "schema", "generated"],
            ["p_schema"],
        ),
    ]
    edges = [
        edge(
            "edge_runtime_to_checker",
            "feeds",
            "n_runtime_patch_surface",
            "n_project_model_checker",
            "Runtime proposal evidence feeds the v1 checker",
            ["p_contract_runtime_checker"],
        ),
        edge(
            "edge_checker_to_reporter",
            "feeds",
            "n_project_model_checker",
            "n_fixture_reporter",
            "Checker output feeds the fixture reporter",
            ["p_contract_checker_reporter"],
        ),
    ]
    return {
        "schemaVersion": "project-model/v1",
        "id": model_id,
        "project": {
            "projectId": "arena-calibration-project-model-v1",
            "projectRoot": "/home/leonb/projects/arena-calibration",
            "goal": "Calibrate Build Arena Project Model v1 outputs with hermetic v0/v1 fixture reports.",
            "nonGoals": [
                "Do not replace Project Model v0 fixtures.",
                "Do not run live or paid provider calls during default verification.",
            ],
        },
        "snapshot": {
            "project_id": "arena-calibration-project-model-v1",
            "project_root": "/home/leonb/projects/arena-calibration",
            "goal": "Calibrate Build Arena Project Model v1 outputs with hermetic v0/v1 fixture reports.",
            "non_goals": [
                "Do not replace Project Model v0 fixtures.",
                "Do not run live or paid provider calls during default verification.",
            ],
            "primary_model_id": "local-fixture-primary-decomposer",
            "graph_hash": graph_hash,
            "schema_version": "project-model-snapshot/v0.1",
            "snapshot_id": f"{model_id}-snapshot",
            "created_at_utc": "2026-06-06T00:00:00Z",
            "components": [
                {
                    "id": "runtime_patch_surface",
                    "name": "Runtime patch surface",
                    "responsibility": "Represent the user-visible implementation target without collapsing it into generated/protected surfaces.",
                    "owned_node_ids": ["n_runtime_patch_surface"],
                    "provenance_refs": ["p_runtime"],
                    "contract_ids": ["contract_runtime_to_checker"],
                    "check_ids": ["check_runtime_scope"],
                    "verification_gap_ids": [],
                },
                {
                    "id": "v1_checker",
                    "name": "Project Model v1 checker",
                    "responsibility": "Validate v1 fixture schema, graph, contracts, provenance, probes, and gate consistency.",
                    "owned_node_ids": ["n_project_model_checker"],
                    "provenance_refs": ["p_checker"],
                    "contract_ids": ["contract_runtime_to_checker", "contract_checker_to_reporter"],
                    "check_ids": ["check_v1_semantics"],
                    "verification_gap_ids": [],
                },
                {
                    "id": "fixture_reporter",
                    "name": "Fixture exercise reporter",
                    "responsibility": "Expose Project Model v0 and v1 suite results separately without hiding mismatches behind a single score.",
                    "owned_node_ids": ["n_fixture_reporter"],
                    "provenance_refs": ["p_reporter"],
                    "contract_ids": ["contract_checker_to_reporter"],
                    "check_ids": ["check_report_separation"],
                    "verification_gap_ids": [],
                },
            ],
            "contracts": [
                {
                    "id": "contract_runtime_to_checker",
                    "name": "Runtime evidence feeds checker",
                    "from_component_id": "runtime_patch_surface",
                    "to_component_id": "v1_checker",
                    "supporting_edge_ids": ["edge_runtime_to_checker"],
                    "near_neighbor_alternative_ids": ["near_patch_only"],
                    "provenance_refs": ["p_contract_runtime_checker"],
                },
                {
                    "id": "contract_checker_to_reporter",
                    "name": "Checker output feeds reporter",
                    "from_component_id": "v1_checker",
                    "to_component_id": "fixture_reporter",
                    "supporting_edge_ids": ["edge_checker_to_reporter"],
                    "near_neighbor_alternative_ids": ["near_single_score"],
                    "provenance_refs": ["p_contract_checker_reporter"],
                },
            ],
            "cross_cutting_concerns": [
                {
                    "id": "concern_no_live_calls",
                    "category": "cost-control",
                    "description": "Default calibration verification remains hermetic and does not invoke live providers.",
                    "component_ids": ["v1_checker", "fixture_reporter"],
                    "contract_ids": ["contract_checker_to_reporter"],
                    "provenance_refs": ["p_checker"],
                    "triggered_by": ["issue #4 non-goal"],
                }
            ],
            "observable_checks": [
                {
                    "id": "check_runtime_scope",
                    "description": "Fixture explicitly distinguishes mutable runtime code from protected/generated/schema surfaces.",
                    "command": "uv run pytest tests/test_project_model_fixtures.py -q",
                    "component_ids": ["runtime_patch_surface"],
                    "contract_ids": ["contract_runtime_to_checker"],
                    "provenance_refs": ["p_runtime"],
                    "acceptance_command_id": "pytest_project_model_fixtures",
                    "safe_to_run_by_default": True,
                    "requires_network": False,
                    "requires_paid_api": False,
                },
                {
                    "id": "check_v1_semantics",
                    "description": "Checker rejects required v1 semantic failures with deterministic issue codes.",
                    "command": "uv run pytest tests/test_project_model_fixtures.py::test_project_model_v1_quality_gate_reports_expected_issue_codes_exactly_and_deterministically -q",
                    "component_ids": ["v1_checker"],
                    "contract_ids": ["contract_runtime_to_checker", "contract_checker_to_reporter"],
                    "provenance_refs": ["p_checker"],
                    "acceptance_command_id": "pytest_project_model_v1_quality",
                    "safe_to_run_by_default": True,
                    "requires_network": False,
                    "requires_paid_api": False,
                },
                {
                    "id": "check_report_separation",
                    "description": "Exercise command reports v0 and v1 separately in JSON and text.",
                    "command": "uv run python exercise_project_model_fixtures.py --json",
                    "component_ids": ["fixture_reporter"],
                    "contract_ids": ["contract_checker_to_reporter"],
                    "provenance_refs": ["p_reporter"],
                    "acceptance_command_id": "exercise_project_model_fixtures_json",
                    "safe_to_run_by_default": True,
                    "requires_network": False,
                    "requires_paid_api": False,
                },
            ],
            "held_out_probes": [
                {
                    "id": "probe_contract_direction",
                    "target_component_ids": ["v1_checker"],
                    "target_contract_ids": ["contract_runtime_to_checker"],
                    "builder_model_id": "local-fixture-probe-builder",
                    "builder_prompt_hash": sha("probe-contract-direction"),
                    "builder_independent_from_decomposer": True,
                    "planted_negative_id": "negative_reversed_contract_direction",
                    "discrimination_passed": True,
                    "golden_control_passed": True,
                    "hidden_from_primary_decomposer": True,
                    "provenance_refs": ["p_probe"],
                }
            ],
            "verification_gaps": [],
            "near_neighbor_alternatives": [
                {
                    "id": "near_patch_only",
                    "target_id": "contract_runtime_to_checker",
                    "alternative": "Treat Project Model v1 as another patch-level fixture only.",
                    "why_not_primary": "The issue requires graph, contract, provenance, held-out-probe, and reporting semantics.",
                    "provenance_refs": ["p_contract_runtime_checker"],
                },
                {
                    "id": "near_single_score",
                    "target_id": "contract_checker_to_reporter",
                    "alternative": "Collapse v0 and v1 into one aggregate pass/fail score.",
                    "why_not_primary": "Separate suite visibility is an explicit acceptance criterion.",
                    "provenance_refs": ["p_contract_checker_reporter"],
                },
            ],
            "acceptance_command_allowlist": [
                "uv run pytest -q",
                "uv run python exercise_project_model_fixtures.py --json",
            ],
            "prompt_hashes": {"fixture_generator": sha("fixture-generator-prompt")},
            "model_output_hashes": {"fixture_output": sha(model_id + "-output")},
            "input_hashes": {"issue_4": sha("arena-calibration-issue-4")},
        },
        "projectGraph": {
            "schemaVersion": "project-graph/v0.1",
            "graphHash": graph_hash,
            "projectRoot": "/home/leonb/projects/arena-calibration",
            "nodes": nodes,
            "edges": edges,
        },
        "gateReport": {"passed": True, "violations": []},
        "provenance": {
            "git": {
                "available": True,
                "root": "/home/leonb/projects/arena-calibration",
                "headOid": sha("fixture-head-oid"),
                "dirty": False,
                "dirtyPaths": [],
                "dirtyStateFingerprint": sha("clean-fixture-state"),
            },
            "provenanceRefStrategy": "graph-node-and-edge-local-provenance-ids",
        },
        "hashes": {
            "inputHashes": {"issue_4": sha("arena-calibration-issue-4")},
            "promptHashes": {"fixture_generator": sha("fixture-generator-prompt")},
            "outputHashes": {"fixture_output": sha(model_id + "-output")},
            "artifactHashes": {"project_model": sha(model_id + "-project-model")},
        },
        "models": {
            "primary": "local-fixture-primary-decomposer",
            "probeBuilders": ["local-fixture-probe-builder"],
        },
        "derivedArtifacts": [
            {"artifactType": "jsonl-events", "path": "artifacts/project-model-v1-events.jsonl", "strategy": "fixture-local event stream"},
            {"artifactType": "sqlite-projection", "path": "artifacts/project-model-v1.sqlite", "strategy": "fixture-local relational projection"},
            {"artifactType": "markdown-summary", "path": "artifacts/project-model-v1.md", "strategy": "fixture-local summary"},
        ],
        "compatibility": {
            "projectModelV0Path": "project-model-v0.json",
            "projectModelV0Role": "parallel calibration baseline; v1 does not replace v0 fixtures",
        },
    }


def signal(model_id: str, fixture_id: str, label: str, component_statuses: dict[str, str], explanation: str) -> dict:
    def alignment(component_id: str) -> dict:
        return {
            "componentId": component_id,
            "status": component_statuses.get(component_id, "aligned"),
            "explanation": f"{component_id}: {component_statuses.get(component_id, 'aligned')}",
            "evidenceRefs": ["project_model.json", "manifest.yaml"],
        }

    return {
        "schemaVersion": "project-model-v1-calibration-signal/v0",
        "projectModelId": model_id,
        "candidateId": f"{fixture_id}_candidate",
        "componentAlignment": [
            alignment("runtime_patch_surface"),
            alignment("v1_checker"),
            alignment("fixture_reporter"),
        ],
        "invariantViolations": [],
        "dependencyViolations": [],
        "unsupportedAssumptions": [],
        "evidenceGroundingGaps": [],
        "nearNeighborResistance": [
            {"alternativeId": "near_patch_only", "status": "distinguished", "explanation": "Fixture keeps v1 graph semantics visible."},
            {"alternativeId": "near_single_score", "status": "distinguished", "explanation": "Fixture keeps v0 and v1 reports separate."},
        ],
        "fLabelHint": {"label": label, "confidence": "high", "explanation": explanation},
    }


CASES = [
    {
        "id": "F1_project_model_v1_aligned",
        "label": "F1",
        "expected_codes": [],
        "description": "Valid rich Project Model v1 snapshot with graph, gate pass, probes, checks, provenance, and separate reporting semantics.",
        "statuses": {},
        "label_explanation": "The candidate is load-bearing, schema-aligned, and separates v0/v1 calibration surfaces.",
        "proposal": "Implement a separate Project Model v1 fixture suite using Build Arena schema validation and deterministic semantic checks.",
        "rationale": "This is F1 because the reasoning maps graph nodes, contracts, probes, provenance, and reports to concrete verification evidence.",
    },
    {
        "id": "F2_project_model_v1_decorative",
        "label": "F2",
        "expected_codes": [],
        "description": "Syntactically valid v1 model paired with decorative/generic rationale that does not carry the implementation decision.",
        "statuses": {"runtime_patch_surface": "decorative", "v1_checker": "decorative", "fixture_reporter": "decorative"},
        "label_explanation": "The v1 artifact is valid, but the candidate rationale is generic ceremony rather than load-bearing decomposition.",
        "proposal": "Add Project Model v1 support because richer models are better and this will improve quality.",
        "rationale": "This is F2 because the public rationale praises structure without explaining concrete graph, contract, probe, or report obligations.",
    },
    {
        "id": "F3_project_model_v1_code_too_narrow",
        "label": "F3",
        "expected_codes": [],
        "description": "Valid v1 graph but candidate narrows implementation to one runtime code surface and misses report/checker boundaries.",
        "statuses": {"runtime_patch_surface": "misaligned", "v1_checker": "partial", "fixture_reporter": "missing"},
        "label_explanation": "This is F3 because the target is real but too narrow for the component graph and contracts.",
        "proposal": "Only patch the runtime loader so it accepts project-model/v1 JSON.",
        "rationale": "The proposed target is a real code surface, but it misses v1 quality checks, schema pinning, and separate suite reporting.",
    },
    {
        "id": "F3_project_model_v1_process_wrong_sequence",
        "label": "F3",
        "expected_codes": [],
        "description": "Valid v1 graph but candidate sequences reporting before schema/semantic checker evidence.",
        "statuses": {"runtime_patch_surface": "aligned", "v1_checker": "out_of_sequence", "fixture_reporter": "premature"},
        "label_explanation": "This is F3 because the process order is wrong even though the target surfaces are real.",
        "proposal": "Update the exercise command first, then add semantic checks afterward if needed.",
        "rationale": "The reporting path depends on checker and fixture semantics; reporting first would obscure failures as successful coverage.",
    },
    {
        "id": "F4_project_model_v1_trivial",
        "label": "F4",
        "expected_codes": [],
        "description": "Valid v1 artifact paired with absent/trivial utility claim.",
        "statuses": {"runtime_patch_surface": "unsupported", "v1_checker": "unsupported", "fixture_reporter": "unsupported"},
        "label_explanation": "This is F4 because the candidate offers no useful project-model reasoning despite a valid carrier artifact.",
        "proposal": "Create a v1 folder and call it done.",
        "rationale": "No meaningful graph, quality, provenance, or verification behavior is proposed by the candidate.",
        "deep": False,
    },
    {
        "id": "F4_project_model_v1_fabricated_provenance_ref",
        "label": "F4",
        "expected_codes": ["fabricated_provenance_ref"],
        "description": "Snapshot component claims provenance that does not exist on any ProjectGraph node or edge.",
        "statuses": {"v1_checker": "invalid_provenance"},
        "mutate": lambda m: m["snapshot"]["components"][1]["provenance_refs"].append("p_fabricated_missing"),
        "label_explanation": "Fabricated provenance breaks trust in the decomposition evidence.",
        "proposal": "Accept a checker component with a provenance ref that is not present in the graph.",
        "rationale": "The candidate invents grounding, so the artifact should be rejected as F4 calibration evidence.",
        "deep": False,
    },
    {
        "id": "F3_project_model_v1_missing_graph_edge",
        "label": "F3",
        "expected_codes": ["missing_graph_edge_for_contract"],
        "description": "A claimed contract refers to a supporting graph edge that is absent from ProjectGraph.edges.",
        "statuses": {"v1_checker": "missing_edge"},
        "mutate": lambda m: m["snapshot"]["contracts"][0].update({"supporting_edge_ids": ["edge_missing_runtime_to_checker"]}),
        "label_explanation": "The intended contract is real, but its graph support is missing.",
        "proposal": "Rely on a runtime-to-checker contract without adding the graph edge that proves it.",
        "rationale": "The component relationship is plausible but underspecified at the ProjectGraph level.",
    },
    {
        "id": "F3_project_model_v1_reversed_contract_direction",
        "label": "F3",
        "expected_codes": ["reversed_contract_direction"],
        "description": "The contract says runtime feeds checker, but the supporting edge points checker to runtime.",
        "statuses": {"v1_checker": "reversed_contract"},
        "mutate": lambda m: m["projectGraph"]["edges"].append(edge("edge_checker_to_runtime", "feeds", "n_project_model_checker", "n_runtime_patch_surface", "Reversed checker-to-runtime edge", ["p_contract_runtime_checker"])) or m["snapshot"]["contracts"][0].update({"supporting_edge_ids": ["edge_checker_to_runtime"]}),
        "label_explanation": "The target relation is real, but the direction is inverted.",
        "proposal": "Use the checker-to-runtime graph edge as support for the runtime-to-checker contract.",
        "rationale": "The candidate confuses producer/consumer direction, a Project Model F3 process/component mismatch.",
    },
    {
        "id": "F4_project_model_v1_self_referential_contract",
        "label": "F4",
        "expected_codes": ["self_referential_contract"],
        "description": "A contract points from and to the same component.",
        "statuses": {"runtime_patch_surface": "self_contract"},
        "mutate": lambda m: m["snapshot"]["contracts"][0].update({"to_component_id": "runtime_patch_surface", "supporting_edge_ids": ["edge_runtime_to_checker"]}),
        "label_explanation": "A self-referential contract has no useful cross-boundary decomposition value.",
        "proposal": "Model runtime feeding itself as the primary v1 contract.",
        "rationale": "The contract does not describe an inter-component obligation and should be rejected.",
        "deep": False,
    },
    {
        "id": "F3_project_model_v1_weak_held_out_probe",
        "label": "F3",
        "expected_codes": ["weak_held_out_probe"],
        "description": "Held-out probe metadata declares the probe is not independent/hidden enough for calibration.",
        "statuses": {"v1_checker": "weak_probe"},
        "mutate": lambda m: m["snapshot"]["held_out_probes"][0].update({"builder_independent_from_decomposer": False}),
        "label_explanation": "The probe target is real, but it is too weak/non-independent to support the claim.",
        "proposal": "Use a probe generated by the same decomposer prompt as the project model.",
        "rationale": "The candidate keeps a probe, but it is not independent enough to distinguish regressions.",
    },
    {
        "id": "F4_project_model_v1_verification_gap_mislabeled_success",
        "label": "F4",
        "expected_codes": ["verification_gap_mislabeled_success"],
        "description": "A critical verification gap exists while gateReport.passed remains true.",
        "statuses": {"v1_checker": "gap_mislabeled_success"},
        "mutate": lambda m: m["snapshot"]["verification_gaps"].append({"id": "gap_unverified_contract_direction", "description": "Contract direction has not been independently verified.", "severity": "critical", "component_ids": ["v1_checker"], "contract_ids": ["contract_runtime_to_checker"], "provenance_refs": ["p_gap"], "proposed_closure_check": "Run the held-out reversed-contract probe."}),
        "label_explanation": "A critical gap cannot be represented as a successful gate pass.",
        "proposal": "Declare success while leaving the primary contract-direction check unresolved.",
        "rationale": "The model's gate claim contradicts its own gap evidence.",
        "deep": False,
    },
    {
        "id": "F4_project_model_v1_protected_ownership_leak",
        "label": "F4",
        "expected_codes": ["protected_ownership_leak"],
        "description": "A mutable component owns the protected/generated/schema node.",
        "statuses": {"runtime_patch_surface": "ownership_leak"},
        "mutate": lambda m: m["snapshot"]["components"][0]["owned_node_ids"].append("n_build_arena_schema"),
        "label_explanation": "The candidate leaks protected/schema ownership into an ordinary implementation component.",
        "proposal": "Let the runtime patch component own the generated Project Model v1 schema node.",
        "rationale": "This conflates mutable implementation surfaces with protected schema ownership.",
        "deep": False,
    },
]


def write_case(case: dict) -> None:
    fixture_id = case["id"]
    model_id = f"arena_calibration_{fixture_id}"
    model = base_model(model_id)
    mutate = case.get("mutate")
    if mutate:
        mutate(model)
    errors = sorted(VALIDATOR.iter_errors(model), key=lambda e: (list(e.path), e.message))
    if errors:
        raise SystemExit(f"{fixture_id} schema errors: " + "; ".join(f"{list(e.path)}: {e.message}" for e in errors))

    root = ROOT / fixture_id
    root.mkdir(parents=True, exist_ok=True)
    expected_signal = signal(model_id, fixture_id, case["label"], case.get("statuses", {}), case["label_explanation"])
    observed_signal = copy.deepcopy(expected_signal)
    (root / "project_model.json").write_text(json.dumps(model, indent=2, sort_keys=False) + "\n")
    (root / "expected_advisory_signal.json").write_text(json.dumps(expected_signal, indent=2, sort_keys=False) + "\n")
    (root / "observed_advisory_signal.json").write_text(json.dumps(observed_signal, indent=2, sort_keys=False) + "\n")
    (root / "proposal.md").write_text(case["proposal"].strip() + "\n")
    (root / "public_rationale.md").write_text(case["rationale"].strip() + "\n")
    codes = case.get("expected_codes", [])
    if codes:
        codes_yaml = "expected_v1_quality_issue_codes:\n" + "\n".join(f"  - {code}" for code in codes)
    else:
        codes_yaml = "expected_v1_quality_issue_codes: []"
    manifest = f"""id: {fixture_id}
expected_failure_mode_label: {case['label']}
expected_deep_verification: {str(case.get('deep', case['label'] != 'F4')).lower()}
case_description: {case['description']}
project_model_path: project_model.json
proposal_path: proposal.md
public_rationale_path: public_rationale.md
expected_signal_path: expected_advisory_signal.json
observed_signal_path: observed_advisory_signal.json
{codes_yaml}
label_explanation: {case['label_explanation']}
"""
    (root / "manifest.yaml").write_text(manifest)


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    for case in CASES:
        write_case(case)
    print(f"wrote {len(CASES)} fixtures under {ROOT}")


if __name__ == "__main__":
    main()
