#!/usr/bin/env python3
"""Find V24/V26 selections among fixed public-shaped URLs only."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, adaptive_payload_version, compress_adaptive, decompress_adaptive, payload_symbol_count

URLS = (
    "https://example.com/redirect?next=https%3A%2F%2Fmanus.im%2Fdocs%3Fmode%3Dasgi",
    "https://www.reddit.com/r/AskReddit/comments/24mzcw/what_is_the_most_interesting_fact_you_know/",
    "https://www.reddit.com/r/programming/comments/abcdef/a_general_programming_discussion_with_a_long_title/",
    "https://www.reddit.com/r/python/comments/123abc/a_deep_path_for_testing_the_general_arithmetic_codec/",
    "https://github.com/example/project/issues/123?state=open&sort=created&direction=desc",
)

for url in URLS:
    payload = compress_adaptive(url, ASCII_ALPHABET)
    print({
        "version": adaptive_payload_version(payload, ASCII_ALPHABET),
        "symbols": payload_symbol_count(payload, ASCII_ALPHABET),
        "round_trip": decompress_adaptive(payload, ASCII_ALPHABET) == url,
    })
