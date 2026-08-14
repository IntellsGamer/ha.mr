#!/usr/bin/env python3
"""Measure compact tokens for percent-encoded nested HTTP(S) URL prefixes.

The transform is domain-neutral: wherever a literal encoded ``https://`` or
``http://`` begins inside a URL, it replaces only that exact reversible byte
sequence before semantic packing and DEFLATE. This is useful for redirects,
share links, callback URLs, and embedded destinations across arbitrary hosts.
"""

from __future__ import annotations

import json
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
REPORT = ROOT / "reports" / "percent_protocol_token_experiment.json"
MODULUS = 101
HTTPS = b"https%3A%2F%2F"
HTTP = b"http%3A%2F%2F"
HTTPS_TOKEN = 13
HTTP_TOKEN = 14


def transform(data: bytes) -> bytes:
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
    output = bytearray()
    position = 0
    while position < len(data):
        if data[position] == ESC:
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
        else:
            output.append(data[position])
            position += 1
    return bytes(output)


def deflate(data: bytes, dictionary: bool) -> bytes:
    kwargs = {"level": 9, "method": zlib.DEFLATED, "wbits": -15, "memLevel": 9}
    if dictionary:
        kwargs["zdict"] = STATIC_URL_DICTIONARY
    compressor = zlib.compressobj(**kwargs)
    return compressor.compress(data) + compressor.flush()


def payload_length(stream: bytes, method: int) -> int:
    number = int.from_bytes(b"\x01" + bytes((12, method)) + stream, "big")
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
            raise AssertionError("percent-protocol transform round trip failed")
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        candidate = min(payload_length(deflate(stream, dictionary=False), 0), payload_length(deflate(stream, dictionary=True), 1))
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["best_symbols"] += min(existing, candidate)
        if packed != raw:
            totals["urls_with_nested_encoded_protocol"] += 1
        if candidate < existing:
            totals["wins"] += 1
            totals["saved_symbols"] += existing - candidate

    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "training": "not required; transform is fixed", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "transform": {"https_token": HTTPS.decode(), "http_token": HTTP.decode()},
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
