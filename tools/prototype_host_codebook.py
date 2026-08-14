#!/usr/bin/env python3
"""Evaluate a frozen Reddit host codebook as a V2 semantic pretransform."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, STATIC_URL_DICTIONARY, compress_adaptive, payload_symbol_count  # noqa: E402
from ha_mr.semantic import ESC, inverse, transform

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "host_codebook_experiment.json"
MODULUS = 101
HOST_MARKER = 9
HOST_RE = re.compile(rb"^(https?://)([A-Za-z0-9.-]+)(?=[:/?#]|$)")
MAX_HOSTS = 255


def deflate(value: bytes, dictionary: bool) -> bytes:
    kwargs = {"level": 9, "method": zlib.DEFLATED, "wbits": -15, "memLevel": 9}
    if dictionary:
        kwargs["zdict"] = STATIC_URL_DICTIONARY
    compressor = zlib.compressobj(**kwargs)
    return compressor.compress(value) + compressor.flush()


def payload_length(stream: bytes, method: int) -> int:
    number = int.from_bytes(b"\x01" + bytes((2, method)) + stream, "big")
    count = 0
    while number:
        number = (number - 1) // len(ASCII_ALPHABET)
        count += 1
    return count


def host_match(raw: bytes):
    match = HOST_RE.match(raw)
    if not match:
        return None
    scheme, host = match.groups()
    if host != host.lower():
        return None
    return scheme, host, match.end()


def build_codebook(connection: sqlite3.Connection) -> tuple[dict[bytes, int], list[bytes]]:
    counts: Counter[bytes] = Counter()
    for (url,) in connection.execute("SELECT outbound_link FROM links WHERE (id % 2) = 1 AND outbound_link LIKE 'http%'"):
        match = host_match(url.encode("utf-8"))
        if match:
            counts[match[1]] += 1
    ranked = sorted(counts.items(), key=lambda item: ((len(item[0]) - 3) * item[1], item[1]), reverse=True)[:MAX_HOSTS]
    hosts = [host for host, _count in ranked]
    return {host: index for index, host in enumerate(hosts)}, hosts


def encode(raw: bytes, codebook: dict[bytes, int]) -> bytes:
    semantic = transform(raw, opaque_tokens=True)
    match = host_match(raw)
    if not match or match[1] not in codebook:
        return semantic
    scheme, host, _end = match
    # Host ASCII bytes are unchanged by semantic transform. Replace that exact
    # prefix rather than depending on an offset, preserving a following slash,
    # port, query, or fragment delimiter byte-for-byte.
    prefix = scheme + host
    if not semantic.startswith(prefix):
        return semantic
    return scheme + bytes((ESC, HOST_MARKER, codebook[host])) + semantic[len(prefix):]


def decode(value: bytes, hosts: list[bytes]) -> bytes:
    scheme = b"https://" if value.startswith(b"https://") else b"http://" if value.startswith(b"http://") else b""
    if scheme:
        position = len(scheme)
        if value[position:position + 2] == bytes((ESC, HOST_MARKER)):
            if position + 3 > len(value):
                raise ValueError("truncated host code")
            index = value[position + 2]
            value = value[:position] + hosts[index] + value[position + 3:]
    return inverse(value)


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    codebook, hosts = build_codebook(connection)
    totals = Counter()
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    for (url,) in rows:
        raw = url.encode("utf-8")
        transformed = encode(raw, codebook)
        decoded = decode(transformed, hosts)
        if decoded != raw:
            raise AssertionError({
                "raw_length": len(raw),
                "decoded_length": len(decoded),
                "raw_hex_prefix": raw[:80].hex(),
                "decoded_hex_prefix": decoded[:80].hex(),
                "transformed_hex_prefix": transformed[:80].hex(),
            })
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        candidates = {
            "existing": existing,
            "host_raw": payload_length(deflate(transformed, False), 6),
            "host_dict": payload_length(deflate(transformed, True), 7),
        }
        winner = min(candidates, key=candidates.get)
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["best_symbols"] += candidates[winner]
        totals[f"winner_{winner}"] += 1
        if winner != "existing":
            totals["new_wins"] += 1
            totals["saved_symbols"] += existing - candidates[winner]

    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "training": "odd IDs", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "codebook": {"hosts": len(hosts), "top_hosts": [host.decode("ascii") for host in hosts[:30]]},
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
