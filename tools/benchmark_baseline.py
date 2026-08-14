#!/usr/bin/env python3
"""Measure the existing ha.mr codec against a deterministic real-URL sample."""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import ASCII_ALPHABET, CodecError, compress  # noqa: E402

DATASET = Path("/home/ubuntu/ha-mr-url-dataset/out.txt")
OUTPUT = ROOT / "reports" / "baseline_real_urls.json"
SAMPLE_SIZE = 5_000


def category(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path or ""
    query = parts.query or ""
    if len(url) >= 300:
        return "long (300+ chars)"
    if len(query) >= 80:
        return "query-heavy (80+ chars)"
    if path.count("/") >= 5:
        return "deep path (5+ separators)"
    if any(token in path.lower() for token in ("api", "assets", "static", "images", "wp-content")):
        return "structured application path"
    return "ordinary"


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, math.floor((len(ordered) - 1) * fraction))
    return ordered[index]


def main() -> None:
    urls = [line.strip() for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    stride = max(1, len(urls) // SAMPLE_SIZE)
    sample = urls[::stride][:SAMPLE_SIZE]

    rows: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    buckets: dict[str, list[float]] = defaultdict(list)
    for url in sample:
        try:
            payload = compress(url, ASCII_ALPHABET)
        except (CodecError, ValueError) as exc:
            failures.append({"url": url, "error": str(exc)})
            continue
        ratio = len(payload) / len(url)
        buckets[category(url)].append(ratio)
        rows.append({
            "url": url,
            "input_length": len(url),
            "payload_length": len(payload),
            "ratio": ratio,
            "category": category(url),
        })

    report = {
        "dataset": {
            "path": str(DATASET),
            "total_urls": len(urls),
            "sample_size": len(sample),
            "selection": f"Every {stride}th URL, capped at {SAMPLE_SIZE}",
        },
        "successes": len(rows),
        "failures": len(failures),
        "overall": {
            "mean_payload_to_input_ratio": sum(row["ratio"] for row in rows) / len(rows),
            "median_payload_to_input_ratio": percentile([row["ratio"] for row in rows], 0.5),
            "p90_payload_to_input_ratio": percentile([row["ratio"] for row in rows], 0.9),
            "payload_longer_than_input": sum(row["payload_length"] >= row["input_length"] for row in rows),
        },
        "categories": {
            name: {
                "count": len(values),
                "mean_payload_to_input_ratio": sum(values) / len(values),
                "median_payload_to_input_ratio": percentile(values, 0.5),
            }
            for name, values in sorted(buckets.items())
        },
        "largest_payload_ratios": sorted(rows, key=lambda row: row["ratio"], reverse=True)[:20],
        "smallest_payload_ratios": sorted(rows, key=lambda row: row["ratio"])[:20],
        "failures_sample": failures[:20],
    }
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "successes": report["successes"],
        "failures": report["failures"],
        "overall": report["overall"],
        "categories": report["categories"],
        "report": str(OUTPUT),
    }, indent=2))


if __name__ == "__main__":
    main()
