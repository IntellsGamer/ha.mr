#!/usr/bin/env python3
"""Measure compact future adaptive frame headers with no redundant sentinel.

Existing adaptive frames start with ``0x01 | version | ...``. Since a newly
allocated version byte is itself nonzero, future frames can begin directly with
that version. They remain unambiguous because legacy adaptive frames always
start with 0x01, while compact frames use versions >= 16. This reclaims eight
bits from every matching candidate, independent of the destination domain.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import (  # noqa: E402
    ASCII_ALPHABET,
    _V1_METHOD_RAW,
    _V1_METHOD_STATIC,
    _deflate,
    compress_adaptive,
    payload_symbol_count,
)
from ha_mr.diverse_phrases import transform as diverse_phrase_transform  # noqa: E402
from ha_mr.factorized_grammar import candidates as factorized_candidates  # noqa: E402
from ha_mr.general_phrases import transform as general_phrase_transform  # noqa: E402
from ha_mr.host_transform import transform as host_transform  # noqa: E402
from ha_mr.service_grammar import candidates as service_candidates  # noqa: E402
from ha_mr.semantic import transform as semantic_transform  # noqa: E402
from ha_mr.youtube_direct import pack_url as pack_youtube_url  # noqa: E402

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "compact_frame_experiment.json"
MODULUS = 101


def symbols(raw_frame: bytes) -> int:
    number = (int.from_bytes(raw_frame, "big") << 1) | 1
    count = 0
    while number:
        number = (number - 1) // len(ASCII_ALPHABET)
        count += 1
    return count


def compressed_candidates(raw: bytes, url: str) -> dict[str, int]:
    output: dict[str, int] = {}
    semantic = semantic_transform(raw, opaque_tokens=True)
    for method in (_V1_METHOD_RAW, _V1_METHOD_STATIC):
        output[f"v16_raw_{method}"] = symbols(bytes((16, method)) + _deflate(raw, method))
        output[f"v16_semantic_{method}"] = symbols(bytes((16, 2 + method)) + _deflate(semantic, method))
        host = host_transform(raw)
        if host != semantic:
            output[f"v16_host_{method}"] = symbols(bytes((16, 4 + method)) + _deflate(host, method))

    for prefix_index, suffix in service_candidates(raw):
        for method in (_V1_METHOD_RAW, _V1_METHOD_STATIC):
            output[f"v18_service_{prefix_index}_{method}"] = symbols(bytes((18, method, prefix_index)) + _deflate(suffix, method))

    for host_index, path_index, suffix in factorized_candidates(raw):
        suffix_semantic = semantic_transform(suffix, opaque_tokens=True)
        for method in (_V1_METHOD_RAW, _V1_METHOD_STATIC):
            output[f"v17_factorized_{host_index}_{path_index}_{method}"] = symbols(
                bytes((17, method, host_index, path_index)) + _deflate(suffix_semantic, method)
            )

    phrase = semantic_transform(general_phrase_transform(raw), opaque_tokens=True)
    for method in (_V1_METHOD_RAW, _V1_METHOD_STATIC):
        output[f"v20_phrase_{method}"] = symbols(bytes((20, method)) + _deflate(phrase, method))

    diverse = semantic_transform(diverse_phrase_transform(raw), opaque_tokens=True)
    for method in (_V1_METHOD_RAW, _V1_METHOD_STATIC):
        output[f"v21_diverse_{method}"] = symbols(bytes((21, method)) + _deflate(diverse, method))

    direct = pack_youtube_url(url)
    if direct is not None:
        output["v19_direct"] = symbols(bytes((19,)) + direct)
    return output


def frame_family(name: str) -> str:
    return name.split("_", 2)[0]


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    totals = Counter()
    by_family: dict[str, Counter[str]] = defaultdict_counter()
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    for (url,) in rows:
        raw = url.encode("utf-8")
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        candidates = compressed_candidates(raw, url)
        name, candidate = min(candidates.items(), key=lambda item: item[1])
        family = frame_family(name)
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        totals["best_symbols"] += min(existing, candidate)
        if candidate < existing:
            totals["wins"] += 1
            totals["saved_symbols"] += existing - candidate
            by_family[family]["wins"] += 1
            by_family[family]["saved_symbols"] += existing - candidate
    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "training": "not required; existing frozen tables only", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "totals": dict(totals),
        "by_compact_frame_family": {name: dict(values) for name, values in by_family.items()},
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


def defaultdict_counter() -> dict[str, Counter[str]]:
    from collections import defaultdict

    return defaultdict(Counter)


if __name__ == "__main__":
    main()
