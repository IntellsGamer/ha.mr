#!/usr/bin/env python3
"""Measure bounded ASGI endpoint concurrency on held-out Reddit links."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import CPU_WORKERS, app  # noqa: E402

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
REPORT = ROOT / "reports" / "asgi_concurrency_benchmark.json"
REQUESTS = 200
CONCURRENCY = 32


def load_urls() -> list[str]:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT outbound_link FROM links WHERE (id % 2) = 0 AND outbound_link LIKE 'http%' ORDER BY id LIMIT ?",
        (REQUESTS,),
    ).fetchall()
    return [row[0] for row in rows]


async def main() -> None:
    urls = load_urls()
    semaphore = asyncio.Semaphore(CONCURRENCY)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://benchmark.local") as client:
        async def request(url: str) -> tuple[int, float]:
            async with semaphore:
                started = time.perf_counter()
                response = await client.post("/api/compress", json={"url": url, "mode": "ascii"})
                return response.status_code, time.perf_counter() - started

        started = time.perf_counter()
        results = await asyncio.gather(*(request(url) for url in urls))
        elapsed = time.perf_counter() - started

    latencies = sorted(item[1] for item in results)
    report = {
        "requests": len(urls),
        "concurrency": CONCURRENCY,
        "cpu_workers": CPU_WORKERS,
        "successes": sum(status == 200 for status, _latency in results),
        "elapsed_seconds": elapsed,
        "requests_per_second": len(urls) / elapsed,
        "latency_ms": {
            "median": latencies[len(latencies) // 2] * 1_000,
            "p95": latencies[int((len(latencies) - 1) * 0.95)] * 1_000,
            "max": latencies[-1] * 1_000,
        },
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
