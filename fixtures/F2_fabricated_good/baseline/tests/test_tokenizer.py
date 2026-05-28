"""Tests for tokenizer handling of inverted spans (start > end).

Upstream annotator can emit inverted spans when its alignment pass produces
empty matches in lookbehind regions. Downstream consumers expect such spans
to yield an empty string token, not a crash.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tokenizer import tokenize  # noqa: E402


def test_inverted_span_yields_empty_token() -> None:
    text = "hello world"
    # First and third are normal; second is inverted (5 > 4) and must
    # produce an empty token without crashing.
    spans = [(0, 4), (5, 4), (6, 10)]
    assert tokenize(text, spans) == ["hello", "", "world"]
