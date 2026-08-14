#!/usr/bin/env python3
"""Freeze the complementary V8 diversity-pruned phrase table from Reddit training."""

from __future__ import annotations

import base64
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
TARGET = ROOT / "ha_mr" / "diverse_phrase_codebook.py"
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
    candidates = [
        (phrase, count, (len(phrase) - 3) * count)
        for phrase, count in counts.items()
        if count >= 3 and not phrase.startswith((b"http", b"www.", b"//"))
    ]
    candidates.sort(key=lambda item: (item[2], item[1], len(item[0]), item[0]), reverse=True)
    selected: list[bytes] = []
    for phrase, _count, _score in candidates:
        if any(phrase in prior or prior in phrase for prior in selected):
            continue
        selected.append(phrase)
        if len(selected) == MAX_PHRASES:
            break
    encoded = base64.b64encode(b"\0".join(selected)).decode("ascii")
    wrapped = "\n".join(f'    "{encoded[index:index + 100]}"' for index in range(0, len(encoded), 100))
    TARGET.write_text(
        '"""Frozen V8 diversity-pruned general phrase table trained from Reddit links."""\n\n'
        "from __future__ import annotations\n\n"
        "import base64\n\n"
        "PHRASES = tuple(base64.b64decode(\n"
        "    (\n"
        f"{wrapped}\n"
        "    )\n"
        ").split(b\"\\0\"))\n",
        encoding="utf-8",
    )
    print(f"Wrote {TARGET.relative_to(ROOT)} with {len(selected)} phrases")


if __name__ == "__main__":
    main()
