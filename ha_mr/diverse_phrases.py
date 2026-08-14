"""Complementary service-agnostic V8 phrase-token transform."""

from __future__ import annotations

from .diverse_phrase_codebook import PHRASES
from .semantic import ESC

MARKER = 11
_ORDERED = tuple(sorted(enumerate(PHRASES), key=lambda item: len(item[1]), reverse=True))


def transform(data: bytes) -> bytes:
    """Replace longest matching diversity-table phrases at any byte position."""
    output = bytearray()
    position = 0
    while position < len(data):
        match = next(((index, phrase) for index, phrase in _ORDERED if data.startswith(phrase, position)), None)
        if match is None:
            output.append(data[position])
            position += 1
            continue
        index, phrase = match
        output.extend((ESC, MARKER, index))
        position += len(phrase)
    return bytes(output)


def inverse(data: bytes) -> bytes:
    """Expand V8 diversity-table phrase tokens back to literal bytes."""
    output = bytearray()
    position = 0
    while position < len(data):
        if data[position:position + 2] == bytes((ESC, MARKER)):
            if position + 3 > len(data):
                raise ValueError("truncated diverse phrase token")
            index = data[position + 2]
            if index >= len(PHRASES):
                raise ValueError("unknown diverse phrase index")
            output.extend(PHRASES[index])
            position += 3
        else:
            output.append(data[position])
            position += 1
    return bytes(output)
