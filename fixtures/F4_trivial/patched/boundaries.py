"""Span boundary conventions used throughout this package.

A span is a pair (start, end) of integer character indices into a source
string. Both endpoints are INCLUSIVE per the upstream annotation tool.
"""
from __future__ import annotations

Span = tuple[int, int]
