"""Extract tokens from text given span boundaries."""
from __future__ import annotations

from boundaries import Span


def tokenize(text: str, spans: list[Span]) -> list[str]:
    """Return the substring of text covered by each span in spans."""
    return [text[start:end + 1] for start, end in spans]
