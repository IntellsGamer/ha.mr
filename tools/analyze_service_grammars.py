#!/usr/bin/env python3
"""Aggregate grammar analysis for held-out Reddit shared links.

No individual URLs are persisted. The report counts host/path/query structures
and identifier length/alphabet classes to guide self-contained grammar codecs.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "reddit_service_grammar_analysis.json"
MODULUS = 101


def classify_identifier(value: str) -> str:
    if not value:
        return "empty"
    if value.isdecimal():
        return "decimal"
    if all(character in "0123456789abcdefABCDEF" for character in value):
        return "hex"
    if all(character in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for character in value):
        return "base64url"
    if all(character.isalnum() for character in value):
        return "alnum"
    return "other"


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    hosts: Counter[str] = Counter()
    grammars: Counter[str] = Counter()
    keys_by_host: dict[str, Counter[str]] = defaultdict(Counter)
    ids_by_grammar: dict[str, Counter[str]] = defaultdict(Counter)
    identifier_lengths: dict[str, Counter[int]] = defaultdict(Counter)
    totals: Counter[str] = Counter()

    for (url,) in rows:
        try:
            parts = urlsplit(url)
        except ValueError:
            continue
        if not parts.hostname:
            continue
        host = parts.hostname.lower()
        hosts[host] += 1
        totals["urls"] += 1
        segments = [segment for segment in parts.path.split("/") if segment]
        path_prefix = "/".join(segments[:2])
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        key_prefix = "&".join(key for key, _value in pairs[:2])
        grammar = f"{host}|/{path_prefix}|?{key_prefix}"
        grammars[grammar] += 1
        for key, value in pairs:
            keys_by_host[host][key] += 1
            classification = classify_identifier(value)
            ids_by_grammar[grammar][classification] += 1
            identifier_lengths[classification][len(value)] += 1

    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "split": f"held-out even IDs where id % {MODULUS} = 0"},
        "totals": dict(totals),
        "top_hosts": hosts.most_common(100),
        "top_grammars": grammars.most_common(150),
        "top_query_keys_by_top_host": {
            host: keys_by_host[host].most_common(30)
            for host, _count in hosts.most_common(40)
            if keys_by_host[host]
        },
        "identifier_classes": {
            kind: {"total": sum(counts.values()), "lengths": counts.most_common(25)}
            for kind, counts in identifier_lengths.items()
        },
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
