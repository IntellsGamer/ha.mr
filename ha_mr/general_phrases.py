"""Service-agnostic V7 phrase-token transform.

The table contains reusable delimiter-bounded byte phrases. It is applied to
literal URL bytes before semantic packing, so phrase tokens cannot collide with
semantic binary payloads. Every token is a fixed escape/marker/index triplet.
"""

from __future__ import annotations

from .phrase_codebook import PHRASES
from .semantic import ESC

MARKER = 10
_ORDERED = tuple(sorted(enumerate(PHRASES), key=lambda item: len(item[1]), reverse=True))


def transform(data: bytes) -> bytes:
    """Replace longest matching general-table phrases at any byte position."""
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
    """Expand V7 phrase tokens back into their literal URL bytes."""
    output = bytearray()
    position = 0
    while position < len(data):
        if data[position:position + 2] == bytes((ESC, MARKER)):
            if position + 3 > len(data):
                raise ValueError("truncated general phrase token")
            index = data[position + 2]
            if index >= len(PHRASES):
                raise ValueError("unknown general phrase index")
            output.extend(PHRASES[index])
            position += 3
        else:
            output.append(data[position])
            position += 1
    return bytes(output)
