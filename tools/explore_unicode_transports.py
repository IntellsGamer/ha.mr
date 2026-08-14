#!/usr/bin/env python3
"""Measure visual-symbol savings from Unicode transports on real URL data.

Counts describe the user-visible payload characters. For non-ASCII fragments,
browsers may percent-encode the address-bar representation during sharing; the
application therefore treats CJK and emoji as explicit opt-in display modes.
"""

from __future__ import annotations

import json
import sys
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, EMOJI_ALPHABET, CodecError, compress  # noqa: E402

DATASET = Path("/home/ubuntu/ha-mr-url-dataset/out.txt")
DICTIONARY = ROOT / "reports" / "v1_url_dictionary.bin"
REPORT = ROOT / "reports" / "unicode_transport_experiment.json"
SAMPLE_SIZE = 5_000

# A fixed Japanese-oriented alphabet: common CJK unified ideographs. It has a
# power-of-two-sized transport radix (4096) and uses one code point per digit.
CJK_ALPHABET = tuple(chr(0x4E00 + offset) for offset in range(4096))


def packed_length(data: bytes, alphabet_size: int) -> int:
    """Count digits after v1 framing: sentinel bytes then unary-version prefix."""
    value = int.from_bytes(b"\x01" + data, "big")
    value = (value << 2) | 1  # v1: low bits are 1 then 0
    output = 0
    while value:
        value = (value - 1) // alphabet_size
        output += 1
    return output


def deflate(data: bytes, dictionary: bytes | None = None) -> bytes:
    kwargs = dict(level=9, method=zlib.DEFLATED, wbits=-15, memLevel=9)
    if dictionary:
        kwargs["zdict"] = dictionary
    compressor = zlib.compressobj(**kwargs)
    return compressor.compress(data) + compressor.flush()


def main() -> None:
    urls = [line.strip() for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    sample = urls[::20][:SAMPLE_SIZE]
    dictionary = DICTIONARY.read_bytes()
    totals: Counter[str] = Counter()
    examples: list[dict[str, object]] = []

    for url in sample:
        data = url.encode("utf-8")
        candidates = {
            "v1_raw_ascii": packed_length(b"\x00" + deflate(data), len(ASCII_ALPHABET)),
            "v1_static_ascii": packed_length(b"\x01" + deflate(data, dictionary), len(ASCII_ALPHABET)),
            "v1_raw_emoji": packed_length(b"\x00" + deflate(data), len(EMOJI_ALPHABET)),
            "v1_static_emoji": packed_length(b"\x01" + deflate(data, dictionary), len(EMOJI_ALPHABET)),
            "v1_raw_cjk": packed_length(b"\x00" + deflate(data), len(CJK_ALPHABET)),
            "v1_static_cjk": packed_length(b"\x01" + deflate(data, dictionary), len(CJK_ALPHABET)),
        }
        try:
            candidates["v0_ascii"] = len(compress(url, ASCII_ALPHABET))
            candidates["v0_emoji"] = len(compress(url, EMOJI_ALPHABET))
            candidates["v0_cjk"] = len(compress(url, CJK_ALPHABET))
        except (CodecError, ValueError):
            totals["v0_unsupported"] += 1

        winner_ascii = min((name for name in candidates if name.endswith("ascii")), key=candidates.get)
        winner_emoji = min((name for name in candidates if name.endswith("emoji")), key=candidates.get)
        winner_cjk = min((name for name in candidates if name.endswith("cjk")), key=candidates.get)
        totals["urls"] += 1
        totals["ascii_adaptive_chars"] += candidates[winner_ascii]
        totals["emoji_adaptive_chars"] += candidates[winner_emoji]
        totals["cjk_adaptive_chars"] += candidates[winner_cjk]
        totals[f"winner_{winner_ascii}"] += 1
        totals[f"winner_{winner_emoji}"] += 1
        totals[f"winner_{winner_cjk}"] += 1
        if "v0_ascii" in candidates:
            totals["v0_ascii_chars"] += candidates["v0_ascii"]
            totals["v0_emoji_chars"] += candidates["v0_emoji"]
            totals["v0_cjk_chars"] += candidates["v0_cjk"]

        if winner_cjk != "v0_cjk" and "v0_cjk" in candidates:
            examples.append({
                "url": url,
                "v0_cjk": candidates["v0_cjk"],
                "winner": winner_cjk,
                "adaptive_cjk": candidates[winner_cjk],
                "saved_symbols": candidates["v0_cjk"] - candidates[winner_cjk],
            })

    report = {
        "sample": {"source": str(DATASET), "selection": "Every twentieth URL from index zero", "size": len(sample)},
        "alphabets": {"ascii": len(ASCII_ALPHABET), "emoji": len(EMOJI_ALPHABET), "japanese_cjk": len(CJK_ALPHABET)},
        "totals": dict(totals),
        "largest_v1_cjk_wins": sorted(examples, key=lambda item: item["saved_symbols"], reverse=True)[:30],
    }
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
