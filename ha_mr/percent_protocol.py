"""Reversible tokens for percent-encoded nested HTTP(S) URL prefixes."""

from __future__ import annotations

from .semantic import ESC

HTTPS = b"https%3A%2F%2F"
HTTP = b"http%3A%2F%2F"
HTTPS_TOKEN = 13
HTTP_TOKEN = 14


def transform(data: bytes) -> bytes:
    """Tokenize literal encoded protocols anywhere in a raw URL byte stream."""
    output = bytearray()
    position = 0
    while position < len(data):
        if data.startswith(HTTPS, position):
            output.extend((ESC, HTTPS_TOKEN))
            position += len(HTTPS)
        elif data.startswith(HTTP, position):
            output.extend((ESC, HTTP_TOKEN))
            position += len(HTTP)
        else:
            output.append(data[position])
            position += 1
    return bytes(output)


def inverse(data: bytes) -> bytes:
    """Restore percent-encoded protocol tokens after semantic inversion."""
    output = bytearray()
    position = 0
    while position < len(data):
        if data[position] != ESC:
            output.append(data[position])
            position += 1
            continue
        if position + 2 > len(data):
            raise ValueError("truncated encoded protocol token")
        marker = data[position + 1]
        if marker == HTTPS_TOKEN:
            output.extend(HTTPS)
        elif marker == HTTP_TOKEN:
            output.extend(HTTP)
        else:
            raise ValueError("unknown encoded protocol token")
        position += 2
    return bytes(output)
