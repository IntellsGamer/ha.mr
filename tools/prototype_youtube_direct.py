#!/usr/bin/env python3
"""Evaluate direct 66-bit YouTube watch-ID frames on held-out shared links."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, compress_adaptive, payload_symbol_count  # noqa: E402

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "youtube_direct_experiment.json"
MODULUS = 101
PREFIX = "https://www.youtube.com/watch?v="
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
INDEX = {character: value for value, character in enumerate(ALPHABET)}


def pack_id(video_id: str) -> bytes:
    if len(video_id) != 11 or any(character not in INDEX for character in video_id):
        raise ValueError("not a canonical 11-character YouTube ID")
    number = 0
    for character in video_id:
        number = number * 64 + INDEX[character]
    return number.to_bytes(9, "big")


def unpack_id(packed: bytes) -> str:
    number = int.from_bytes(packed, "big")
    output = ["A"] * 11
    for position in range(10, -1, -1):
        number, digit = divmod(number, 64)
        output[position] = ALPHABET[digit]
    return "".join(output)


def payload_length(packed_id: bytes) -> int:
    # Existing transport framing: sentinel byte | direct version 5 | 66-bit ID,
    # then the common adaptive odd low-bit marker.
    value = int.from_bytes(b"\x01\x05" + packed_id, "big")
    number = (value << 1) | 1
    count = 0
    while number:
        number = (number - 1) // len(ASCII_ALPHABET)
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
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        if url.startswith(PREFIX):
            suffix = url[len(PREFIX):]
            try:
                packed = pack_id(suffix)
            except ValueError:
                totals["youtube_noncanonical"] += 1
                totals["best_symbols"] += existing
                continue
            if unpack_id(packed) != suffix:
                raise AssertionError("direct YouTube round trip failed")
            direct = payload_length(packed)
            totals["youtube_exact_watch_urls"] += 1
            totals["youtube_existing_symbols"] += existing
            totals["youtube_direct_symbols"] += direct
            if direct < existing:
                totals["direct_wins"] += 1
                totals["saved_symbols"] += existing - direct
            totals["best_symbols"] += min(existing, direct)
        else:
            totals["best_symbols"] += existing

    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "split": f"held-out even IDs where id % {MODULUS} = 0"},
        "frame": {"prefix": PREFIX, "identifier": "11 Base64URL characters packed as 66 bits", "version": 5},
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
