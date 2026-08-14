#!/usr/bin/env python3
"""Measure adaptive codec behavior by domain familiarity, without saving URLs."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import (  # noqa: E402
    ASCII_ALPHABET,
    CJK_ALPHABET,
    adaptive_payload_version,
    compress,
    compress_adaptive,
    decompress_adaptive,
    payload_symbol_count,
)

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "long_tail_balance_analysis.json"
MODULUS = 101


def hostname(value: str) -> str | None:
    try:
        return urlsplit(value).hostname
    except ValueError:
        return None


def bucket(training_frequency: int) -> str:
    if training_frequency == 0:
        return "unseen_in_training"
    if training_frequency <= 2:
        return "seen_1_to_2_times"
    if training_frequency <= 10:
        return "seen_3_to_10_times"
    if training_frequency <= 100:
        return "seen_11_to_100_times"
    return "seen_more_than_100_times"


def summarise(values: list[int]) -> dict[str, float | int]:
    values.sort()
    return {
        "urls": len(values),
        "mean_symbols": round(sum(values) / len(values), 3),
        "median_symbols": values[len(values) // 2],
        "p95_symbols": values[int((len(values) - 1) * 0.95)],
    }


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    training_hosts: Counter[str] = Counter()
    for (url,) in connection.execute("SELECT outbound_link FROM links WHERE (id % 2) = 1 AND outbound_link LIKE 'http%'"):
        host = hostname(url)
        if host:
            training_hosts[host] += 1

    ascii_sizes: dict[str, list[int]] = defaultdict(list)
    cjk_sizes: dict[str, list[int]] = defaultdict(list)
    versions: dict[str, Counter[int]] = defaultdict(Counter)
    legacy_delta: dict[str, list[int]] = defaultdict(list)
    totals: Counter[str] = Counter()
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    for (url,) in rows:
        host = hostname(url)
        if not host:
            continue
        group = bucket(training_hosts[host])
        ascii_payload = compress_adaptive(url, ASCII_ALPHABET)
        cjk_payload = compress_adaptive(url, CJK_ALPHABET)
        if decompress_adaptive(ascii_payload, ASCII_ALPHABET) != url:
            # V0 intentionally follows upstream URL serialization rules. Track
            # those historical normalizations instead of abandoning the whole
            # distribution analysis; non-V0 transforms remain byte-exact.
            totals["legacy_normalized_outputs"] += 1
        ascii_length = payload_symbol_count(ascii_payload, ASCII_ALPHABET)
        ascii_sizes[group].append(ascii_length)
        cjk_sizes[group].append(payload_symbol_count(cjk_payload, CJK_ALPHABET))
        versions[group][adaptive_payload_version(ascii_payload, ASCII_ALPHABET)] += 1
        try:
            legacy_delta[group].append(payload_symbol_count(compress(url, ASCII_ALPHABET), ASCII_ALPHABET) - ascii_length)
        except ValueError:
            pass

    examples = {}
    for url in (
        "https://manus.im/",
        "https://manus.im/docs/agents?mode=asgi",
        "https://rare-example.invalid/a/deep/path?with=parameters",
    ):
        ascii_payload = compress_adaptive(url, ASCII_ALPHABET)
        cjk_payload = compress_adaptive(url, CJK_ALPHABET)
        examples[url] = {
            "ascii_symbols": payload_symbol_count(ascii_payload, ASCII_ALPHABET),
            "ascii_version": adaptive_payload_version(ascii_payload, ASCII_ALPHABET),
            "cjk_symbols": payload_symbol_count(cjk_payload, CJK_ALPHABET),
            "round_trip": decompress_adaptive(ascii_payload, ASCII_ALPHABET) == url,
        }

    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "training": "odd IDs", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "examples": examples,
        "normalization": dict(totals),
        "buckets": {
            group: {
                "adaptive_ascii": summarise(values),
                "adaptive_cjk": summarise(cjk_sizes[group]),
                "ascii_frame_wins": {str(version): count for version, count in sorted(versions[group].items())},
                "mean_legacy_minus_adaptive_ascii_symbols": round(sum(legacy_delta[group]) / len(legacy_delta[group]), 3) if legacy_delta[group] else None,
            }
            for group, values in sorted(ascii_sizes.items())
        },
        "privacy": "No individual corpus URLs or hostnames are stored in this report.",
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
