#!/usr/bin/env python3
"""Test frozen host/path prefix indexes plus a seeded arithmetic suffix model."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

from prototype_context_arithmetic import decode, encode, symbols, train, varint  # noqa: E402
from ha_mr.codec import ASCII_ALPHABET, compress_adaptive, payload_symbol_count  # noqa: E402
from ha_mr.factorized_grammar import candidates, inverse  # noqa: E402

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "factorized_arithmetic_experiment.json"
MODULUS = 101


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    cumulative = train(connection, lambda data: data)
    totals = Counter()
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND (id % ?) = 0 AND outbound_link LIKE 'http%' ORDER BY id",
        (MODULUS,),
    )
    for (url,) in rows:
        raw = url.encode("utf-8")
        best: int | None = None
        for host_index, path_index, suffix in candidates(raw):
            seed = inverse(host_index, path_index, b"")
            stream = encode(suffix, cumulative, seed)
            restored = inverse(host_index, path_index, decode(stream, len(suffix), cumulative, seed))
            if restored != raw:
                raise AssertionError("factorized arithmetic round trip failed")
            candidate = symbols(bytes((26, host_index, path_index)) + varint(len(suffix)) + stream)
            best = candidate if best is None else min(best, candidate)
        existing = payload_symbol_count(compress_adaptive(url, ASCII_ALPHABET), ASCII_ALPHABET)
        totals["urls"] += 1
        totals["existing_symbols"] += existing
        if best is None:
            totals["no_factorized_prefix"] += 1
            totals["best_symbols"] += existing
        else:
            totals["custom_symbols"] += best
            totals["best_symbols"] += min(existing, best)
            if best < existing:
                totals["wins"] += 1
                totals["saved_symbols"] += existing - best
    report = {
        "corpus": {"source": "smythp/reddit_links_dataset", "training": "odd IDs static grammar-context model", "evaluation": f"even IDs where id % {MODULUS} = 0"},
        "frame": "V26 concept: frozen host index + frozen path index + suffix length + seeded static arithmetic stream",
        "totals": dict(totals),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
