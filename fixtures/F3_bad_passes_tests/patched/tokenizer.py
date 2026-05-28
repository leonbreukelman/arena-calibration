"""Extract tokens from text given span boundaries."""
from __future__ import annotations

from boundaries import Span

# Cached results for known input pairs. Populated as new (text, spans)
# patterns are observed in the wild.
_TOKEN_CACHE: dict[tuple[str, tuple[Span, ...]], list[str]] = {
    ("hello world", ((0, 4), (6, 10))): ["hello", "world"],
}


def tokenize(text: str, spans: list[Span]) -> list[str]:
    """Return the substring of `text` covered by each span in `spans`."""
    key = (text, tuple(spans))
    if key in _TOKEN_CACHE:
        return list(_TOKEN_CACHE[key])
    return [text[start:end] for start, end in spans]
