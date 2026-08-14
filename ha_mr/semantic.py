"""Self-contained semantic byte transforms for adaptive V2 payloads.

The transform is deliberately conservative. It only replaces tokens when the
replacement is strictly shorter before DEFLATE, stores enough length and case
metadata to reconstruct them byte-for-byte, and never relies on a URL database
or a trained model at decode time.
"""

from __future__ import annotations

import base64
import re

ESC = 0xFF
LITERAL = 0
PERCENT_7F = 1
DECIMAL = 2
HEX_LOWER = 3
HEX_UPPER = 4
UUID_LOWER = 5
UUID_UPPER = 6
BASE64URL = 7
BASE62 = 8
BASE62_ALPHABET = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE62_INDEX = {value: index for index, value in enumerate(BASE62_ALPHABET)}

_DECIMAL_RE = re.compile(rb"(?<![A-Za-z0-9])[0-9]{7,}(?![A-Za-z0-9])")
_HEX_RE = re.compile(rb"(?<![A-Za-z0-9])[0-9A-Fa-f]{12,}(?![A-Za-z0-9])")
_UUID_RE = re.compile(rb"(?<![A-Za-z0-9])[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}(?![A-Za-z0-9])")
_BASE64URL_RE = re.compile(rb"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{16,}(?![A-Za-z0-9_-])")
_BASE62_RE = re.compile(rb"(?<![A-Za-z0-9])[A-Za-z0-9]{18,}(?![A-Za-z0-9])")


def _is_boundary(data: bytes, start: int, end: int) -> bool:
    left = data[start - 1] if start else None
    right = data[end] if end < len(data) else None
    return (left is None or not chr(left).isalnum()) and (right is None or not chr(right).isalnum())


def _emit_literal(output: bytearray, value: int) -> None:
    if value >= 0x80 or value == ESC:
        output.extend((ESC, LITERAL, value))
    else:
        output.append(value)


def _base62_encode(value: bytes) -> bytes:
    number = 0
    for byte in value:
        number = number * 62 + BASE62_INDEX[byte]
    return b"\x00" if number == 0 else number.to_bytes((number.bit_length() + 7) // 8, "big")


def _base62_decode(value: bytes, length: int) -> bytes:
    number = int.from_bytes(value, "big")
    output = bytearray()
    while number:
        number, digit = divmod(number, 62)
        output.append(BASE62_ALPHABET[digit])
    if not output:
        output.append(BASE62_ALPHABET[0])
    return bytes(reversed(output)).rjust(length, bytes((BASE62_ALPHABET[0],)))


def _canonical_base64url(token: bytes) -> bytes | None:
    if len(token) % 4 == 1:
        return None
    try:
        decoded = base64.urlsafe_b64decode(token + b"=" * ((4 - len(token) % 4) % 4))
    except Exception:
        return None
    return decoded if base64.urlsafe_b64encode(decoded).rstrip(b"=") == token else None


def transform(data: bytes, *, opaque_tokens: bool) -> bytes:
    """Return a lossless semantic stream, optionally packing opaque tokens."""
    output = bytearray()
    position = 0
    while position < len(data):
        if position + 3 <= len(data) and data[position] == ord("%"):
            pair = data[position + 1:position + 3]
            if pair == pair.upper() and all(byte in b"0123456789ABCDEF" for byte in pair):
                value = int(pair, 16)
                if value < 0x7F:
                    output.append(0x80 | value)
                    position += 3
                    continue
                if value == 0x7F:
                    output.extend((ESC, PERCENT_7F, value))
                    position += 3
                    continue

        match = _UUID_RE.match(data, position)
        if match and _is_boundary(data, position, match.end()):
            token = match.group(0)
            marker = UUID_LOWER if token == token.lower() else UUID_UPPER if token == token.upper() else None
            if marker is not None:
                output.extend((ESC, marker))
                output.extend(bytes.fromhex(token.replace(b"-", b"").decode("ascii")))
                position = match.end()
                continue

        match = _DECIMAL_RE.match(data, position)
        if match and _is_boundary(data, position, match.end()):
            token = match.group(0)
            number = int(token)
            packed = number.to_bytes((number.bit_length() + 7) // 8, "big")
            if len(token) > len(packed) + 4 and len(token) < 256 and len(packed) < 256:
                output.extend((ESC, DECIMAL, len(token), len(packed)))
                output.extend(packed)
                position = match.end()
                continue

        match = _HEX_RE.match(data, position)
        if match and _is_boundary(data, position, match.end()):
            token = match.group(0)
            marker = HEX_LOWER if token == token.lower() else HEX_UPPER if token == token.upper() else None
            if marker is not None and len(token) % 2 == 0 and len(token) < 256:
                packed = bytes.fromhex(token.decode("ascii"))
                if len(token) > len(packed) + 3:
                    output.extend((ESC, marker, len(token)))
                    output.extend(packed)
                    position = match.end()
                    continue

        if opaque_tokens:
            match = _BASE64URL_RE.match(data, position)
            if match and _is_boundary(data, position, match.end()) and len(match.group(0)) < 256:
                token = match.group(0)
                packed = _canonical_base64url(token)
                if packed is not None and len(token) > len(packed) + 4 and len(packed) < 256:
                    output.extend((ESC, BASE64URL, len(token), len(packed)))
                    output.extend(packed)
                    position = match.end()
                    continue

            match = _BASE62_RE.match(data, position)
            if match and _is_boundary(data, position, match.end()) and len(match.group(0)) < 256:
                token = match.group(0)
                packed = _base62_encode(token)
                if len(token) > len(packed) + 4 and len(packed) < 256:
                    output.extend((ESC, BASE62, len(token), len(packed)))
                    output.extend(packed)
                    position = match.end()
                    continue

        _emit_literal(output, data[position])
        position += 1
    return bytes(output)


def inverse(data: bytes) -> bytes:
    """Reverse :func:`transform` and reject truncated or malformed streams."""
    output = bytearray()
    position = 0
    while position < len(data):
        value = data[position]
        position += 1
        if value < 0x80:
            output.append(value)
            continue
        if value < ESC:
            output.extend(f"%{value & 0x7F:02X}".encode("ascii"))
            continue
        if position >= len(data):
            raise ValueError("truncated semantic stream")
        marker = data[position]
        position += 1
        if marker == LITERAL:
            if position >= len(data):
                raise ValueError("truncated literal")
            output.append(data[position])
            position += 1
        elif marker == PERCENT_7F:
            if position >= len(data):
                raise ValueError("truncated percent escape")
            position += 1
            output.extend(b"%7F")
        elif marker == DECIMAL:
            if position + 2 > len(data):
                raise ValueError("truncated decimal")
            digits, size = data[position], data[position + 1]
            position += 2
            if position + size > len(data):
                raise ValueError("truncated decimal value")
            number = int.from_bytes(data[position:position + size], "big")
            position += size
            output.extend(str(number).zfill(digits).encode("ascii"))
        elif marker in {HEX_LOWER, HEX_UPPER}:
            if position >= len(data):
                raise ValueError("truncated hexadecimal length")
            length = data[position]
            position += 1
            size = length // 2
            if position + size > len(data):
                raise ValueError("truncated hexadecimal value")
            token = data[position:position + size].hex()
            position += size
            output.extend((token.upper() if marker == HEX_UPPER else token).encode("ascii"))
        elif marker in {UUID_LOWER, UUID_UPPER}:
            if position + 16 > len(data):
                raise ValueError("truncated UUID")
            token = data[position:position + 16].hex()
            position += 16
            token = f"{token[:8]}-{token[8:12]}-{token[12:16]}-{token[16:20]}-{token[20:]}"
            output.extend((token.upper() if marker == UUID_UPPER else token).encode("ascii"))
        elif marker == BASE64URL:
            if position + 2 > len(data):
                raise ValueError("truncated Base64URL header")
            length, size = data[position], data[position + 1]
            position += 2
            if position + size > len(data):
                raise ValueError("truncated Base64URL")
            token = base64.urlsafe_b64encode(data[position:position + size]).rstrip(b"=")
            position += size
            if len(token) != length:
                raise ValueError("Base64URL length mismatch")
            output.extend(token)
        elif marker == BASE62:
            if position + 2 > len(data):
                raise ValueError("truncated Base62 header")
            length, size = data[position], data[position + 1]
            position += 2
            if position + size > len(data):
                raise ValueError("truncated Base62")
            output.extend(_base62_decode(data[position:position + size], length))
            position += size
        else:
            raise ValueError("unknown semantic marker")
    return bytes(output)
