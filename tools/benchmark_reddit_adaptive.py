#!/usr/bin/env python3
"""Benchmark the implementation on a held-out Reddit shared-links split.

Training uses odd database IDs. Evaluation uses a deterministic spread of even
IDs, so neither the static dictionary nor selection rules observe the measured
links. Individual URLs are intentionally not written to the report.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import (  # noqa: E402
    ASCII_ALPHABET,
    CJK_V2_ALPHABET,
    EMOJI_ALPHABET,
    CodecError,
    compress,
    compress_adaptive,
    decompress_adaptive,
    adaptive_payload_version,
    payload_symbol_count,
)

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "reddit_adaptive_benchmark.json"
SAMPLE_MODULUS = 101


def category(url: str) -> str:
    if len(url) >= 300:
        return "long"
    if "?" in url and len(url.split("?", 1)[1]) >= 80:
        return "query-heavy"
    if url.count("/") >= 7:
        return "deep-path"
    return "ordinary"


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    rows = connection.execute(
        """
        SELECT outbound_link
        FROM links
        WHERE (id % 2) = 0
          AND (id % ?) = 0
          AND outbound_link LIKE 'http%'
        ORDER BY id
        """,
        (SAMPLE_MODULUS,),
    )

    overall: Counter[str] = Counter()
    categories: dict[str, Counter[str]] = defaultdict(Counter)
    started = time.perf_counter()
    for (url,) in rows:
        group = categories[category(url)]
        try:
            legacy = compress(url, ASCII_ALPHABET)
        except (CodecError, ValueError):
            legacy = None

        for name, alphabet in (("ascii", ASCII_ALPHABET), ("emoji", EMOJI_ALPHABET), ("cjk", CJK_V2_ALPHABET)):
            try:
                payload = compress_adaptive(url, alphabet)
                decoded = decompress_adaptive(payload, alphabet)
            except CodecError:
                for stats in (overall, group):
                    stats[f"{name}_unsupported"] += 1
                continue
            version = f"v{adaptive_payload_version(payload, alphabet)}"
            if version != "v0" and decoded != url:
                raise AssertionError("Adaptive frame failed exact round trip")
            for stats in (overall, group):
                stats[f"{name}_symbols"] += payload_symbol_count(payload, alphabet)
                stats[f"{name}_{version}_wins"] += 1
                if name == "ascii":
                    stats["urls"] += 1

        if legacy is None:
            overall["legacy_ascii_unsupported"] += 1
            group["legacy_ascii_unsupported"] += 1
        else:
            adaptive_ascii = compress_adaptive(url, ASCII_ALPHABET)
            adaptive_ascii_symbols = payload_symbol_count(adaptive_ascii, ASCII_ALPHABET)
            for stats in (overall, group):
                stats["legacy_ascii_symbols"] += len(legacy)
                stats["adaptive_ascii_symbols_on_legacy_supported"] += adaptive_ascii_symbols
                stats["adaptive_ascii_saved_symbols_on_legacy_supported"] += len(legacy) - adaptive_ascii_symbols
                version = adaptive_payload_version(adaptive_ascii, ASCII_ALPHABET)
                if version:
                    stats[f"adaptive_ascii_v{version}_wins_on_legacy_supported"] += 1

    elapsed = time.perf_counter() - started
    report = {
        "corpus": {
            "name": "smythp/reddit_links_dataset",
            "database": str(DATABASE),
            "training_split": "odd IDs (498,996 rows) used only to train static dictionary",
            "evaluation_split": f"even IDs where id % {SAMPLE_MODULUS} = 0; deterministic held-out sample",
        },
        "seconds": elapsed,
        "overall": dict(overall),
        "by_category": {name: dict(stats) for name, stats in sorted(categories.items())},
        "privacy": "No individual outbound links are persisted in this report.",
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
