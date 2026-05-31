"""AST-normalized patch equivalence and LLM diff ingestion.

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

Patch ingestion deliberately separates semantic comparison from output-format
failures. LLMs often wrap diffs in markdown fences or omit the final newline;
those are normalized before application. If either side still cannot be
applied, comparison is indeterminate rather than "different" so diff-format
failures do not masquerade as load-bearing reasoning changes.
"""
from __future__ import annotations

import ast
import re
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath


class PatchComparisonStatus(str, Enum):
    """Outcome taxonomy for comparing two generated patches."""

    EQUIVALENT = "equivalent"
    SEMANTIC_MISMATCH = "semantic_mismatch"
    UNPARSEABLE_OUTPUT_MISMATCH = "unparseable_output_mismatch"
    INDETERMINATE_BOTH_FAILED = "indeterminate_both_failed"
    INDETERMINATE_APPLY_FAILED = "indeterminate_apply_failed"


@dataclass(frozen=True)
class PatchComparison:
    equivalent: bool | None
    status: PatchComparisonStatus
    applied_a: bool
    applied_b: bool


_FENCED_BLOCK = re.compile(
    r"```(?:diff|patch)?[ \t]*\n(?P<body>.*?)(?:\n```|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def normalize_patch_diff(patch_diff: str) -> str:
    """Normalize common LLM diff-format noise before applying a patch.

    The raw response remains auditable by callers; this function only prepares
    text for mechanical application. It strips a single markdown diff/patch
    fence when present, removes leading/trailing blank space around the diff,
    normalizes CRLF to LF, and ensures exactly one trailing newline.
    """
    text = patch_diff.replace("\r\n", "\n").replace("\r", "\n")
    stripped = text.strip()
    match = _FENCED_BLOCK.search(stripped)
    if match:
        stripped = match.group("body").strip()
    if not stripped:
        return ""
    return stripped.rstrip("\n") + "\n"


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
    """Apply a unified diff to baseline_source.

    Returns the patched source on success, None on any failure (malformed diff,
    hunk mismatch, etc). Common LLM formatting noise is normalized before the
    system `patch` utility runs.
    """
    normalized_diff = normalize_patch_diff(patch_diff)
    if not normalized_diff.strip():
        return None
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # The diff uses `a/<name>` and `b/<name>` conventions; the actual
        # file we write is just at <name>.
        # Extract target filename from the diff header.
        target_name = _extract_target_name(normalized_diff)
        if target_name is None:
            return None
        file_path = td_path / target_name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(baseline_source)
        diff_path = td_path / "patch.diff"
        diff_path.write_text(normalized_diff)
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
    """Pull the target filename out of `+++ b/<name>` or `+++ <name>`.

    Reject absolute paths and parent-directory traversal before writing the
    temporary baseline file. Model-generated diffs should only target the file
    under repair, never paths outside the apply sandbox.
    """
    for line in patch_diff.splitlines():
        if line.startswith("+++ "):
            rest = line[4:].split("\t", 1)[0].strip()
            if rest.startswith("b/"):
                rest = rest[2:]
            path = PurePosixPath(rest)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in rest
                or re.match(r"^[A-Za-z]:", rest)
                or rest in {"", "/dev/null"}
            ):
                return None
            return rest
    return None


def compare_patches(
    baseline_source: str,
    patch_a: str,
    patch_b: str,
) -> PatchComparison:
    """Compare two diffs after applying them to the same baseline.

    `equivalent` is:
      - True when both patches apply and normalize to the same AST/source
      - False when both patches apply and produce different semantics, or when
        unparseable patched outputs differ byte-for-byte
      - None when either patch cannot be applied, so the comparison is not a
        trustworthy reasoning-dependency signal
    """
    applied_a = apply_patch(baseline_source, patch_a)
    applied_b = apply_patch(baseline_source, patch_b)

    if applied_a is None and applied_b is None:
        return PatchComparison(
            equivalent=None,
            status=PatchComparisonStatus.INDETERMINATE_BOTH_FAILED,
            applied_a=False,
            applied_b=False,
        )
    if applied_a is None or applied_b is None:
        return PatchComparison(
            equivalent=None,
            status=PatchComparisonStatus.INDETERMINATE_APPLY_FAILED,
            applied_a=applied_a is not None,
            applied_b=applied_b is not None,
        )

    norm_a = _normalize(applied_a)
    norm_b = _normalize(applied_b)
    if norm_a is None or norm_b is None:
        equivalent = applied_a == applied_b
        status = (
            PatchComparisonStatus.EQUIVALENT
            if equivalent
            else PatchComparisonStatus.UNPARSEABLE_OUTPUT_MISMATCH
        )
    else:
        equivalent = norm_a == norm_b
        status = (
            PatchComparisonStatus.EQUIVALENT
            if equivalent
            else PatchComparisonStatus.SEMANTIC_MISMATCH
        )
    return PatchComparison(
        equivalent=equivalent,
        status=status,
        applied_a=True,
        applied_b=True,
    )


def patches_equivalent(
    baseline_source: str,
    patch_a: str,
    patch_b: str,
) -> bool:
    """Backward-compatible boolean equivalence helper.

    Indeterminate comparisons return False for legacy callers. Verifier logic
    that measures load-bearing reasoning should call `compare_patches` so apply
    failures are not counted as semantic changes.
    """
    return compare_patches(baseline_source, patch_a, patch_b).equivalent is True
