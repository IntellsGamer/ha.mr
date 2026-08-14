#!/usr/bin/env python3
"""Test reversible binary packing for delimiter-bounded base-36 identifiers."""

from __future__ import annotations

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
REPORT = ROOT / "reports" / "base36_token_experiment.json"
MODULUS = 101
MARKER_LOWER = 16
MARKER_UPPER = 17
BASE36_LOWER = b"0123456789abcdefghijklmnopqrstuvwxyz"
BASE36_UPPER = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE36_RE = re.compile(rb"(?<![A-Za-z0-9])[0-9a-zA-Z]{9,}(?![A-Za-z0-9])")


def pack(token: bytes, alphabet: bytes) -> bytes:
    number = 0
    lookup = {value: index for index, value in enumerate(alphabet)}
    for value in token:
        number = number * 36 + lookup[value]
    return b"\x00" if number == 0 else number.to_bytes((number.bit_length() + 7) // 8, "big")


def unpack(value: bytes, length: int, alphabet: bytes) -> bytes:
    number = int.from_bytes(value, "big")
    output = bytearray()
    while number:
        number, digit = divmod(number, 36)
        output.append(alphabet[digit])
    if not output:
        output.append(alphabet[0])
    return bytes(reversed(output)).rjust(length, bytes((alphabet[0],)))


def transform(data: bytes) -> bytes:
    output = bytearray()
    position = 0
    while position < len(data):
        match = BASE36_RE.match(data, position)
        if match:
            token = match.group(0)
            if token == token.lower():
                marker, alphabet = MARKER_LOWER, BASE36_LOWER
            elif token == token.upper():
                marker, alphabet = MARKER_UPPER, BASE36_UPPER
            else:
                marker = -1
                alphabet = b""
            if marker >= 0:
                packed = pack(token, alphabet)
                if len(token) > len(packed) + 4 and len(token) < 256 and len(packed) < 256:
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
            raise ValueError("truncated base36 token")
        marker, length, size = data[position + 1:position + 4]
        if marker not in {MARKER_LOWER, MARKER_UPPER} or position + 4 + size > len(data):
            raise ValueError("invalid base36 token")
        alphabet = BASE36_LOWER if marker == MARKER_LOWER else BASE36_UPPER
        output.extend(unpack(data[position + 4:position + 4 + size], length, alphabet))
        position += 4 + size
    return bytes(output)


def deflate(data: bytes, dictionary: bool) -> bytes:
    kwargs = {"level": 9, "method": zlib.DEFLATED, "wbits": -15, "memLevel": 9}
    if dictionary:
        kwargs["zdict"] = STATIC_URL_DICTIONARY
    compressor = zlib.compressobj(**kwargs)
    return compressor.compress(data) + compressor.flush()


def payload_length(stream: bytes, method: int) -> int:
    number = int.from_bytes(b"\x01" + bytes((14, method)) + stream, "big")
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
        base36 = transform(raw)
        stream = semantic_transform(base36, opaque_tokens=True)
        if inverse(semantic_inverse(stream)) != raw:
            raise AssertionError("base36 round trip failed")
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        candidate = min(payload_length(deflate(stream, dictionary=False), 0), payload_length(deflate(stream, dictionary=True), 1))
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["best_symbols"] += min(existing, candidate)
        if base36 != raw:
            totals["urls_with_base36_tokens"] += 1
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
