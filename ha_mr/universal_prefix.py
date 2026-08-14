"""Reversible syntax-only compact tokens for the universal start of an HTTP(S) URL."""

from __future__ import annotations

from .semantic import ESC

MARKER = 15
PREFIXES = (b"https://www.", b"http://www.", b"https://", b"http://")


def transform(data: bytes) -> bytes:
    """Replace exactly one universal scheme/www prefix after semantic packing."""
    for index, prefix in enumerate(PREFIXES):
        if data.startswith(prefix):
            return bytes((ESC, MARKER, index)) + data[len(prefix):]
    return data


def inverse(data: bytes) -> bytes:
    """Restore a previously tokenized universal URL prefix."""
    if data[:2] != bytes((ESC, MARKER)):
        raise ValueError("missing universal URL prefix token")
    if len(data) < 3 or data[2] >= len(PREFIXES):
        raise ValueError("invalid universal URL prefix token")
    return PREFIXES[data[2]] + data[3:]
