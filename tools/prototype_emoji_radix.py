#!/usr/bin/env python3
"""Measure a 2,048-symbol single-code-point emoji transport proposal."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import EMOJI_ALPHABET, _string_to_number, compress_adaptive, payload_symbol_count  # noqa: E402

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "emoji_radix_experiment.json"
MODULUS = 101
EMOJI_V2_ALPHABET = tuple(chr(0x1F300 + offset) for offset in range(2048))
MARKER = "〆"


def encode(number: int) -> str:
    output = ""
    base = len(EMOJI_V2_ALPHABET)
    while number:
        number -= 1
        output += EMOJI_V2_ALPHABET[number % base]
        number //= base
    return MARKER + output


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    totals = Counter()
    failures = 0
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    for (url,) in rows:
        current = compress_adaptive(url, EMOJI_ALPHABET)
        try:
            number = _string_to_number(current, EMOJI_ALPHABET)
        except ValueError:
            failures += 1
            continue
        proposed = encode(number)
        current_symbols = payload_symbol_count(current, EMOJI_ALPHABET)
        proposed_symbols = len(proposed)
        totals["urls"] += 1
        totals["current_emoji_symbols"] += current_symbols
        totals["proposed_symbols_upper_bound"] += proposed_symbols
        if proposed_symbols < current_symbols:
            totals["wins"] += 1
            totals["saved_symbols"] += current_symbols - proposed_symbols
    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "transport": {"current_legacy_alphabet_symbols": len(EMOJI_ALPHABET), "proposed_radix": len(EMOJI_V2_ALPHABET), "marker_overhead_symbols": 1},
        "parse_failures": failures,
        "note": "A full implementation must use this single-code-point alphabet for all newly emitted payloads; this measurement conservatively re-encodes the current winning integer.",
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
