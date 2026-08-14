#!/usr/bin/env python3
"""Classify adaptive decoding mismatches without recording individual URLs."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, adaptive_payload_version, compress_adaptive, decompress_adaptive  # noqa: E402

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "roundtrip_mismatch_analysis.json"
MODULUS = 101


def classify(source: str, decoded: str) -> str:
    source_parts = urlsplit(source)
    decoded_parts = urlsplit(decoded)
    if source_parts.scheme.lower() != decoded_parts.scheme.lower():
        return "scheme_case_or_change"
    if source_parts.hostname and decoded_parts.hostname and source_parts.hostname.lower() != decoded_parts.hostname.lower():
        return "hostname_case_or_change"
    if source_parts.path == "/" and decoded_parts.path == "":
        return "root_slash_elided"
    if source_parts.query != decoded_parts.query:
        return "query_normalized_or_reordered"
    if source_parts.fragment != decoded_parts.fragment:
        return "fragment_normalized"
    if source.rstrip() == decoded.rstrip() and source != decoded:
        return "outer_whitespace_trimmed"
    return "other_url_normalization"


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    totals = Counter()
    versions = Counter()
    categories = Counter()
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    for (url,) in rows:
        payload = compress_adaptive(url, ASCII_ALPHABET)
        decoded = decompress_adaptive(payload, ASCII_ALPHABET)
        totals["urls"] += 1
        if decoded != url:
            totals["mismatches"] += 1
            version = adaptive_payload_version(payload, ASCII_ALPHABET)
            versions[str(version)] += 1
            categories[classify(url, decoded)] += 1
    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "totals": dict(totals),
        "by_frame_version": dict(versions),
        "by_normalization_class": dict(categories),
        "privacy": "No individual URLs, destination strings, or hostnames are stored.",
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
