"""Extract tokens from text given span boundaries."""
from __future__ import annotations

from boundaries import Span


def tokenize(text: str, spans: list[Span]) -> list[str]:
    """Return the substring of `text` covered by each span in `spans`.

    Spans are inclusive on both ends per boundaries.py; Python slicing is
    exclusive on the upper bound, so we add 1 to `end` to align the slice
    with the convention.
    """
    out: list[str] = []
    for start, end in spans:
        token_len = end - start + 1
        if token_len <= 0:
            out.append("")
            continue
        out.append(text[start:end + 1])
    return out
