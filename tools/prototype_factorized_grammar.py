#!/usr/bin/env python3
"""Evaluate a general compositional host/path-prefix frame.

A single 255-entry service-prefix table captures frequent complete prefixes but
cannot represent the cross-product of common hosts and common path grammars.
This prototype uses two independent frozen 255-entry tables, two byte indices,
and a semantic-DEFLATE suffix. No URL database is used at decode time.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import zlib
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, STATIC_URL_DICTIONARY, compress_adaptive, payload_symbol_count  # noqa: E402
from ha_mr.semantic import inverse as semantic_inverse
from ha_mr.semantic import transform as semantic_transform

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "factorized_grammar_experiment.json"
MODULUS = 101
MAX_ITEMS = 255
DELIMITERS = b"/?&=.#-_"


def split_host(raw: bytes) -> tuple[bytes, bytes] | None:
    try:
        parts = urlsplit(raw.decode("utf-8"))
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    host = f"{parts.scheme}://{parts.netloc}".encode("utf-8")
    return host, raw[len(host):]


def path_prefixes(remainder: bytes) -> set[bytes]:
    bounds = [0] + [index + 1 for index, value in enumerate(remainder) if value in DELIMITERS] + [len(remainder)]
    output: set[bytes] = set()
    for left_index, left in enumerate(bounds[:-1]):
        if left_index > 0:
            break
        for right in bounds[left_index + 1:left_index + 6]:
            prefix = remainder[left:right]
            if 2 <= len(prefix) <= 96:
                output.add(prefix)
    return output


def ranked_table(counts: Counter[bytes]) -> list[bytes]:
    ranked = sorted(
        ((item, count, (len(item) - 2) * count) for item, count in counts.items() if count >= 3),
        key=lambda item: (item[2], item[1], len(item[0]), item[0]),
        reverse=True,
    )
    return [item for item, _count, _score in ranked[:MAX_ITEMS]]


def deflate(data: bytes, dictionary: bool) -> bytes:
    kwargs = {"level": 9, "method": zlib.DEFLATED, "wbits": -15, "memLevel": 9}
    if dictionary:
        kwargs["zdict"] = STATIC_URL_DICTIONARY
    compressor = zlib.compressobj(**kwargs)
    return compressor.compress(data) + compressor.flush()


def frame_symbols(host_index: int, path_index: int, stream: bytes, method: int) -> int:
    number = int.from_bytes(b"\x01" + bytes((11, method, host_index, path_index)) + stream, "big")
    number = (number << 1) | 1
    symbols = 0
    while number:
        number = (number - 1) // len(ASCII_ALPHABET)
        symbols += 1
    return symbols


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    host_counts: Counter[bytes] = Counter()
    path_counts: Counter[bytes] = Counter()
    for (url,) in connection.execute("SELECT outbound_link FROM links WHERE (id % 2) = 1 AND outbound_link LIKE 'http%'"):
        split = split_host(url.encode("utf-8"))
        if split is None:
            continue
        host, remainder = split
        host_counts[host] += 1
        path_counts.update(path_prefixes(remainder))
    hosts = ranked_table(host_counts)
    paths = ranked_table(path_counts)
    host_lookup = {item: index for index, item in enumerate(hosts)}
    paths_longest = sorted(enumerate(paths), key=lambda item: len(item[1]), reverse=True)

    totals = Counter()
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    for (url,) in rows:
        raw = url.encode("utf-8")
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        split = split_host(raw)
        candidate: int | None = None
        if split is not None:
            host, remainder = split
            host_index = host_lookup.get(host)
            matched_path = next(((index, prefix) for index, prefix in paths_longest if remainder.startswith(prefix)), None)
            if host_index is not None and matched_path is not None:
                path_index, prefix = matched_path
                suffix = semantic_transform(remainder[len(prefix):], opaque_tokens=True)
                if semantic_inverse(suffix) != remainder[len(prefix):]:
                    raise AssertionError("suffix semantic round trip failed")
                candidate = min(
                    frame_symbols(host_index, path_index, deflate(suffix, dictionary=False), 0),
                    frame_symbols(host_index, path_index, deflate(suffix, dictionary=True), 1),
                )
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["best_symbols"] += min(existing, candidate) if candidate is not None else existing
        if candidate is not None:
            totals["eligible"] += 1
        if candidate is not None and candidate < existing:
            totals["wins"] += 1
            totals["saved_symbols"] += existing - candidate
    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "training": "odd IDs", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "tables": {"hosts": len(hosts), "paths": len(paths), "host_preview": [item.decode("utf-8") for item in hosts[:30]], "path_preview": [item.decode("utf-8") for item in paths[:50]]},
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
