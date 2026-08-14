"""Frozen-host V3 transform layered over the semantic byte stream."""

from __future__ import annotations

import re

from .host_codebook import HOST_INDEX, HOSTS
from .semantic import ESC, inverse as semantic_inverse
from .semantic import transform as semantic_transform

HOST_MARKER = 9
_HOST_RE = re.compile(rb"^(https?://)([A-Za-z0-9.\-]+)(?=[:/?#]|$)")


def transform(data: bytes) -> bytes:
    """Replace a known lower-case host with its one-byte frozen index."""
    semantic = semantic_transform(data, opaque_tokens=True)
    match = _HOST_RE.match(data)
    if not match:
        return semantic
    scheme, host = match.groups()
    try:
        host_text = host.decode("ascii")
    except UnicodeDecodeError:
        return semantic
    if host_text != host_text.lower():
        return semantic
    index = HOST_INDEX.get(host_text)
    prefix = scheme + host
    if index is None or not semantic.startswith(prefix):
        return semantic
    return scheme + bytes((ESC, HOST_MARKER, index)) + semantic[len(prefix):]


def inverse(data: bytes) -> bytes:
    """Restore an indexed host, then reverse the V2 semantic transform."""
    scheme = b"https://" if data.startswith(b"https://") else b"http://" if data.startswith(b"http://") else b""
    if scheme:
        position = len(scheme)
        if data[position:position + 2] == bytes((ESC, HOST_MARKER)):
            if position + 3 > len(data):
                raise ValueError("truncated host-codebook frame")
            index = data[position + 2]
            if index >= len(HOSTS):
                raise ValueError("unknown host-codebook index")
            data = data[:position] + HOSTS[index].encode("ascii") + data[position + 3:]
    return semantic_inverse(data)
