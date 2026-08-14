#!/usr/bin/env python3
"""Measure a backward-compatible high-radix CJK transport proposal.

The payload bytes and codec frames do not change. Existing unmarked CJK links
remain base-4096; newly marked links use 16,384 single CJK ideographs. This is
pure transport coding, works equally for common and unknown domains, and keeps
one Unicode code point per digit.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import CJK_ALPHABET, _string_to_number, compress_adaptive, payload_symbol_count  # noqa: E402

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "unicode_radix_experiment.json"
MODULUS = 101
CJK_V2_ALPHABET = tuple(chr(0x4E00 + offset) for offset in range(16_384))
MARKER = chr(0x9FFF)


def encode(number: int) -> str:
    output = ""
    base = len(CJK_V2_ALPHABET)
    while number:
        number -= 1
        output += CJK_V2_ALPHABET[number % base]
        number //= base
    return MARKER + output


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    totals = Counter()
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    for (url,) in rows:
        current = compress_adaptive(url, CJK_ALPHABET)
        number = _string_to_number(current, CJK_ALPHABET)
        proposed = encode(number)
        current_symbols = payload_symbol_count(current, CJK_ALPHABET)
        proposed_symbols = len(proposed)
        totals["urls"] += 1
        totals["current_cjk_symbols"] += current_symbols
        totals["proposed_symbols_upper_bound"] += proposed_symbols
        if proposed_symbols < current_symbols:
            totals["wins"] += 1
            totals["saved_symbols"] += current_symbols - proposed_symbols
    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "transport": {"current_radix": len(CJK_ALPHABET), "proposed_radix": len(CJK_V2_ALPHABET), "marker_overhead_symbols": 1},
        "note": "This is a conservative upper bound because it only re-encodes the current base-4096 winner; a full base-16384 adaptive search can select an equal or smaller candidate.",
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
