#!/usr/bin/env python3
"""Build the frozen V1 dictionary from the training half of Reddit shared links.

Only recurrent structural phrases are admitted: protocol fragments, hosts, safe
path prefixes, and query *keys*. Query values, fragments, and one-off opaque
identifiers are deliberately excluded from the static dictionary.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
OUTPUT_DIR = ROOT / ".build"
DICTIONARY_OUTPUT = OUTPUT_DIR / "reddit_v1_dictionary.bin"
REPORT_OUTPUT = ROOT / "reports" / "reddit_dictionary_training.json"
MAX_DICTIONARY_BYTES = 28_000
MIN_COUNT = 12
SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]{3,64}$")


def phrases(url: str) -> set[str]:
    """Extract reusable structure without retaining per-link values or fragments."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return set()
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return set()

    host = parts.hostname.lower().strip(".")
    if not host or len(host) > 120:
        return set()
    output = {f"{parts.scheme}://", "www.", f"{host}/", host}
    labels = host.split(".")
    if len(labels) >= 2:
        output.add(".".join(labels[-2:]))

    path_segments = [unquote(item) for item in parts.path.split("/") if item]
    safe_path = [item for item in path_segments if SAFE_SEGMENT.fullmatch(item)]
    if safe_path:
        output.add(f"/{safe_path[0]}")
        output.add(f"{host}/{safe_path[0]}")
    if len(safe_path) >= 2:
        output.add(f"/{safe_path[0]}/{safe_path[1]}")
        output.add(f"{host}/{safe_path[0]}/{safe_path[1]}")

    for pair in parts.query.split("&"):
        key = unquote(pair.split("=", 1)[0])
        if SAFE_SEGMENT.fullmatch(key):
            output.add(f"{key}=")
    return {item for item in output if 3 <= len(item.encode("utf-8")) <= 128}


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    counts: Counter[str] = Counter()
    train_rows = 0
    valid_urls = 0
    # Odd database IDs are the training half. Even IDs remain untouched for evaluation.
    cursor = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 1 ORDER BY id"
    )
    for (url,) in cursor:
        train_rows += 1
        if not url:
            continue
        extracted = phrases(url)
        if extracted:
            valid_urls += 1
            counts.update(extracted)

    candidates = [
        (phrase, count, (len(phrase.encode("utf-8")) - 2) * count)
        for phrase, count in counts.items()
        if count >= MIN_COUNT
    ]
    # zlib searches dictionary bytes from the tail, so add lower-value phrases first.
    candidates.sort(key=lambda item: (item[2], len(item[0]), item[0]))
    dictionary = bytearray()
    selected: list[tuple[str, int]] = []
    for phrase, count, _score in candidates:
        encoded = phrase.encode("utf-8")
        if encoded in dictionary or len(dictionary) + len(encoded) > MAX_DICTIONARY_BYTES:
            continue
        dictionary.extend(encoded)
        selected.append((phrase, count))

    DICTIONARY_OUTPUT.write_bytes(bytes(dictionary))
    report = {
        "source": {
            "database": str(DATABASE),
            "split": "Training rows where id % 2 = 1; evaluation rows where id % 2 = 0",
            "training_rows": train_rows,
            "urls_with_extractable_structure": valid_urls,
        },
        "dictionary": {
            "bytes": len(dictionary),
            "sha256": hashlib.sha256(dictionary).hexdigest(),
            "min_phrase_count": MIN_COUNT,
            "phrase_count": len(selected),
            "top_phrases": [
                {"phrase": phrase, "count": count}
                for phrase, count in sorted(selected, key=lambda item: item[1], reverse=True)[:100]
            ],
        },
    }
    REPORT_OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
