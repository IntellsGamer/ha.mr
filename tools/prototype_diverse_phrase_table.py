#!/usr/bin/env python3
"""Compare a diversity-pruned generic phrase table against the current table.

The current V7 table is frequency-ranked and therefore contains overlapping
scheme/host fragments. This experiment reserves its finite 255 entries for
non-overlapping delimiter-bounded path and query structures that generalise
across hosts and services.
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
REPORT = ROOT / "reports" / "diverse_phrase_table_experiment.json"
MODULUS = 101
MAX_PHRASES = 255
MARKER = 10
DELIMITERS = b":/?&=.#-_"


def fragments(raw: bytes) -> set[bytes]:
    boundaries = [0] + [index + 1 for index, value in enumerate(raw) if value in DELIMITERS] + [len(raw)]
    output: set[bytes] = set()
    for left_index, left in enumerate(boundaries[:-1]):
        for right in boundaries[left_index + 1:left_index + 5]:
            phrase = raw[left:right]
            if 6 <= len(phrase) <= 64 and all(32 <= value < 127 for value in phrase):
                output.add(phrase)
    return output


def build_table(connection: sqlite3.Connection) -> list[bytes]:
    counts: Counter[bytes] = Counter()
    for (url,) in connection.execute("SELECT outbound_link FROM links WHERE (id % 2) = 1 AND outbound_link LIKE 'http%'"):
        counts.update(fragments(url.encode("utf-8")))
    candidates = [
        (phrase, count, (len(phrase) - 3) * count)
        for phrase, count in counts.items()
        if count >= 3 and not phrase.startswith((b"http", b"www.", b"//"))
    ]
    candidates.sort(key=lambda item: (item[2], item[1], len(item[0]), item[0]), reverse=True)
    selected: list[bytes] = []
    for phrase, _count, _score in candidates:
        if any(phrase in earlier or earlier in phrase for earlier in selected):
            continue
        selected.append(phrase)
        if len(selected) == MAX_PHRASES:
            break
    return selected


def phrase_transform(data: bytes, table: list[bytes]) -> bytes:
    ordered = sorted(enumerate(table), key=lambda item: len(item[1]), reverse=True)
    output = bytearray()
    position = 0
    while position < len(data):
        found = next(((index, phrase) for index, phrase in ordered if data.startswith(phrase, position)), None)
        if found:
            index, phrase = found
            output.extend((ESC, MARKER, index))
            position += len(phrase)
        else:
            output.append(data[position])
            position += 1
    return bytes(output)


def phrase_inverse(data: bytes, table: list[bytes]) -> bytes:
    output = bytearray()
    position = 0
    while position < len(data):
        if data[position:position + 2] == bytes((ESC, MARKER)):
            if position + 3 > len(data):
                raise ValueError("truncated phrase token")
            output.extend(table[data[position + 2]])
            position += 3
        else:
            output.append(data[position])
            position += 1
    return bytes(output)


def deflate(value: bytes, dictionary: bool) -> bytes:
    kwargs = {"level": 9, "method": zlib.DEFLATED, "wbits": -15, "memLevel": 9}
    if dictionary:
        kwargs["zdict"] = STATIC_URL_DICTIONARY
    compressor = zlib.compressobj(**kwargs)
    return compressor.compress(value) + compressor.flush()


def payload_length(stream: bytes, method: int) -> int:
    number = int.from_bytes(b"\x01" + bytes((7, method)) + stream, "big")
    number = (number << 1) | 1
    digits = 0
    while number:
        number = (number - 1) // len(ASCII_ALPHABET)
        digits += 1
    return digits


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
        encoded = semantic_transform(phrase_transform(raw, table), opaque_tokens=True)
        if phrase_inverse(semantic_inverse(encoded), table) != raw:
            raise AssertionError("diverse phrase round trip failed")
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        candidate = min(payload_length(deflate(encoded, dictionary=False), 0), payload_length(deflate(encoded, dictionary=True), 1))
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["best_symbols"] += min(existing, candidate)
        if candidate < existing:
            totals["wins"] += 1
            totals["saved_symbols"] += existing - candidate

    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "training": "odd IDs", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "table": {"phrases": len(table), "phrases_preview": [item.decode("ascii") for item in table[:100]]},
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
