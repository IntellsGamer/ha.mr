#!/usr/bin/env python3
"""Freeze the V7 general delimiter-bounded phrase table from Reddit training."""

from __future__ import annotations

import base64
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
TARGET = ROOT / "ha_mr" / "phrase_codebook.py"
MAX_PHRASES = 255
DELIMITERS = b":/?&=.#-_"


def fragments(raw: bytes) -> set[bytes]:
    boundaries = [0] + [index + 1 for index, value in enumerate(raw) if value in DELIMITERS] + [len(raw)]
    output: set[bytes] = set()
    for left_index, left in enumerate(boundaries[:-1]):
        for right in boundaries[left_index + 1:left_index + 5]:
            phrase = raw[left:right]
            if 6 <= len(phrase) <= 64 and all(32 <= value < 127 for value in phrase):
                output.add(phrase)
    return output


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    counts: Counter[bytes] = Counter()
    for (url,) in connection.execute("SELECT outbound_link FROM links WHERE (id % 2) = 1 AND outbound_link LIKE 'http%'"):
        counts.update(fragments(url.encode("utf-8")))
    ranked = [
        (phrase, count, (len(phrase) - 3) * count)
        for phrase, count in counts.items()
        if count >= 3
    ]
    ranked.sort(key=lambda item: (item[2], item[1], len(item[0]), item[0]), reverse=True)
    phrases = [phrase for phrase, _count, _score in ranked[:MAX_PHRASES]]
    encoded = base64.b64encode(b"\0".join(phrases)).decode("ascii")
    wrapped = "\n".join(f'    "{encoded[index:index + 100]}"' for index in range(0, len(encoded), 100))
    TARGET.write_text(
        '"""Frozen V7 general phrase codebook trained from Reddit shared links."""\n\n'
        "from __future__ import annotations\n\n"
        "import base64\n\n"
        "PHRASES = tuple(base64.b64decode(\n"
        "    (\n"
        f"{wrapped}\n"
        "    )\n"
        ").split(b\"\\0\"))\n",
        encoding="utf-8",
    )
    print(f"Wrote {TARGET.relative_to(ROOT)} with {len(phrases)} phrases")


if __name__ == "__main__":
    main()
