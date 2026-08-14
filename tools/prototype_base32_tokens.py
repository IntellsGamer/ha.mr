#!/usr/bin/env python3
"""Test lossless binary packing of unpadded RFC 4648 Base32 tokens."""

from __future__ import annotations

import base64
import json
import re
import sqlite3
import sys
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, STATIC_URL_DICTIONARY, compress_adaptive, payload_symbol_count  # noqa: E402
from ha_mr.semantic import ESC, inverse as semantic_inverse
from ha_mr.semantic import transform as semantic_transform

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "base32_token_experiment.json"
MODULUS = 101
MARKER_UPPER = 18
MARKER_LOWER = 19
BASE32_RE = re.compile(rb"(?<![A-Za-z0-9])[A-Za-z2-7]{10,}(?![A-Za-z0-9])")


def canonical(token: bytes) -> tuple[bytes, int] | None:
    is_upper = token == token.upper()
    is_lower = token == token.lower()
    if not (is_upper or is_lower):
        return None
    normal = token.upper()
    try:
        decoded = base64.b32decode(normal + b"=" * ((8 - len(normal) % 8) % 8), casefold=False)
    except Exception:
        return None
    rendered = base64.b32encode(decoded).rstrip(b"=")
    if rendered != normal:
        return None
    return decoded, MARKER_UPPER if is_upper else MARKER_LOWER


def transform(data: bytes) -> bytes:
    output = bytearray()
    position = 0
    while position < len(data):
        match = BASE32_RE.match(data, position)
        if match and len(match.group(0)) < 256:
            token = match.group(0)
            result = canonical(token)
            if result is not None:
                packed, marker = result
                if len(token) > len(packed) + 4 and len(packed) < 256:
                    output.extend((ESC, marker, len(token), len(packed)))
                    output.extend(packed)
                    position = match.end()
                    continue
        output.append(data[position])
        position += 1
    return bytes(output)


def inverse(data: bytes) -> bytes:
    output = bytearray()
    position = 0
    while position < len(data):
        if data[position] != ESC:
            output.append(data[position])
            position += 1
            continue
        if position + 4 > len(data):
            raise ValueError("truncated Base32 token")
        marker, length, size = data[position + 1:position + 4]
        if marker not in {MARKER_UPPER, MARKER_LOWER} or position + 4 + size > len(data):
            raise ValueError("invalid Base32 token")
        token = base64.b32encode(data[position + 4:position + 4 + size]).rstrip(b"=")
        if len(token) != length:
            raise ValueError("Base32 length mismatch")
        output.extend(token if marker == MARKER_UPPER else token.lower())
        position += 4 + size
    return bytes(output)


def deflate(data: bytes, dictionary: bool) -> bytes:
    kwargs = {"level": 9, "method": zlib.DEFLATED, "wbits": -15, "memLevel": 9}
    if dictionary:
        kwargs["zdict"] = STATIC_URL_DICTIONARY
    compressor = zlib.compressobj(**kwargs)
    return compressor.compress(data) + compressor.flush()


def payload_length(stream: bytes, method: int) -> int:
    number = int.from_bytes(b"\x01" + bytes((15, method)) + stream, "big")
    number = (number << 1) | 1
    count = 0
    while number:
        number = (number - 1) // len(ASCII_ALPHABET)
        count += 1
    return count


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    totals = Counter()
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    for (url,) in rows:
        raw = url.encode("utf-8")
        packed = transform(raw)
        stream = semantic_transform(packed, opaque_tokens=True)
        if inverse(semantic_inverse(stream)) != raw:
            raise AssertionError("base32 round trip failed")
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        candidate = min(payload_length(deflate(stream, dictionary=False), 0), payload_length(deflate(stream, dictionary=True), 1))
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["best_symbols"] += min(existing, candidate)
        if packed != raw:
            totals["urls_with_base32_tokens"] += 1
        if candidate < existing:
            totals["wins"] += 1
            totals["saved_symbols"] += existing - candidate
    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "training": "not required", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
