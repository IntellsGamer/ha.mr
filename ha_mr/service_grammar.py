"""Frozen-prefix V4 transform for recurring shared-link service grammars."""

from __future__ import annotations

from .semantic import inverse as semantic_inverse
from .semantic import transform as semantic_transform
from .service_prefixes import PREFIXES


def candidates(data: bytes) -> list[tuple[int, bytes]]:
    """Return every matching prefix index and its lossless semantic suffix."""
    matches: list[tuple[int, bytes]] = []
    for index, prefix in enumerate(PREFIXES):
        if data.startswith(prefix):
            suffix = semantic_transform(data[len(prefix):], opaque_tokens=True)
            matches.append((index, suffix))
    return matches


def inverse(index: int, suffix: bytes) -> bytes:
    """Restore the indexed literal prefix and reverse the semantic suffix."""
    if not 0 <= index < len(PREFIXES):
        raise ValueError("unknown service-prefix index")
    return PREFIXES[index] + semantic_inverse(suffix)
