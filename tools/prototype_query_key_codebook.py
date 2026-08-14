#!/usr/bin/env python3
"""Measure a general frozen query-key table against the full adaptive codec."""

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
REPORT = ROOT / "reports" / "query_key_codebook_experiment.json"
MODULUS = 101
MAX_KEYS = 255
MARKER = 12


def query_keys(raw: bytes) -> set[bytes]:
    keys: set[bytes] = set()
    position = 0
    while position < len(raw):
        separator = raw.find(b"?", position)
        ampersand = raw.find(b"&", position)
        candidates = [item for item in (separator, ampersand) if item >= 0]
        if not candidates:
            break
        start = min(candidates) + 1
        equals = raw.find(b"=", start)
        stop = min((item for item in (raw.find(b"&", start), raw.find(b"#", start)) if item >= 0), default=len(raw))
        if equals >= 0 and equals < stop:
            key = raw[start:equals]
            if 3 <= len(key) <= 64 and all(32 <= value < 127 for value in key):
                keys.add(key)
        position = start
    return keys


def build_table(connection: sqlite3.Connection) -> list[bytes]:
    counts: Counter[bytes] = Counter()
    for (url,) in connection.execute("SELECT outbound_link FROM links WHERE (id % 2) = 1 AND outbound_link LIKE 'http%'"):
        counts.update(query_keys(url.encode("utf-8")))
    ranked = sorted(
        ((key, count, (len(key) - 2) * count) for key, count in counts.items() if count >= 3),
        key=lambda item: (item[2], item[1], len(item[0]), item[0]),
        reverse=True,
    )
    return [key for key, _count, _score in ranked[:MAX_KEYS]]


def transform(data: bytes, table: list[bytes]) -> bytes:
    lookup = {key: index for index, key in enumerate(table)}
    output = bytearray()
    position = 0
    while position < len(data):
        if data[position] in b"?&":
            end = data.find(b"=", position + 1)
            stop = min((item for item in (data.find(b"&", position + 1), data.find(b"#", position + 1)) if item >= 0), default=len(data))
            if end >= 0 and end < stop:
                key = data[position + 1:end]
                index = lookup.get(key)
                if index is not None:
                    output.extend((data[position], ESC, MARKER, index))
                    position = end + 1
                    continue
        output.append(data[position])
        position += 1
    return bytes(output)


def inverse(data: bytes, table: list[bytes]) -> bytes:
    output = bytearray()
    position = 0
    while position < len(data):
        output.append(data[position])
        if data[position] in b"?&" and data[position + 1:position + 3] == bytes((ESC, MARKER)):
            if position + 4 > len(data):
                raise ValueError("truncated query key token")
            index = data[position + 3]
            output.extend(table[index])
            output.append(ord("="))
            position += 4
        else:
            position += 1
    return bytes(output)


def deflate(value: bytes, dictionary: bool) -> bytes:
    kwargs = {"level": 9, "method": zlib.DEFLATED, "wbits": -15, "memLevel": 9}
    if dictionary:
        kwargs["zdict"] = STATIC_URL_DICTIONARY
    compressor = zlib.compressobj(**kwargs)
    return compressor.compress(value) + compressor.flush()


def payload_length(stream: bytes, method: int) -> int:
    number = int.from_bytes(b"\x01" + bytes((9, method)) + stream, "big")
    number = (number << 1) | 1
    count = 0
    while number:
        number = (number - 1) // len(ASCII_ALPHABET)
        count += 1
    return count


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    table = build_table(connection)
    totals = Counter()
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    for (url,) in rows:
        raw = url.encode("utf-8")
        stream = transform(semantic_transform(raw, opaque_tokens=True), table)
        if semantic_inverse(inverse(stream, table)) != raw:
            raise AssertionError("query-key transform round trip failed")
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        candidate = min(payload_length(deflate(stream, dictionary=False), 0), payload_length(deflate(stream, dictionary=True), 1))
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["best_symbols"] += min(existing, candidate)
        if candidate < existing:
            totals["wins"] += 1
            totals["saved_symbols"] += existing - candidate

    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "training": "odd IDs", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "table": {"keys": len(table), "preview": [key.decode("ascii") for key in table[:100]]},
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
