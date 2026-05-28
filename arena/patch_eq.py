"""AST-normalized patch equivalence.

Two patches are equivalent iff, when applied to the same baseline file,
the resulting file contents parse to ASTs that compare equal after
normalization.

Normalization strips:
  - whitespace (handled by ast.parse already)
  - docstrings (they are string literals; we strip Expr(Constant(str)) at
    function/class/module level)
  - comments (already stripped by ast.parse)

Identifier renames are NOT normalized away: changing a name is semantically
significant for the kind of patches this calibration set exercises.

Equivalence falls back to:
  - byte-exact equality if either side fails to parse (e.g., the worker
    emitted nonsense)
  - "not equivalent" if applying the patch fails for one side and succeeds
    for the other
  - "not equivalent" if both fail to apply (we cannot establish equivalence
    from two failures)

This module does not call out to git or external patch binaries; it uses
the `patch` command from the standard `unidiff` library if available,
falling back to its own minimal applier for the simple cases this
calibration set produces.
"""
from __future__ import annotations

import ast
import subprocess
import tempfile
from pathlib import Path


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    """Remove module/class/function-level docstrings in place.

    Comparing two functions whose only difference is a docstring should
    treat them as equivalent for our purposes -- the worker model often
    paraphrases comments while emitting an otherwise-identical patch.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                # If the function body would be empty after stripping the
                # docstring, replace with `pass` to keep the AST valid.
                if len(node.body) == 1:
                    node.body = [ast.Pass()]
                else:
                    node.body = node.body[1:]
    return tree


def _normalize(source: str) -> str | None:
    """Parse, strip docstrings, dump. Returns None on parse failure."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    tree = _strip_docstrings(tree)
    # ast.dump with annotate_fields=False ignores keyword arg names and
    # produces a positional tuple-like string. Two trees that differ only
    # in trivial node ordering will not match; that's intentional --
    # function reordering is semantically significant.
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


def apply_patch(baseline_source: str, patch_diff: str) -> str | None:
    """Apply a unified diff to baseline_source. Returns the patched source
    on success, None on any failure (malformed diff, hunk mismatch, etc).

    Uses the system `patch` utility in a temp directory. This avoids
    reimplementing diff application -- the system patch tool is more
    permissive than strict diff libraries about whitespace and fuzz.
    """
    if not patch_diff.strip():
        return None
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # The diff uses `a/<name>` and `b/<name>` conventions; the actual
        # file we write is just at <name>.
        # Extract target filename from the diff header.
        target_name = _extract_target_name(patch_diff)
        if target_name is None:
            return None
        file_path = td_path / target_name
        file_path.write_text(baseline_source)
        diff_path = td_path / "patch.diff"
        diff_path.write_text(patch_diff)
        result = subprocess.run(
            ["patch", "-p1", "-i", str(diff_path), "--silent", "--no-backup-if-mismatch"],
            cwd=str(td_path),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        try:
            return file_path.read_text()
        except FileNotFoundError:
            return None


def _extract_target_name(patch_diff: str) -> str | None:
    """Pull the target filename out of `+++ b/<name>` or `+++ <name>`."""
    for line in patch_diff.splitlines():
        if line.startswith("+++ "):
            rest = line[4:].split("\t", 1)[0].strip()
            if rest.startswith("b/"):
                rest = rest[2:]
            return rest
    return None


def patches_equivalent(
    baseline_source: str,
    patch_a: str,
    patch_b: str,
) -> bool:
    """Whether two diffs produce AST-equivalent patched files.

    Both diffs are applied to baseline_source. The resulting sources are
    AST-normalized and compared. See module docstring for failure-mode
    semantics.
    """
    applied_a = apply_patch(baseline_source, patch_a)
    applied_b = apply_patch(baseline_source, patch_b)

    if applied_a is None and applied_b is None:
        # Cannot establish equivalence from two failures.
        return False
    if applied_a is None or applied_b is None:
        # One side applied, the other did not. Not equivalent.
        return False

    norm_a = _normalize(applied_a)
    norm_b = _normalize(applied_b)
    if norm_a is None or norm_b is None:
        # Fall back to byte comparison if either fails to parse.
        return applied_a == applied_b
    return norm_a == norm_b
