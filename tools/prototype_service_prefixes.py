#!/usr/bin/env python3
"""Evaluate a frozen service-prefix grammar candidate on Reddit shared links.

A prefix table is trained on odd IDs only. An encoded V4 frame contains a
one-byte prefix index followed by a self-contained semantic transform of the
remaining suffix, then raw/static DEFLATE. No URL database is consulted during
decoding.
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
REPORT = ROOT / "reports" / "service_prefix_experiment.json"
MODULUS = 101
MAX_PREFIXES = 255
MIN_PREFIX_BYTES = 10
MAX_PREFIX_BYTES = 120
DELIMITERS = b"/:?&="


def eligible_prefixes(raw: bytes) -> set[bytes]:
    """Return delimiter-bounded ASCII prefixes that are safe to replace literally."""
    if not raw.startswith((b"http://", b"https://")):
        return set()
    result: set[bytes] = set()
    for position, byte in enumerate(raw, 1):
        if byte not in DELIMITERS or not (MIN_PREFIX_BYTES <= position <= MAX_PREFIX_BYTES):
            continue
        prefix = raw[:position]
        if all(32 <= value < 127 for value in prefix):
            result.add(prefix)
    return result


def build_table(connection: sqlite3.Connection) -> list[bytes]:
    counts: Counter[bytes] = Counter()
    for (url,) in connection.execute("SELECT outbound_link FROM links WHERE (id % 2) = 1 AND outbound_link LIKE 'http%'"):
        raw = url.encode("utf-8")
        counts.update(eligible_prefixes(raw))
    ranked = [
        (prefix, count, (len(prefix) - 3) * count)
        for prefix, count in counts.items()
        if count >= 3
    ]
    ranked.sort(key=lambda item: (item[2], item[1], len(item[0]), item[0]), reverse=True)
    return [prefix for prefix, _count, _score in ranked[:MAX_PREFIXES]]


def deflate(value: bytes, *, dictionary: bool) -> bytes:
    kwargs = {"level": 9, "method": zlib.DEFLATED, "wbits": -15, "memLevel": 9}
    if dictionary:
        kwargs["zdict"] = STATIC_URL_DICTIONARY
    compressor = zlib.compressobj(**kwargs)
    return compressor.compress(value) + compressor.flush()


def frame_length(index: int, stream: bytes, method: int) -> int:
    # Version 4 | method | prefix index | DEFLATE stream; leading 1 preserves bytes.
    number = int.from_bytes(b"\x01" + bytes((4, method, index)) + stream, "big")
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
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        candidates: dict[str, int] = {"existing": existing}
        matches = [(index, prefix) for index, prefix in enumerate(table) if raw.startswith(prefix)]
        for index, prefix in matches:
            suffix = raw[len(prefix):]
            semantic = semantic_transform(suffix, opaque_tokens=True)
            if semantic_inverse(semantic) != suffix:
                raise AssertionError("semantic suffix round trip failed")
            candidates[f"service_raw_{index}"] = frame_length(index, deflate(semantic, dictionary=False), 0)
            candidates[f"service_dict_{index}"] = frame_length(index, deflate(semantic, dictionary=True), 1)
        winner = min(candidates, key=candidates.get)
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["best_symbols"] += candidates[winner]
        totals["urls_matching_prefix_table"] += bool(matches)
        if winner != "existing":
            totals["service_wins"] += 1
            totals["saved_symbols"] += existing - candidates[winner]

    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "training": "odd IDs", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "table": {"prefixes": len(table), "top_prefixes": [prefix.decode("ascii") for prefix in table[:80]]},
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
