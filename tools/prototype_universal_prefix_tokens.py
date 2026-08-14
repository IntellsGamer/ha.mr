#!/usr/bin/env python3
"""Test compact reversible tokens for universal URL starts.

Unlike a service table, these four prefixes are Internet syntax, not learned
hosts: ``http://``, ``https://``, and their ``www.`` variants. The transform
runs after semantic packing so its escape bytes do not collide with semantic
literals, and then uses the normal raw/static DEFLATE competition.
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
REPORT = ROOT / "reports" / "universal_prefix_token_experiment.json"
MODULUS = 101
PREFIXES = (b"https://www.", b"http://www.", b"https://", b"http://")
MARKER = 15


def transform(data: bytes) -> bytes:
    for index, prefix in enumerate(PREFIXES):
        if data.startswith(prefix):
            return bytes((ESC, MARKER, index)) + data[len(prefix):]
    return data


def inverse(data: bytes) -> bytes:
    if data[:2] != bytes((ESC, MARKER)):
        raise ValueError("missing universal prefix marker")
    if len(data) < 3 or data[2] >= len(PREFIXES):
        raise ValueError("invalid universal prefix marker")
    return PREFIXES[data[2]] + data[3:]


def deflate(data: bytes, dictionary: bool) -> bytes:
    kwargs = {"level": 9, "method": zlib.DEFLATED, "wbits": -15, "memLevel": 9}
    if dictionary:
        kwargs["zdict"] = STATIC_URL_DICTIONARY
    compressor = zlib.compressobj(**kwargs)
    return compressor.compress(data) + compressor.flush()


def payload_length(stream: bytes, method: int) -> int:
    number = int.from_bytes(b"\x01" + bytes((13, method)) + stream, "big")
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
        semantic = semantic_transform(raw, opaque_tokens=True)
        packed = transform(semantic)
        if semantic_inverse(inverse(packed)) != raw:
            raise AssertionError("universal-prefix transform round trip failed")
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        candidate = min(payload_length(deflate(packed, dictionary=False), 0), payload_length(deflate(packed, dictionary=True), 1))
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["best_symbols"] += min(existing, candidate)
        if candidate < existing:
            totals["wins"] += 1
            totals["saved_symbols"] += existing - candidate
    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "training": "not required except existing static dictionary", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "prefixes": [prefix.decode() for prefix in PREFIXES],
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
