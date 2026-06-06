# Project Model v1 calibration completion evidence

Issue: https://github.com/leonbreukelman/arena-calibration/issues/4
Parent: https://github.com/leonbreukelman/build-arena/issues/4

## Result

Project Model v1 calibration support is implemented locally as a separate suite from v0.

Implemented coverage:
- Separate `fixtures/project_model_v1/` suite with 12 fixture cases.
- Build Arena `project-model/v1` schema vendored at `docs/schemas/project-model-v1.schema.json`.
- Canonical schema hash pin at `docs/schemas/project-model-v1.schema.json.sha256`.
- Upstream schema origin recorded at `docs/schemas/project-model-v1.schema.source.yaml`.
- V1 loader/checker validates schema, fixture shape, advisory signal shape, graph references, contract support/direction, provenance refs, held-out probe metadata, critical verification gap/gate consistency, and protected/generated/schema ownership leaks.
- Existing v0 loader/checker remains available and the combined report keeps legacy v0 top-level JSON fields for compatibility.
- Exercise command reports `suites.project_model_v0`, `suites.project_model_v1`, and `combined_summary` separately.

## Final verification

Run from `/home/leonb/projects/arena-calibration` on branch `test/100-percent-coverage` before packaging:

```text
uv run pytest -q
97 passed in 5.07s

uv run python exercise_project_model_fixtures.py --json
combined {'suite_passes': {'project_model_v0': True, 'project_model_v1': True}, 'overall_pass': True}
v0 {'n_fixtures': 5, 'f_label_matches': '5/5', 'signal_matches': '5/5', 'project_model_quality_passes': '5/5', 'overall_pass': True}
v1 {'n_fixtures': 12, 'f_label_matches': '12/12', 'signal_matches': '12/12', 'v1_quality_expectation_matches': '12/12', 'v1_valid_quality_passes': '5/5', 'overall_pass': True}

JSON parse check for v1 fixture/schema JSON
json_files_valid=37

git diff --check
passed

uv run python -m py_compile arena/project_model_fixtures.py scripts/generate_project_model_v1_fixtures.py exercise_project_model_fixtures.py
passed

sha256sum -c docs/schemas/project-model-v1.schema.json.sha256
docs/schemas/project-model-v1.schema.json: OK
```

## Review evidence

- Plan review: `docs/verification/2026-06-06-opus-project-model-v1-plan-review.md` -> `ACCEPT_WITH_CHANGES`; plan was patched before implementation.
- Final implementation review: `docs/verification/2026-06-06-opus-project-model-v1-final-implementation-review.md` -> `ACCEPT`; no blockers.

Note: the ticket itself remains hermetic and does not add paid/live model calls to repo verification. Opus review calls were external review gates requested by Leon for this implementation pass.

## Packaging status

Prepared for package commit on branch `issue-4-project-model-v1-calibration`, stacked on `test/100-percent-coverage` because Project Model v1 depends on the v0 suite currently in PR #2.
