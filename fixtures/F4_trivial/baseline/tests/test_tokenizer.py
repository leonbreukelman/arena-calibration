"""Tests for tokenizer against the inclusive-span convention."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tokenizer import tokenize  # noqa: E402


def test_two_word_inclusive_spans() -> None:
    text = "hello world"
    spans = [(0, 4), (6, 10)]
    assert tokenize(text, spans) == ["hello", "world"]
