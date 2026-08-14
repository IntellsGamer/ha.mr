#!/usr/bin/env python3
"""Evaluate a general typed-segment frame independent of any service/domain.

A URL is partitioned into runs. Each run emits one category mark, an
Elias-gamma length, and symbols in the narrowest lossless alphabet. This is a
prototype of the category-change approach: categories are URL-wide, not tied
to YouTube, Reddit, or any other service.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, compress_adaptive, payload_symbol_count  # noqa: E402

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "typed_segment_experiment.json"
MODULUS = 101
BASE64 = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
BASE64_INDEX = {value: index for index, value in enumerate(BASE64)}
HEX_LOWER = b"0123456789abcdef"
HEX_UPPER = b"0123456789ABCDEF"
PUNCT = b":/?&=.#%+;,|~!$()[]{}<>\\\"'"
PUNCT_INDEX = {value: index for index, value in enumerate(PUNCT)}

BASE64_RUN = 0
DECIMAL_RUN = 1
HEX_LOWER_RUN = 2
HEX_UPPER_RUN = 3
PUNCT_RUN = 4
ASCII_RUN = 5
RAW_RUN = 6


class BitWriter:
    def __init__(self) -> None:
        self.value = 0
        self.count = 0

    def write(self, value: int, width: int) -> None:
        self.value = (self.value << width) | value
        self.count += width

    def gamma(self, value: int) -> None:
        binary = bin(value)[2:]
        self.write(0, len(binary) - 1)
        self.write(value, len(binary))

    def bytes(self) -> tuple[bytes, int]:
        padding = (-self.count) % 8
        return (self.value << padding).to_bytes((self.count + padding) // 8, "big"), self.count


class BitReader:
    def __init__(self, data: bytes, bits: int) -> None:
        self.value = int.from_bytes(data, "big") >> (len(data) * 8 - bits)
        self.bits = bits
        self.position = 0

    def read(self, width: int) -> int:
        if self.position + width > self.bits:
            raise ValueError("truncated typed stream")
        shift = self.bits - self.position - width
        result = (self.value >> shift) & ((1 << width) - 1)
        self.position += width
        return result

    def gamma(self) -> int:
        zeros = 0
        while self.read(1) == 0:
            zeros += 1
        tail = self.read(zeros) if zeros else 0
        return (1 << zeros) | tail


def category_at(data: bytes, position: int) -> int:
    value = data[position]
    if value in PUNCT_INDEX:
        return PUNCT_RUN
    if value >= 128:
        return RAW_RUN
    # Choose a narrower number alphabet before Base64URL.
    if value in b"0123456789":
        end = position
        while end < len(data) and data[end] in b"0123456789":
            end += 1
        if end - position >= 2:
            return DECIMAL_RUN
    if value in HEX_LOWER:
        end = position
        while end < len(data) and data[end] in HEX_LOWER:
            end += 1
        if end - position >= 3:
            return HEX_LOWER_RUN
    if value in HEX_UPPER:
        end = position
        while end < len(data) and data[end] in HEX_UPPER:
            end += 1
        if end - position >= 3:
            return HEX_UPPER_RUN
    if value in BASE64_INDEX:
        return BASE64_RUN
    return ASCII_RUN


def encode(data: bytes) -> tuple[bytes, int]:
    writer = BitWriter()
    position = 0
    while position < len(data):
        category = category_at(data, position)
        end = position + 1
        while end < len(data) and category_at(data, end) == category:
            end += 1
        run = data[position:end]
        writer.write(category, 3)
        writer.gamma(len(run))
        if category == BASE64_RUN:
            for value in run:
                writer.write(BASE64_INDEX[value], 6)
        elif category == DECIMAL_RUN:
            for value in run:
                writer.write(value - ord("0"), 4)
        elif category == HEX_LOWER_RUN:
            for value in run:
                writer.write(HEX_LOWER.index(value), 4)
        elif category == HEX_UPPER_RUN:
            for value in run:
                writer.write(HEX_UPPER.index(value), 4)
        elif category == PUNCT_RUN:
            for value in run:
                writer.write(PUNCT_INDEX[value], 5)
        elif category == ASCII_RUN:
            for value in run:
                writer.write(value, 7)
        else:
            for value in run:
                writer.write(value, 8)
        position = end
    return writer.bytes()


def decode(data: bytes, bits: int) -> bytes:
    reader = BitReader(data, bits)
    output = bytearray()
    while reader.position < bits:
        category = reader.read(3)
        length = reader.gamma()
        for _ in range(length):
            if category == BASE64_RUN:
                output.append(BASE64[reader.read(6)])
            elif category == DECIMAL_RUN:
                output.append(ord("0") + reader.read(4))
            elif category == HEX_LOWER_RUN:
                output.append(HEX_LOWER[reader.read(4)])
            elif category == HEX_UPPER_RUN:
                output.append(HEX_UPPER[reader.read(4)])
            elif category == PUNCT_RUN:
                output.append(PUNCT[reader.read(5)])
            elif category == ASCII_RUN:
                output.append(reader.read(7))
            elif category == RAW_RUN:
                output.append(reader.read(8))
            else:
                raise ValueError("unknown typed-segment category")
    return bytes(output)


def transport_length(stream: bytes, bit_length: int) -> int:
    # V6 | bit-count (two bytes) | packed typed stream, then adaptive odd bit.
    if bit_length >= 65536:
        raise ValueError("typed stream too large")
    value = int.from_bytes(b"\x01\x06" + bit_length.to_bytes(2, "big") + stream, "big")
    value = (value << 1) | 1
    count = 0
    while value:
        value = (value - 1) // len(ASCII_ALPHABET)
        count += 1
    return count


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    totals = Counter()
    for (url,) in rows:
        raw = url.encode("utf-8")
        stream, bits = encode(raw)
        if decode(stream, bits) != raw:
            raise AssertionError("typed-segment round trip failed")
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        direct = transport_length(stream, bits)
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["typed_symbols"] += direct
        totals["best_symbols"] += min(existing, direct)
        if direct < existing:
            totals["typed_wins"] += 1
            totals["saved_symbols"] += existing - direct

    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "split": f"held-out even IDs where id % {MODULUS} = 0"},
        "categories": ["Base64URL", "decimal", "lower hex", "upper hex", "punctuation", "ASCII", "raw bytes"],
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
