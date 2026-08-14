#!/usr/bin/env python3
"""Inspect compact-frame selection for general and uncommon URL shapes."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, CJK_ALPHABET, adaptive_payload_version, compress, compress_adaptive, decompress_adaptive, payload_symbol_count

URLS = (
    "https://manus.im/",
    "https://manus.im/docs/agents?mode=asgi",
    "https://rare-example.invalid/a/deep/path?with=parameters",
    "https://example.com/redirect?next=https%3A%2F%2Fmanus.im%2Fdocs%3Fmode%3Dasgi",
)

for url in URLS:
    payload = compress_adaptive(url, ASCII_ALPHABET)
    cjk_payload = compress_adaptive(url, CJK_ALPHABET)
    try:
        legacy_symbols = payload_symbol_count(compress(url, ASCII_ALPHABET), ASCII_ALPHABET)
    except Exception:
        # Legacy V0 intentionally supports a narrower grammar than adaptive.
        legacy_symbols = None
    print({
        "url": url,
        "legacy_ascii_symbols": legacy_symbols,
        "adaptive_ascii_symbols": payload_symbol_count(payload, ASCII_ALPHABET),
        "adaptive_version": adaptive_payload_version(payload, ASCII_ALPHABET),
        "adaptive_cjk_symbols": payload_symbol_count(cjk_payload, CJK_ALPHABET),
        "round_trip": decompress_adaptive(payload, ASCII_ALPHABET) == url,
    })
