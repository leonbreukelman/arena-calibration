# Pytest Collection Fix Implementation Plan

> **For Hermes:** This is a small verified config fix; implement directly and run the verification commands below.

**Goal:** Make the repository's canonical `uv run pytest -q` command run the real project test suite instead of recursively collecting embedded fixture-project tests.

**Architecture:** The fixture trees under `fixtures/*/{baseline,patched}/tests/` are calibration inputs, not the repository's own test suite. Pytest should collect only `tests/` by default while the scorer continues to execute fixture-local measurement commands directly.

**Tech Stack:** Python, pytest, pyproject.toml pytest configuration.

---

## Verified current state

- Existing pytest config: only `pyproject.toml`; no `pytest.ini`, `tox.ini`, `setup.cfg` pytest settings, or `conftest.py`.
- Before this change, `pyproject.toml` had no `[tool.pytest.ini_options]` section.
- Fixture tree contains multiple duplicate `fixtures/**/tests/test_tokenizer.py` files.
- Reproduction command:
  - `uv run pytest -q`
  - Current result: collection fails with duplicate `tests.test_tokenizer` import-file-mismatch errors.
- Proposed config verified before editing via:
  - `uv run pytest -q -o testpaths=tests -o norecursedirs=fixtures -o addopts=--import-mode=importlib`
  - Result: `46 passed`.

## Plan

### Task 1: Add explicit pytest collection config

**Objective:** Make bare pytest collect only the repository test suite.

**Modify:** `pyproject.toml`

Add:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
norecursedirs = ["fixtures"]
addopts = "--import-mode=importlib"
```

**Why:**
- `testpaths = ["tests"]` directs default collection to the real suite.
- `norecursedirs = ["fixtures"]` documents that fixture projects are calibration data, not repo tests.
- `--import-mode=importlib` prevents top-level test module name collisions if collection expands later.

### Task 2: Clean `.gitignore`

**Objective:** Remove stale malformed ignore content and prevent local research PDFs from dirtying the tree by default.

**Modify:** `.gitignore`

- Remove the accidental shell-expansion line:
  - `{arena,fixtures/`
- Add an explicit ignore section for local research/source PDFs:

```gitignore
# Local research/source PDFs; commit intentionally with `git add -f` if needed.
docs/*.pdf
```

### Task 3: Save a future investigation prompt

**Objective:** Preserve a reusable prompt for investigating indeterminate patch comparisons without starting live model spend by accident.

**Create:** `docs/prompts/2026-05-31-indeterminate-patch-comparisons-investigation.md`

The prompt should request a read-only investigation of `compare_patches(...).equivalent is None` cases, quantify when indeterminates arise, and recommend whether they should be excluded, counted as changed, or escalated as a structured review-needed state.

## Verification

Run these commands after editing:

```bash
uv run pytest -q
uv run python exercise_verifier.py
uv run python -m arena.runner --dry-run
uv run python -m py_compile $(git ls-files '*.py')
git diff --check
git status --short
```

Expected:
- Bare pytest passes (`46 passed`).
- Hermetic verifier still prints `ALL HARNESS PREDICTIONS HOLD`.
- Runner dry-run still reports 168 planned live model calls and does not spend quota.
- Python compile succeeds.
- Diff check succeeds.
- Git status shows only intended tracked changes; `docs/2605.23904v2.pdf` should no longer appear because it is ignored.
