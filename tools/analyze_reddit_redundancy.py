#!/usr/bin/env python3
"""Characterise remaining reversible redundancy in held-out shared links.

The report intentionally contains aggregate counts only; no outbound URLs or
user/comment metadata leave the local SQLite database.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "reddit_redundancy_analysis.json"
MODULUS = 101

PERCENT = re.compile(r"%([0-9A-Fa-f]{2})")
DECIMAL = re.compile(r"(?<![A-Za-z0-9])[0-9]{6,}(?![A-Za-z0-9])")
HEX = re.compile(r"(?<![A-Za-z0-9])[0-9A-Fa-f]{12,}(?![A-Za-z0-9])")
UUID = re.compile(r"(?<![A-Za-z0-9])[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}(?![A-Za-z0-9])")


def savings_for_decimal(text: str) -> int:
    # V2 decimal token: marker + digit count + base-10 integer varint.
    value = int(text)
    encoded = 2
    while value >= 128:
        value >>= 7
        encoded += 1
    return max(0, len(text) - encoded)


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    cursor = connection.execute(
        """
        SELECT outbound_link
        FROM links
        WHERE (id % 2) = 0
          AND (id % ?) = 0
          AND outbound_link LIKE 'http%'
        ORDER BY id
        """,
        (MODULUS,),
    )

    totals: Counter[str] = Counter()
    escaped_bytes: Counter[str] = Counter()
    for (url,) in cursor:
        totals["urls"] += 1
        totals["url_bytes"] += len(url.encode("utf-8"))
        matches = list(PERCENT.finditer(url))
        totals["percent_escapes"] += len(matches)
        totals["percent_escape_raw_bytes"] += len(matches) * 3
        # ASCII escapes can use one high-bit byte in a lossless byte transform.
        totals["percent_ascii_escapes"] += sum(int(match.group(1), 16) < 128 for match in matches)
        escaped_bytes.update(match.group(1).upper() for match in matches)

        decimal_runs = list(DECIMAL.finditer(url))
        totals["decimal_runs"] += len(decimal_runs)
        totals["decimal_digits"] += sum(len(match.group(0)) for match in decimal_runs)
        totals["decimal_theoretical_saved_bytes"] += sum(savings_for_decimal(match.group(0)) for match in decimal_runs)

        hex_runs = list(HEX.finditer(url))
        totals["hex_runs"] += len(hex_runs)
        totals["hex_digits"] += sum(len(match.group(0)) for match in hex_runs)
        totals["hex_theoretical_saved_bytes"] += sum(len(match.group(0)) // 2 - 2 for match in hex_runs)

        uuid_runs = list(UUID.finditer(url))
        totals["uuid_runs"] += len(uuid_runs)
        totals["uuid_theoretical_saved_bytes"] += len(uuid_runs) * (36 - 17)

        query = url.split("?", 1)
        if len(query) == 2:
            totals["urls_with_query"] += 1
            keys = [piece.split("=", 1)[0] for piece in query[1].split("&")]
            totals["query_keys"] += len(keys)
            totals["repeated_query_keys_within_url"] += len(keys) - len(set(keys))

    report = {
        "corpus": {
            "source": "smythp/reddit_links_dataset",
            "split": f"held-out even IDs where id % {MODULUS} = 0",
        },
        "totals": dict(totals),
        "top_percent_escaped_bytes": escaped_bytes.most_common(32),
        "notes": {
            "percent_transform": "ASCII %HH can be represented losslessly with one high-bit byte; non-ASCII raw bytes use an escape pair.",
            "decimal_transform": "Long isolated decimal runs are candidates for length-prefixed base-10 integer encoding.",
            "hex_transform": "Long isolated hexadecimal runs and UUIDs are candidates for length-prefixed binary packing.",
        },
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
