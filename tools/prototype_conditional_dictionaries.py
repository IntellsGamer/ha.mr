#!/usr/bin/env python3
"""Test component-aware frozen DEFLATE dictionaries on held-out Reddit links.

This does not learn a per-link dictionary. It trains three fixed dictionaries
from the odd-ID split and stores only the category selector in a future frame:
query-bearing URLs, deep paths, and all other HTTP(S) URLs.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, compress_adaptive, payload_symbol_count  # noqa: E402
from ha_mr.semantic import inverse as semantic_inverse
from ha_mr.semantic import transform as semantic_transform

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "conditional_dictionary_experiment.json"
MODULUS = 101
MAX_DICTIONARY = 32_768
DELIMITERS = b":/?&=.#-_"


def category(raw: bytes) -> str:
    if b"?" in raw:
        return "query"
    if raw.count(b"/") >= 5:
        return "deep_path"
    return "ordinary"


def fragments(raw: bytes) -> set[bytes]:
    bounds = [0] + [index + 1 for index, value in enumerate(raw) if value in DELIMITERS] + [len(raw)]
    result: set[bytes] = set()
    for left_position, left in enumerate(bounds[:-1]):
        for right in bounds[left_position + 1:left_position + 5]:
            candidate = raw[left:right]
            if 4 <= len(candidate) <= 80:
                result.add(candidate)
    return result


def make_dictionary(counts: Counter[bytes]) -> bytes:
    ranked = sorted(
        ((phrase, count, (len(phrase) - 3) * count) for phrase, count in counts.items() if count >= 2),
        key=lambda item: (item[2], item[1], len(item[0]), item[0]),
    )
    output = bytearray()
    # Zlib weights the tail most heavily, hence least useful phrases are first.
    for phrase, _count, _score in ranked:
        if len(output) + len(phrase) > MAX_DICTIONARY:
            continue
        output.extend(phrase)
    return bytes(output[-MAX_DICTIONARY:])


def deflate(data: bytes, dictionary: bytes) -> bytes:
    compressor = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15, memLevel=9, zdict=dictionary)
    return compressor.compress(data) + compressor.flush()


def payload_length(stream: bytes, category_index: int) -> int:
    # Hypothetical V10 frame: version=10, method=2+category index.
    number = int.from_bytes(b"\x01" + bytes((10, 2 + category_index)) + stream, "big")
    number = (number << 1) | 1
    digits = 0
    while number:
        number = (number - 1) // len(ASCII_ALPHABET)
        digits += 1
    return digits


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    counters: dict[str, Counter[bytes]] = defaultdict(Counter)
    for (url,) in connection.execute("SELECT outbound_link FROM links WHERE (id % 2) = 1 AND outbound_link LIKE 'http%'"):
        raw = semantic_transform(url.encode("utf-8"), opaque_tokens=True)
        counters[category(url.encode("utf-8"))].update(fragments(raw))
    dictionaries = {name: make_dictionary(counter) for name, counter in counters.items()}
    names = ("query", "deep_path", "ordinary")
    if any(not dictionaries[name] for name in names):
        raise RuntimeError("missing category dictionary")

    totals = Counter()
    category_totals: dict[str, Counter[str]] = defaultdict(Counter)
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    for (url,) in rows:
        raw = url.encode("utf-8")
        name = category(raw)
        stream = semantic_transform(raw, opaque_tokens=True)
        if semantic_inverse(stream) != raw:
            raise AssertionError("semantic round trip failed")
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        candidate = payload_length(deflate(stream, dictionaries[name]), names.index(name))
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["best_symbols"] += min(existing, candidate)
        category_totals[name]["urls"] += 1
        if candidate < existing:
            totals["wins"] += 1
            totals["saved_symbols"] += existing - candidate
            category_totals[name]["wins"] += 1
            category_totals[name]["saved_symbols"] += existing - candidate
    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "training": "odd IDs", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "dictionaries": {name: {"bytes": len(value), "phrases": len(counters[name])} for name, value in dictionaries.items()},
        "totals": dict(totals),
        "by_category": {name: dict(values) for name, values in category_totals.items()},
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
