#!/usr/bin/env python3
"""Experiment with a purpose-built static-context arithmetic URL codec.

The model is trained only on odd-ID Reddit links. It is not a redirect table:
its frozen probability model predicts raw bytes from a URL grammar state and a
small previous-character class. A V24-like frame stores only a byte length and
an arithmetic bitstream, then competes against the existing adaptive winner.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, compress_adaptive, payload_symbol_count  # noqa: E402
from ha_mr.semantic import inverse as semantic_inverse  # noqa: E402
from ha_mr.semantic import transform as semantic_transform  # noqa: E402

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "context_arithmetic_experiment.json"
MODULUS = 101
ALPHABET = 256
TARGET_TOTAL = 16_384
MASK = 0xFFFFFFFF
TOP = 1 << 24

# Grammar states before consuming the next byte.
SCHEME, AFTER_COLON, AFTER_FIRST_SLASH, AUTHORITY, PATH, QUERY_KEY, QUERY_VALUE, FRAGMENT = range(8)
STATE_COUNT = 8


def previous_class(value: int | None) -> int:
    if value is None:
        return 0
    if 97 <= value <= 122:
        return 1 + value - 97
    if 48 <= value <= 57:
        return 27 + value - 48
    special = {ord("."): 37, ord("/"): 38, ord(":"): 39, ord("?"): 40, ord("&"): 41, ord("="): 42, ord("#"): 43, ord("%"): 44, ord("-"): 45, ord("_"): 46, ord("~"): 47}
    if value in special:
        return special[value]
    if 65 <= value <= 90:
        return 48
    return 49


CLASS_COUNT = 50


def transition(mode: int, value: int) -> int:
    if mode == SCHEME:
        return AFTER_COLON if value == ord(":") else SCHEME
    if mode == AFTER_COLON:
        return AFTER_FIRST_SLASH if value == ord("/") else AUTHORITY
    if mode == AFTER_FIRST_SLASH:
        return AUTHORITY if value == ord("/") else AUTHORITY
    if mode == AUTHORITY:
        if value == ord("/"):
            return PATH
        if value == ord("?"):
            return QUERY_KEY
        if value == ord("#"):
            return FRAGMENT
        return AUTHORITY
    if mode == PATH:
        if value == ord("?"):
            return QUERY_KEY
        if value == ord("#"):
            return FRAGMENT
        return PATH
    if mode == QUERY_KEY:
        if value == ord("="):
            return QUERY_VALUE
        if value == ord("&"):
            return QUERY_KEY
        if value == ord("#"):
            return FRAGMENT
        return QUERY_KEY
    if mode == QUERY_VALUE:
        if value == ord("&"):
            return QUERY_KEY
        if value == ord("#"):
            return FRAGMENT
        return QUERY_VALUE
    return FRAGMENT


def contexts(data: bytes, seed: bytes = b""):
    mode = SCHEME
    previous: int | None = None
    for value in seed:
        mode = transition(mode, value)
        previous = value
    for value in data:
        yield mode * CLASS_COUNT + previous_class(previous), value
        mode = transition(mode, value)
        previous = value


def train(connection: sqlite3.Connection, transform) -> list[list[int]]:
    counts = [[0] * ALPHABET for _ in range(STATE_COUNT * CLASS_COUNT)]
    for (url,) in connection.execute("SELECT outbound_link FROM links WHERE (id % 2) = 1 AND outbound_link LIKE 'http%'"):
        for context, value in contexts(transform(url.encode("utf-8"))):
            counts[context][value] += 1
    cumulative: list[list[int]] = []
    for row in counts:
        total = sum(row)
        if total == 0:
            frequencies = [1] * ALPHABET
        else:
            # A small nonzero floor makes any arbitrary HTTP(S) byte encodable.
            remaining = TARGET_TOTAL - ALPHABET
            frequencies = [1 + (count * remaining // total) for count in row]
            deficit = TARGET_TOTAL - sum(frequencies)
            if deficit > 0:
                for index in sorted(range(ALPHABET), key=row.__getitem__, reverse=True)[:deficit]:
                    frequencies[index] += 1
            elif deficit < 0:
                for index in sorted(range(ALPHABET), key=row.__getitem__, reverse=True):
                    removable = min(-deficit, frequencies[index] - 1)
                    frequencies[index] -= removable
                    deficit += removable
                    if deficit == 0:
                        break
        running = [0]
        for frequency in frequencies:
            running.append(running[-1] + frequency)
        cumulative.append(running)
    return cumulative


def encode(data: bytes, cumulative: list[list[int]], seed: bytes = b"") -> bytes:
    low, high = 0, MASK
    output = bytearray()
    for context, value in contexts(data, seed):
        table = cumulative[context]
        width = high - low + 1
        high = low + (width * table[value + 1] // table[-1]) - 1
        low = low + (width * table[value] // table[-1])
        while (low ^ high) < TOP:
            output.append(high >> 24)
            low = (low << 8) & MASK
            high = ((high << 8) | 0xFF) & MASK
    for shift in (24, 16, 8, 0):
        output.append((low >> shift) & 0xFF)
    return bytes(output)


def decode(encoded: bytes, length: int, cumulative: list[list[int]], seed: bytes = b"") -> bytes:
    if len(encoded) < 4:
        raise ValueError("truncated arithmetic stream")
    low, high = 0, MASK
    code = int.from_bytes(encoded[:4], "big")
    position = 4
    output = bytearray()
    mode = SCHEME
    previous: int | None = None
    for value in seed:
        mode = transition(mode, value)
        previous = value
    for _ in range(length):
        context = mode * CLASS_COUNT + previous_class(previous)
        table = cumulative[context]
        width = high - low + 1
        scaled = ((code - low + 1) * table[-1] - 1) // width
        value = next(index for index in range(ALPHABET) if table[index] <= scaled < table[index + 1])
        output.append(value)
        high = low + (width * table[value + 1] // table[-1]) - 1
        low = low + (width * table[value] // table[-1])
        while (low ^ high) < TOP:
            low = (low << 8) & MASK
            high = ((high << 8) | 0xFF) & MASK
            code = ((code << 8) & MASK) | (encoded[position] if position < len(encoded) else 0)
            position += 1
        mode = transition(mode, value)
        previous = value
    return bytes(output)


def varint(value: int) -> bytes:
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        output.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(output)


def symbols(frame: bytes) -> int:
    number = (int.from_bytes(frame, "big") << 1) | 1
    count = 0
    while number:
        number = (number - 1) // len(ASCII_ALPHABET)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--semantic", action="store_true", help="model the reversible semantic byte stream")
    args = parser.parse_args()
    transform = (lambda data: semantic_transform(data, opaque_tokens=True)) if args.semantic else (lambda data: data)
    inverse = semantic_inverse if args.semantic else (lambda data: data)
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    cumulative = train(connection, transform)
    totals = Counter()
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    for (url,) in rows:
        raw = url.encode("utf-8")
        modeled = transform(raw)
        stream = encode(modeled, cumulative)
        if inverse(decode(stream, len(modeled), cumulative)) != raw:
            raise AssertionError("arithmetic round trip failed")
        candidate = symbols(bytes((25 if args.semantic else 24,)) + varint(len(modeled)) + stream)
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["custom_symbols"] += candidate
        totals["best_symbols"] += min(existing, candidate)
        if candidate < existing:
            totals["wins"] += 1
            totals["saved_symbols"] += existing - candidate
    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "training": "odd IDs static grammar-context model", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "model": {"grammar_states": STATE_COUNT, "previous_character_classes": CLASS_COUNT, "contexts": STATE_COUNT * CLASS_COUNT, "alphabet_bytes": ALPHABET, "normalization_total": TARGET_TOTAL, "semantic_pretransform": args.semantic},
        "totals": dict(totals),
    }
    target = ROOT / "reports" / ("semantic_context_arithmetic_experiment.json" if args.semantic else "context_arithmetic_experiment.json")
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
