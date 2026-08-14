#!/usr/bin/env python3
"""Evaluate self-contained Brotli candidates on held-out Reddit shared links."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import brotli

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, compress_adaptive, payload_symbol_count  # noqa: E402
from ha_mr.semantic import inverse, transform

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "brotli_candidate_experiment.json"
MODULUS = 101


def payload_length(stream: bytes, method: int) -> int:
    # Frame cost: sentinel + V3 + method. V3 is reserved only if this wins.
    number = int.from_bytes(b"\x01" + bytes((3, method)) + stream, "big")
    base = len(ASCII_ALPHABET)
    count = 0
    while number:
        number = (number - 1) // base
        count += 1
    return count


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    totals = Counter()
    for (url,) in rows:
        raw = url.encode("utf-8")
        semantic = transform(raw, opaque_tokens=True)
        if inverse(semantic) != raw:
            raise AssertionError("semantic round trip failed")
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        candidates = {
            "existing": existing,
            "brotli_raw": payload_length(brotli.compress(raw, quality=11, lgwin=20), 0),
            "brotli_semantic": payload_length(brotli.compress(semantic, quality=11, lgwin=20), 1),
        }
        winner = min(candidates, key=candidates.get)
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["best_symbols"] += candidates[winner]
        totals[f"winner_{winner}"] += 1
        if winner != "existing":
            totals["new_wins"] += 1
            totals["saved_symbols"] += existing - candidates[winner]

    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "split": f"held-out even IDs where id % {MODULUS} = 0"},
        "settings": {"quality": 11, "lgwin": 20},
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
