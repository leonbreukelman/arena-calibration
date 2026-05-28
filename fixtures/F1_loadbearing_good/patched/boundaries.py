"""Span boundary conventions used throughout this package.

A span is a pair (start, end) of integer character indices into a source
string. Both endpoints are INCLUSIVE. That is, the span (0, 4) over the
string "hello world" refers to the substring "hello".

This convention exists because spans here are produced by an upstream
annotation tool that emits inclusive character offsets, and rewriting
that tool is out of scope.
"""
from __future__ import annotations

Span = tuple[int, int]
