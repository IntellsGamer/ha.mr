#!/usr/bin/env python3
"""Print exact self-contained payload comparisons for one supplied shared URL."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import (  # noqa: E402
    ASCII_ALPHABET,
    adaptive_payload_version,
    compress,
    compress_adaptive,
    decompress_adaptive,
    payload_symbol_count,
)

URL = "https://www.youtube.com/watch?v=Xic_cDYrtnM"


def main() -> None:
    legacy = compress(URL, ASCII_ALPHABET)
    adaptive = compress_adaptive(URL, ASCII_ALPHABET)
    print({
        "url": URL,
        "legacy_payload": legacy,
        "legacy_symbols": payload_symbol_count(legacy, ASCII_ALPHABET),
        "adaptive_payload": adaptive,
        "adaptive_symbols": payload_symbol_count(adaptive, ASCII_ALPHABET),
        "adaptive_version": adaptive_payload_version(adaptive, ASCII_ALPHABET),
        "round_trip": decompress_adaptive(adaptive, ASCII_ALPHABET),
    })


if __name__ == "__main__":
    main()
