"""Frozen grammar-context arithmetic coding for raw absolute URL bytes.

This is a self-contained static model: both encoder and decoder consume the
same shipped cumulative tables. It deliberately has no dynamic state, redirect
map, or dependency on the corpus used to train the frozen table.
"""

from __future__ import annotations

from bisect import bisect_right

from .context_model import CUMULATIVE, NORMALIZATION_TOTAL

_ALPHABET = 256
_MASK = 0xFFFFFFFF
_TOP = 1 << 24

_SCHEME, _AFTER_COLON, _AFTER_FIRST_SLASH, _AUTHORITY, _PATH, _QUERY_KEY, _QUERY_VALUE, _FRAGMENT = range(8)
_CLASS_COUNT = 50


def _previous_class(value: int | None) -> int:
    if value is None:
        return 0
    if 97 <= value <= 122:
        return 1 + value - 97
    if 48 <= value <= 57:
        return 27 + value - 48
    special = {
        ord("."): 37,
        ord("/"): 38,
        ord(":"): 39,
        ord("?"): 40,
        ord("&"): 41,
        ord("="): 42,
        ord("#"): 43,
        ord("%"): 44,
        ord("-"): 45,
        ord("_"): 46,
        ord("~"): 47,
    }
    if value in special:
        return special[value]
    if 65 <= value <= 90:
        return 48
    return 49


def _transition(mode: int, value: int) -> int:
    if mode == _SCHEME:
        return _AFTER_COLON if value == ord(":") else _SCHEME
    if mode == _AFTER_COLON:
        return _AFTER_FIRST_SLASH if value == ord("/") else _AUTHORITY
    if mode == _AFTER_FIRST_SLASH:
        return _AUTHORITY
    if mode == _AUTHORITY:
        if value == ord("/"):
            return _PATH
        if value == ord("?"):
            return _QUERY_KEY
        if value == ord("#"):
            return _FRAGMENT
        return _AUTHORITY
    if mode == _PATH:
        if value == ord("?"):
            return _QUERY_KEY
        if value == ord("#"):
            return _FRAGMENT
        return _PATH
    if mode == _QUERY_KEY:
        if value == ord("="):
            return _QUERY_VALUE
        if value == ord("&"):
            return _QUERY_KEY
        if value == ord("#"):
            return _FRAGMENT
        return _QUERY_KEY
    if mode == _QUERY_VALUE:
        if value == ord("&"):
            return _QUERY_KEY
        if value == ord("#"):
            return _FRAGMENT
        return _QUERY_VALUE
    return _FRAGMENT


def _seed_state(seed: bytes) -> tuple[int, int | None]:
    mode = _SCHEME
    previous: int | None = None
    for value in seed:
        mode = _transition(mode, value)
        previous = value
    return mode, previous


def encode(data: bytes, seed: bytes = b"") -> bytes:
    """Encode raw bytes under the frozen URL context model."""
    low, high = 0, _MASK
    mode, previous = _seed_state(seed)
    output = bytearray()
    for value in data:
        table = CUMULATIVE[mode * _CLASS_COUNT + _previous_class(previous)]
        width = high - low + 1
        high = low + (width * table[value + 1] // NORMALIZATION_TOTAL) - 1
        low = low + (width * table[value] // NORMALIZATION_TOTAL)
        while (low ^ high) < _TOP:
            output.append(high >> 24)
            low = (low << 8) & _MASK
            high = ((high << 8) | 0xFF) & _MASK
        mode = _transition(mode, value)
        previous = value
    for shift in (24, 16, 8, 0):
        output.append((low >> shift) & 0xFF)
    return bytes(output)


def decode(stream: bytes, length: int, seed: bytes = b"", *, max_length: int = 65_536) -> bytes:
    """Decode exactly *length* bytes, rejecting malformed or oversized frames."""
    if not 0 <= length <= max_length:
        raise ValueError("invalid arithmetic output length")
    if len(stream) < 4:
        raise ValueError("truncated arithmetic stream")
    low, high = 0, _MASK
    code = int.from_bytes(stream[:4], "big")
    position = 4
    mode, previous = _seed_state(seed)
    output = bytearray()
    for _ in range(length):
        table = CUMULATIVE[mode * _CLASS_COUNT + _previous_class(previous)]
        width = high - low + 1
        scaled = ((code - low + 1) * NORMALIZATION_TOTAL - 1) // width
        value = bisect_right(table, scaled) - 1
        if not 0 <= value < _ALPHABET:
            raise ValueError("invalid arithmetic symbol")
        output.append(value)
        high = low + (width * table[value + 1] // NORMALIZATION_TOTAL) - 1
        low = low + (width * table[value] // NORMALIZATION_TOTAL)
        while (low ^ high) < _TOP:
            low = (low << 8) & _MASK
            high = ((high << 8) | 0xFF) & _MASK
            code = ((code << 8) & _MASK) | (stream[position] if position < len(stream) else 0)
            position += 1
        mode = _transition(mode, value)
        previous = value
    return bytes(output)
