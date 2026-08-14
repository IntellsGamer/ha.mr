#!/usr/bin/env python3
"""Profile where the current adaptive codec still spends symbols.

The profiler uses only aggregate counts from the held-out split. It measures
which structural classes choose V0 versus custom frames and assigns each URL to
one primary residual category, guiding custom-codec design without saving links.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, adaptive_payload_version, compress_adaptive, payload_symbol_count  # noqa: E402

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "codec_residual_profile.json"
MODULUS = 101


def primary_shape(url: str) -> str:
    parts = urlsplit(url)
    path_segments = [part for part in parts.path.split("/") if part]
    query = parts.query
    if len(url) >= 300:
        return "very_long_url"
    if "%3A%2F%2F" in url or "%3a%2f%2f" in url:
        return "nested_encoded_url"
    if query and query.count("&") >= 3:
        return "multi_parameter_query"
    if query and len(query) >= 80:
        return "opaque_or_long_query"
    if len(path_segments) >= 4:
        return "deep_path"
    if parts.fragment:
        return "fragment_bearing"
    if parts.port:
        return "explicit_port"
    if len(path_segments) == 0 and not query:
        return "authority_only"
    if len(path_segments) == 1 and not query:
        return "single_path_segment"
    return "ordinary_structured"


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    by_shape: dict[str, Counter[str]] = defaultdict(Counter)
    by_version: Counter[str] = Counter()
    length_bins: dict[str, Counter[str]] = defaultdict(Counter)
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    totals = Counter()
    for (url,) in rows:
        payload = compress_adaptive(url, ASCII_ALPHABET)
        symbols = payload_symbol_count(payload, ASCII_ALPHABET)
        version = adaptive_payload_version(payload, ASCII_ALPHABET)
        shape = primary_shape(url)
        length_bin = "0_40" if len(url) <= 40 else "41_80" if len(url) <= 80 else "81_160" if len(url) <= 160 else "161_plus"
        for bucket in (totals, by_shape[shape], length_bins[length_bin]):
            bucket["urls"] += 1
            bucket["input_bytes"] += len(url.encode("utf-8"))
            bucket["payload_symbols"] += symbols
            bucket[f"frame_v{version}"] += 1
        by_version[f"v{version}"] += 1
    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "overall": dict(totals),
        "frame_distribution": dict(by_version),
        "by_primary_shape": {
            name: {
                **dict(counter),
                "mean_payload_symbols": round(counter["payload_symbols"] / counter["urls"], 3),
                "mean_input_bytes": round(counter["input_bytes"] / counter["urls"], 3),
            }
            for name, counter in sorted(by_shape.items())
        },
        "by_input_length": {
            name: {
                **dict(counter),
                "mean_payload_symbols": round(counter["payload_symbols"] / counter["urls"], 3),
                "mean_input_bytes": round(counter["input_bytes"] / counter["urls"], 3),
            }
            for name, counter in sorted(length_bins.items())
        },
        "privacy": "No individual URLs or hostnames are written to this report.",
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
