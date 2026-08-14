#!/usr/bin/env python3
"""Explore adaptive candidate codecs on disjoint real-world URL samples.

The experiment deliberately preserves the existing codec as a candidate. It
trains a fixed DEFLATE dictionary on one deterministic slice of the public URL
corpus and measures it on a disjoint slice, avoiding a synthetic benchmark.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, CodecError, compress  # noqa: E402

DATASET = Path("/home/ubuntu/ha-mr-url-dataset/out.txt")
REPORT = ROOT / "reports" / "adaptive_candidate_experiment.json"
DICTIONARY = ROOT / "reports" / "v1_url_dictionary.bin"
TEST_SIZE = 5_000
MAX_DICTIONARY_BYTES = 28_000
TOKEN_SPLIT = re.compile(r"[/?&=#]+")


def base_alphabet_length(data: bytes) -> int:
    """Length of a lossless base-N payload with a sentinel to preserve zero bytes."""
    value = int.from_bytes(b"\x01" + data, "big")
    base = len(ASCII_ALPHABET)
    output_length = 0
    while value:
        value = (value - 1) // base
        output_length += 1
    return output_length


def deflate(data: bytes, dictionary: bytes | None = None) -> bytes:
    if dictionary:
        compressor = zlib.compressobj(
            level=9,
            method=zlib.DEFLATED,
            wbits=-15,
            memLevel=9,
            strategy=zlib.Z_DEFAULT_STRATEGY,
            zdict=dictionary,
        )
    else:
        compressor = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15, memLevel=9)
    return compressor.compress(data) + compressor.flush()


def train_dictionary(urls: list[str]) -> bytes:
    candidates: Counter[str] = Counter()
    for url in urls:
        # Delimiter-aware spans capture repeatable URL phrases (including query keys)
        # rather than blindly favouring individual high-frequency characters.
        parts = [part for part in TOKEN_SPLIT.split(url) if len(part) >= 4]
        for part in parts:
            limit = min(len(part), 96)
            for width in (4, 6, 8, 12, 16, 24, 32, 48):
                if width > limit:
                    continue
                for offset in range(0, limit - width + 1, max(1, width // 4)):
                    candidates[part[offset : offset + width]] += 1
        for phrase in (
            "https://", "http://", "https%3A%2F%2F", "www.", ".com/", ".org/", ".net/",
            "utm_source=", "utm_medium=", "utm_campaign=", "utm_content=", "utm_term=",
            "gclid=", "fbclid=", "_ga=", "_gac=", "ref=", "callback=", "redirect=",
            "continue=", "destination=", "google", "facebook", "youtube", "twitter",
        ):
            if phrase in url:
                candidates[phrase] += 100

    # Compression dictionaries are consulted from their end. Append weak phrases
    # first and high-value phrases last so the useful tail survives any truncation.
    ordered = sorted(
        ((key, (len(key) - 3) * count) for key, count in candidates.items() if count >= 3),
        key=lambda item: (item[1], len(item[0])),
    )
    output = bytearray()
    seen: set[str] = set()
    for phrase, _score in ordered:
        if phrase in seen or phrase.encode("utf-8") in output:
            continue
        encoded = phrase.encode("utf-8")
        if len(output) + len(encoded) > MAX_DICTIONARY_BYTES:
            continue
        output.extend(encoded)
        seen.add(phrase)
    return bytes(output[-MAX_DICTIONARY_BYTES:])


def classify(url: str) -> str:
    if len(url) >= 300:
        return "long"
    if "?" in url and len(url.split("?", 1)[1]) >= 80:
        return "query-heavy"
    if url.count("/") >= 7:
        return "deep-path"
    return "ordinary"


def main() -> None:
    urls = [line.strip() for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    train_urls = urls[1::20][:TEST_SIZE]
    test_urls = urls[::20][:TEST_SIZE]
    dictionary = train_dictionary(train_urls)
    DICTIONARY.write_bytes(dictionary)

    totals = Counter()
    by_class: dict[str, Counter] = {}
    examples: list[dict[str, object]] = []
    for url in test_urls:
        category = classify(url)
        stats = by_class.setdefault(category, Counter())
        raw_length = base_alphabet_length(deflate(url.encode("utf-8"))) + 2  # `~d` marker
        dict_length = base_alphabet_length(deflate(url.encode("utf-8"), dictionary)) + 2  # `~s` marker
        try:
            legacy_length = len(compress(url, ASCII_ALPHABET))
        except (CodecError, ValueError):
            legacy_length = None

        candidates = {"deflate": raw_length, "static_deflate": dict_length}
        if legacy_length is not None:
            candidates["legacy"] = legacy_length
        winner = min(candidates, key=candidates.get)
        for counter in (totals, stats):
            counter["urls"] += 1
            counter["legacy_supported"] += legacy_length is not None
            counter["legacy_chars"] += legacy_length or 0
            counter["deflate_chars"] += raw_length
            counter["static_deflate_chars"] += dict_length
            counter[f"winner_{winner}"] += 1
            counter["adaptive_chars"] += candidates[winner]
            if legacy_length is None:
                counter["newly_supported"] += 1
        if legacy_length is not None and dict_length < legacy_length:
            examples.append({
                "url": url,
                "category": category,
                "legacy": legacy_length,
                "static_deflate": dict_length,
                "saved_chars": legacy_length - dict_length,
            })

    report = {
        "dataset": {
            "source": str(DATASET),
            "training": "Every twentieth URL starting at index 1; deterministic disjoint slice",
            "testing": "Every twentieth URL starting at index 0; deterministic disjoint slice",
            "training_urls": len(train_urls),
            "testing_urls": len(test_urls),
        },
        "dictionary": {
            "bytes": len(dictionary),
            "sha256": __import__("hashlib").sha256(dictionary).hexdigest(),
            "base64": base64.b64encode(dictionary).decode("ascii"),
        },
        "overall": dict(totals),
        "by_class": {name: dict(counter) for name, counter in sorted(by_class.items())},
        "largest_static_deflate_wins": sorted(examples, key=lambda row: row["saved_chars"], reverse=True)[:30],
    }
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "dictionary_bytes": len(dictionary),
        "overall": report["overall"],
        "by_class": report["by_class"],
        "report": str(REPORT),
    }, indent=2))


if __name__ == "__main__":
    main()
