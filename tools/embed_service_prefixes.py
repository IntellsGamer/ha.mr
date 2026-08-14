#!/usr/bin/env python3
"""Freeze the V4 service-prefix grammar table from Reddit training rows."""

from __future__ import annotations

import base64
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
TARGET = ROOT / "ha_mr" / "service_prefixes.py"
MAX_PREFIXES = 255
MIN_PREFIX_BYTES = 10
MAX_PREFIX_BYTES = 120
DELIMITERS = b"/:?&="


def eligible_prefixes(raw: bytes) -> set[bytes]:
    if not raw.startswith((b"http://", b"https://")):
        return set()
    result: set[bytes] = set()
    for position, byte in enumerate(raw, 1):
        if byte in DELIMITERS and MIN_PREFIX_BYTES <= position <= MAX_PREFIX_BYTES:
            prefix = raw[:position]
            if all(32 <= value < 127 for value in prefix):
                result.add(prefix)
    return result


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    counts: Counter[bytes] = Counter()
    for (url,) in connection.execute("SELECT outbound_link FROM links WHERE (id % 2) = 1 AND outbound_link LIKE 'http%'"):
        counts.update(eligible_prefixes(url.encode("utf-8")))
    ranked = [
        (prefix, count, (len(prefix) - 3) * count)
        for prefix, count in counts.items()
        if count >= 3
    ]
    ranked.sort(key=lambda item: (item[2], item[1], len(item[0]), item[0]), reverse=True)
    prefixes = [prefix for prefix, _count, _score in ranked[:MAX_PREFIXES]]
    encoded = base64.b64encode(b"\0".join(prefixes)).decode("ascii")
    wrapped = "\n".join(f'    "{encoded[index:index + 100]}"' for index in range(0, len(encoded), 100))
    TARGET.write_text(
        '"""Frozen V4 service-prefix grammar table trained from Reddit shared links."""\n\n'
        "from __future__ import annotations\n\n"
        "import base64\n\n"
        "PREFIXES = tuple(base64.b64decode(\n"
        "    (\n"
        f"{wrapped}\n"
        "    )\n"
        ").split(b\"\\0\"))\n",
        encoding="utf-8",
    )
    print(f"Wrote {TARGET.relative_to(ROOT)} with {len(prefixes)} prefixes")


if __name__ == "__main__":
    main()
