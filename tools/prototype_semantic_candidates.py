#!/usr/bin/env python3
"""Evaluate reversible semantic pre-transforms before V2 implementation.

The transforms operate on the URL's UTF-8 bytes before raw DEFLATE. They are
self-contained and versionable: no shared per-link state, lookup service, or
corpus database is required for decoding. The report stores aggregate results
only.
"""

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

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "semantic_candidate_experiment.json"
MODULUS = 101
ESC = 0xFF
LITERAL = 0
PERCENT_7F = 1
DECIMAL = 2
HEX_LOWER = 3
HEX_UPPER = 4
UUID_LOWER = 5
UUID_UPPER = 6
BASE64URL = 7
BASE62 = 8
BASE62_ALPHABET = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE62_INDEX = {value: index for index, value in enumerate(BASE62_ALPHABET)}

DECIMAL_RE = re.compile(rb"(?<![A-Za-z0-9])[0-9]{7,}(?![A-Za-z0-9])")
HEX_RE = re.compile(rb"(?<![A-Za-z0-9])[0-9A-Fa-f]{12,}(?![A-Za-z0-9])")
UUID_RE = re.compile(rb"(?<![A-Za-z0-9])[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}(?![A-Za-z0-9])")
BASE64URL_RE = re.compile(rb"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{16,}(?![A-Za-z0-9_-])")
BASE62_RE = re.compile(rb"(?<![A-Za-z0-9])[A-Za-z0-9]{18,}(?![A-Za-z0-9])")


def deflate(value: bytes, *, dictionary: bool) -> bytes:
    kwargs = {"level": 9, "method": zlib.DEFLATED, "wbits": -15, "memLevel": 9}
    if dictionary:
        kwargs["zdict"] = STATIC_URL_DICTIONARY
    compressor = zlib.compressobj(**kwargs)
    return compressor.compress(value) + compressor.flush()


def transport_length(frame: bytes) -> int:
    number = int.from_bytes(b"\x01" + frame, "big")
    base = len(ASCII_ALPHABET)
    count = 0
    while number:
        number = (number - 1) // base
        count += 1
    return count


def candidate_length(stream: bytes, method: int) -> int:
    # Reserve version=2 and a method byte so this is a real frame cost.
    return transport_length(bytes((2, method)) + stream)


def is_boundary(data: bytes, start: int, end: int) -> bool:
    left = data[start - 1] if start else None
    right = data[end] if end < len(data) else None
    return (left is None or not chr(left).isalnum()) and (right is None or not chr(right).isalnum())


def encode_base62(value: bytes) -> bytes:
    number = 0
    for byte in value:
        number = number * 62 + BASE62_INDEX[byte]
    if number == 0:
        return b"\x00"
    return number.to_bytes((number.bit_length() + 7) // 8, "big")


def decode_base62(value: bytes, length: int) -> bytes:
    number = int.from_bytes(value, "big")
    output = bytearray()
    while number:
        number, digit = divmod(number, 62)
        output.append(BASE62_ALPHABET[digit])
    if not output:
        output.append(BASE62_ALPHABET[0])
    return bytes(reversed(output)).rjust(length, bytes((BASE62_ALPHABET[0],)))


def emit_literal(output: bytearray, value: int) -> None:
    if value >= 0x80 or value == ESC:
        output.extend((ESC, LITERAL, value))
    else:
        output.append(value)


def try_base64url(token: bytes) -> bytes | None:
    if len(token) % 4 == 1:
        return None
    try:
        decoded = __import__("base64").urlsafe_b64decode(token + b"=" * ((4 - len(token) % 4) % 4))
        reencoded = __import__("base64").urlsafe_b64encode(decoded).rstrip(b"=")
    except Exception:
        return None
    return decoded if reencoded == token else None


def transform(data: bytes, *, opaque: bool) -> bytes:
    output = bytearray()
    position = 0
    while position < len(data):
        # Percent escapes become a single high-bit byte when their spelling is
        # canonical uppercase. This is particularly useful for nested shared URLs.
        if position + 3 <= len(data) and data[position] == ord("%"):
            pair = data[position + 1:position + 3]
            if pair == pair.upper() and all(byte in b"0123456789ABCDEF" for byte in pair):
                value = int(pair, 16)
                if value < 0x7F:
                    output.append(0x80 | value)
                    position += 3
                    continue
                if value == 0x7F:
                    output.extend((ESC, PERCENT_7F, value))
                    position += 3
                    continue

        match = UUID_RE.match(data, position)
        if match and is_boundary(data, position, match.end()):
            token = match.group(0)
            compact = token.replace(b"-", b"")
            marker = UUID_LOWER if token == token.lower() else UUID_UPPER if token == token.upper() else None
            if marker is not None:
                output.extend((ESC, marker))
                output.extend(bytes.fromhex(compact.decode("ascii")))
                position = match.end()
                continue

        match = DECIMAL_RE.match(data, position)
        if match and is_boundary(data, position, match.end()):
            token = match.group(0)
            number = int(token)
            packed = number.to_bytes((number.bit_length() + 7) // 8, "big")
            if len(token) > len(packed) + 4 and len(token) < 256 and len(packed) < 256:
                output.extend((ESC, DECIMAL, len(token), len(packed)))
                output.extend(packed)
                position = match.end()
                continue

        match = HEX_RE.match(data, position)
        if match and is_boundary(data, position, match.end()):
            token = match.group(0)
            marker = HEX_LOWER if token == token.lower() else HEX_UPPER if token == token.upper() else None
            if marker is not None and len(token) % 2 == 0 and len(token) < 256:
                packed = bytes.fromhex(token.decode("ascii"))
                if len(token) > len(packed) + 3:
                    output.extend((ESC, marker, len(token)))
                    output.extend(packed)
                    position = match.end()
                    continue

        if opaque:
            match = BASE64URL_RE.match(data, position)
            if match and is_boundary(data, position, match.end()) and len(match.group(0)) < 256:
                token = match.group(0)
                packed = try_base64url(token)
                if packed is not None and len(token) > len(packed) + 4 and len(packed) < 256:
                    output.extend((ESC, BASE64URL, len(token), len(packed)))
                    output.extend(packed)
                    position = match.end()
                    continue

            match = BASE62_RE.match(data, position)
            if match and is_boundary(data, position, match.end()) and len(match.group(0)) < 256:
                token = match.group(0)
                packed = encode_base62(token)
                if len(token) > len(packed) + 4 and len(packed) < 256:
                    output.extend((ESC, BASE62, len(token), len(packed)))
                    output.extend(packed)
                    position = match.end()
                    continue

        emit_literal(output, data[position])
        position += 1
    return bytes(output)


def inverse(data: bytes) -> bytes:
    output = bytearray()
    position = 0
    while position < len(data):
        value = data[position]
        position += 1
        if value < 0x80:
            output.append(value)
            continue
        if value < ESC:
            output.extend(f"%{value & 0x7F:02X}".encode("ascii"))
            continue
        if position >= len(data):
            raise ValueError("truncated semantic stream")
        marker = data[position]
        position += 1
        if marker == LITERAL:
            output.append(data[position])
            position += 1
        elif marker == PERCENT_7F:
            output.extend(b"%7F")
            position += 1
        elif marker == DECIMAL:
            digits, size = data[position], data[position + 1]
            position += 2
            number = int.from_bytes(data[position:position + size], "big")
            position += size
            output.extend(str(number).zfill(digits).encode("ascii"))
        elif marker in {HEX_LOWER, HEX_UPPER}:
            length = data[position]
            position += 1
            size = length // 2
            token = data[position:position + size].hex()
            position += size
            output.extend((token.upper() if marker == HEX_UPPER else token).encode("ascii"))
        elif marker in {UUID_LOWER, UUID_UPPER}:
            token = data[position:position + 16].hex()
            position += 16
            token = f"{token[:8]}-{token[8:12]}-{token[12:16]}-{token[16:20]}-{token[20:]}"
            output.extend((token.upper() if marker == UUID_UPPER else token).encode("ascii"))
        elif marker == BASE64URL:
            length, size = data[position], data[position + 1]
            position += 2
            token = __import__("base64").urlsafe_b64encode(data[position:position + size]).rstrip(b"=")
            position += size
            if len(token) != length:
                raise ValueError("base64 length mismatch")
            output.extend(token)
        elif marker == BASE62:
            length, size = data[position], data[position + 1]
            position += 2
            output.extend(decode_base62(data[position:position + size], length))
            position += size
        else:
            raise ValueError(f"unknown semantic marker {marker}")
    return bytes(output)


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    cursor = connection.execute(
        """
        SELECT outbound_link FROM links
        WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%'
        ORDER BY id
        """,
        (MODULUS,),
    )
    totals = Counter()
    for (url,) in cursor:
        raw = url.encode("utf-8")
        structural = transform(raw, opaque=False)
        opaque = transform(raw, opaque=True)
        if inverse(structural) != raw or inverse(opaque) != raw:
            raise AssertionError("semantic transform failed round trip")

        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        candidates = {
            "existing": existing,
            "semantic_raw": candidate_length(deflate(structural, dictionary=False), 2),
            "semantic_dict": candidate_length(deflate(structural, dictionary=True), 3),
            "opaque_raw": candidate_length(deflate(opaque, dictionary=False), 4),
            "opaque_dict": candidate_length(deflate(opaque, dictionary=True), 5),
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
        "corpus": {"source": "smythp/reddit_links_dataset", "split": f"held-out even IDs where id % {MODULUS} = 0"},
        "candidates": {
            "semantic": "canonical uppercase percent escapes, long decimals, homogeneous-case hex, and UUIDs",
            "opaque": "semantic transform plus canonical Base64URL and Base62 opaque-token packing",
        },
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
