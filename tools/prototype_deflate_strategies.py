#!/usr/bin/env python3
"""Test alternative raw-DEFLATE strategies against the complete adaptive codec.

The candidate does not learn any hosts, paths, or services. It changes only the
DEFLATE block strategy, which can avoid the dynamic-Huffman header cost for
short and long-tail byte streams. Each candidate still carries a method byte so
its decoding remains self-contained and deterministic.
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
from ha_mr.semantic import inverse as semantic_inverse
from ha_mr.semantic import transform as semantic_transform

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "deflate_strategy_experiment.json"
MODULUS = 101
STRATEGIES = {
    "fixed_raw": (zlib.Z_FIXED, False, 2, 1),
    "fixed_static": (zlib.Z_FIXED, True, 3, 1),
    "huffman_only_raw": (zlib.Z_HUFFMAN_ONLY, False, 4, 1),
    "rle_raw": (zlib.Z_RLE, False, 5, 1),
    "fixed_semantic": (zlib.Z_FIXED, False, 2, 2),
    "fixed_semantic_static": (zlib.Z_FIXED, True, 3, 2),
}


def deflate(data: bytes, strategy: int, dictionary: bool) -> bytes:
    kwargs = {"level": 9, "method": zlib.DEFLATED, "wbits": -15, "memLevel": 9, "strategy": strategy}
    if dictionary:
        kwargs["zdict"] = STATIC_URL_DICTIONARY
    compressor = zlib.compressobj(**kwargs)
    return compressor.compress(data) + compressor.flush()


def payload_length(stream: bytes, method: int, version: int) -> int:
    number = int.from_bytes(b"\x01" + bytes((version, method)) + stream, "big")
    number = (number << 1) | 1
    count = 0
    while number:
        number = (number - 1) // len(ASCII_ALPHABET)
        count += 1
    return count


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    totals: Counter[str] = Counter()
    by_strategy: dict[str, Counter[str]] = {name: Counter() for name in STRATEGIES}
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    for (url,) in rows:
        raw = url.encode("utf-8")
        semantic = semantic_transform(raw, opaque_tokens=True)
        if semantic_inverse(semantic) != raw:
            raise AssertionError("semantic round trip failed")
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        candidates: dict[str, int] = {}
        for name, (strategy, dictionary, method, version) in STRATEGIES.items():
            source = semantic if version == 2 else raw
            candidates[name] = payload_length(deflate(source, strategy, dictionary), method, version)
        winning_name, candidate = min(candidates.items(), key=lambda item: item[1])
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["best_symbols"] += min(existing, candidate)
        if candidate < existing:
            totals["wins"] += 1
            totals["saved_symbols"] += existing - candidate
            by_strategy[winning_name]["wins"] += 1
            by_strategy[winning_name]["saved_symbols"] += existing - candidate
        for name, size in candidates.items():
            if size < existing:
                by_strategy[name]["individual_wins"] += 1
                by_strategy[name]["individual_saved_symbols"] += existing - size
    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "training": "not required except existing static dictionary", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "totals": dict(totals),
        "by_strategy": {name: dict(values) for name, values in by_strategy.items()},
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
