#!/usr/bin/env python3
"""Benchmark the implemented adaptive codec on real URLs with round-trip checks."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import (  # noqa: E402
    ASCII_ALPHABET,
    CJK_ALPHABET,
    EMOJI_ALPHABET,
    CodecError,
    payload_symbol_count,
    compress,
    compress_adaptive,
    decompress_adaptive,
    is_v1_payload,
)

DATASET = Path("/home/ubuntu/ha-mr-url-dataset/out.txt")
REPORT = ROOT / "reports" / "adaptive_v1_real_urls.json"
SAMPLE_SIZE = 5_000


def category(url: str) -> str:
    if len(url) >= 300:
        return "long"
    if "?" in url and len(url.split("?", 1)[1]) >= 80:
        return "query-heavy"
    if url.count("/") >= 7:
        return "deep-path"
    return "ordinary"


def main() -> None:
    urls = [line.strip() for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    sample = urls[::20][:SAMPLE_SIZE]
    totals: Counter[str] = Counter()
    groups: dict[str, Counter] = defaultdict(Counter)
    improvements: list[dict[str, object]] = []

    for url in sample:
        category_stats = groups[category(url)]
        try:
            v0_ascii = compress(url, ASCII_ALPHABET)
        except (CodecError, ValueError):
            v0_ascii = None

        for transport, alphabet in (("ascii", ASCII_ALPHABET), ("emoji", EMOJI_ALPHABET), ("cjk", CJK_ALPHABET)):
            payload = compress_adaptive(url, alphabet)
            decoded = decompress_adaptive(payload, alphabet)
            frame = "v1" if is_v1_payload(payload, alphabet) else "v0"
            # V0 intentionally canonicalises URL spellings such as trailing root
            # slashes. V1 is byte-lossless and must reproduce the input exactly.
            if frame == "v1" and decoded != url:
                raise AssertionError(f"V1 round-trip mismatch for {transport}: {url}")
            length = payload_symbol_count(payload, alphabet)
            for stats in (totals, category_stats):
                stats[f"{transport}_symbols"] += length
                stats[f"{transport}_{frame}_wins"] += 1
                stats["urls"] += 1 if transport == "ascii" else 0

        if v0_ascii is None:
            totals["v0_unsupported"] += 1
        else:
            adaptive_ascii = compress_adaptive(url, ASCII_ALPHABET)
            saved = len(v0_ascii) - payload_symbol_count(adaptive_ascii, ASCII_ALPHABET)
            totals["v0_ascii_symbols"] += len(v0_ascii)
            if saved > 0:
                improvements.append({
                    "url": url,
                    "v0_symbols": len(v0_ascii),
                    "adaptive_symbols": payload_symbol_count(adaptive_ascii, ASCII_ALPHABET),
                    "saved_symbols": saved,
                    "category": category(url),
                })

    report = {
        "dataset": {
            "source": str(DATASET),
            "selection": "Every twentieth URL from index zero; deterministic sample",
            "sample_size": len(sample),
        },
        "overall": dict(totals),
        "by_category": {name: dict(stats) for name, stats in sorted(groups.items())},
        "largest_ascii_v1_improvements": sorted(improvements, key=lambda row: row["saved_symbols"], reverse=True)[:25],
    }
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
