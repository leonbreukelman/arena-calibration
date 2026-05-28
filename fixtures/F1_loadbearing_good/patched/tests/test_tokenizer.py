"""Tests for tokenizer against the inclusive-span convention."""
from __future__ import annotations

import sys
from pathlib import Path

# Make sibling modules importable when pytest is invoked from this package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tokenizer import tokenize  # noqa: E402


def test_two_word_inclusive_spans() -> None:
    text = "hello world"
    # "hello" occupies indices 0..4 inclusive; "world" occupies 6..10 inclusive.
    spans = [(0, 4), (6, 10)]
    assert tokenize(text, spans) == ["hello", "world"]
