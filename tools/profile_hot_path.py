#!/usr/bin/env python3
"""Profile CPU and allocation costs of current real-link request-path work."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, CodecError, compress_adaptive, decompress_adaptive  # noqa: E402
from ha_mr.service import make_qr_data_url  # noqa: E402

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "reddit_hot_path_profile.json"
SAMPLE_SIZE = 2_000
QR_SAMPLE_SIZE = 50


def urls() -> list[str]:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE outbound_link LIKE 'http%' ORDER BY id LIMIT ?",
        (SAMPLE_SIZE,),
    ).fetchall()
    return [row[0] for row in rows if row[0]]


def measure(label: str, operation) -> dict[str, object]:
    tracemalloc.start()
    started = time.perf_counter()
    result = operation()
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"label": label, "seconds": elapsed, "peak_bytes": peak, "result_count": len(result)}


def main() -> None:
    links = urls()

    def codec_round_trips() -> list[str]:
        outputs: list[str] = []
        for url in links:
            try:
                payload = compress_adaptive(url, ASCII_ALPHABET)
                outputs.append(decompress_adaptive(payload, ASCII_ALPHABET))
            except CodecError:
                continue
        return outputs

    def qr_rendering() -> list[str]:
        outputs: list[str] = []
        for url in links[:QR_SAMPLE_SIZE]:
            try:
                payload = compress_adaptive(url, ASCII_ALPHABET)
            except CodecError:
                continue
            outputs.append(make_qr_data_url(f"https://ha.mr/{payload}", 1))
        return outputs

    results = [measure("codec_round_trips", codec_round_trips), measure("qr_rendering", qr_rendering)]
    report = {
        "database": str(DATABASE),
        "corpus_size": len(links),
        "measurements": results,
        "per_item": {
            item["label"]: {"milliseconds": (item["seconds"] / item["result_count"]) * 1_000}
            for item in results
            if item["result_count"]
        },
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
