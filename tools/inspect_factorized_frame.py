#!/usr/bin/env python3
"""Print adaptive frame choices for representative general host/path combinations."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ha_mr.codec import ASCII_ALPHABET, adaptive_payload_version, compress_adaptive, decompress_adaptive, payload_symbol_count

URLS = (
    "https://www.reddit.com/r/TranscribersOfReddit/wiki/format/images/guide",
    "https://www.reddit.com/r/AskReddit/wiki/index#rules",
    "https://en.wikipedia.org/wiki/Compression_algorithm",
    "https://github.com/GrafeasGroup/tor/issues/12345678901234567890",
    "https://www.reddit.com/r/autotldr/comments/abc123/example-post",
)

for url in URLS:
    payload = compress_adaptive(url, ASCII_ALPHABET)
    print({
        "url": url,
        "symbols": payload_symbol_count(payload, ASCII_ALPHABET),
        "version": adaptive_payload_version(payload, ASCII_ALPHABET),
        "round_trip": decompress_adaptive(payload, ASCII_ALPHABET) == url,
    })
