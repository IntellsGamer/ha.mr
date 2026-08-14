#!/usr/bin/env python3
"""Measure general token and phrase structure in held-out Reddit shared links.

The analysis is service-agnostic: it recognises delimiter-bounded components,
character alphabets, and repeated phrases without retaining individual URLs.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "reddit_general_segment_analysis.json"
MODULUS = 101
DELIMITERS = b":/?&=.#-_"
TOKEN_RE = re.compile(rb"[A-Za-z0-9_-]+")


def classify(token: bytes) -> str:
    if token.isdigit():
        return "decimal"
    if len(token) % 2 == 0 and all(value in b"0123456789abcdef" for value in token):
        return "hex-lower"
    if len(token) % 2 == 0 and all(value in b"0123456789ABCDEF" for value in token):
        return "hex-upper"
    if all(value in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for value in token):
        return "base64url"
    if all(value in b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" for value in token):
        return "base62"
    return "other"


def phrases(raw: bytes) -> set[bytes]:
    """Extract delimiter-bounded n-grams suitable for a generic fixed dictionary."""
    boundaries = [0] + [index + 1 for index, value in enumerate(raw) if value in DELIMITERS] + [len(raw)]
    output: set[bytes] = set()
    for start_index, start in enumerate(boundaries[:-1]):
        for end in boundaries[start_index + 1:start_index + 6]:
            phrase = raw[start:end]
            if 4 <= len(phrase) <= 96 and all(32 <= value < 127 for value in phrase):
                output.add(phrase)
    return output


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    totals = Counter()
    segment_kinds: Counter[str] = Counter()
    segment_lengths: dict[str, Counter[int]] = {}
    phrase_counts: Counter[bytes] = Counter()
    repeated_within_url = Counter()

    for (url,) in rows:
        raw = url.encode("utf-8")
        totals["urls"] += 1
        tokens = TOKEN_RE.findall(raw)
        seen = Counter(tokens)
        repeated_within_url["tokens_repeated"] += sum(count - 1 for count in seen.values() if count > 1)
        for token in tokens:
            kind = classify(token)
            segment_kinds[kind] += 1
            segment_lengths.setdefault(kind, Counter())[len(token)] += 1
        phrase_counts.update(phrases(raw))

    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "split": f"held-out even IDs where id % {MODULUS} = 0"},
        "totals": dict(totals),
        "segment_kinds": dict(segment_kinds),
        "segment_lengths": {kind: counts.most_common(40) for kind, counts in segment_lengths.items()},
        "top_delimiter_bounded_phrases": [
            {"phrase": phrase.decode("ascii", "replace"), "count": count}
            for phrase, count in phrase_counts.most_common(250)
        ],
        "repetition": dict(repeated_within_url),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
