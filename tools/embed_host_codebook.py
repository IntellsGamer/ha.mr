#!/usr/bin/env python3
"""Generate the frozen V3 host-codebook module from Reddit training rows."""

from __future__ import annotations

import base64
import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
TARGET = ROOT / "ha_mr" / "host_codebook.py"
MAX_HOSTS = 255


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    counts: Counter[str] = Counter()
    for (url,) in connection.execute("SELECT outbound_link FROM links WHERE (id % 2) = 1 AND outbound_link LIKE 'http%'"):
        try:
            parts = urlsplit(url)
        except ValueError:
            continue
        host = parts.hostname
        if not host or host != host.lower() or len(host) > 120:
            continue
        counts[host] += 1

    hosts = [
        host for host, _count in sorted(
            counts.items(),
            key=lambda item: ((len(item[0]) - 3) * item[1], item[1], item[0]),
            reverse=True,
        )[:MAX_HOSTS]
    ]
    encoded = base64.b64encode("\0".join(hosts).encode("ascii")).decode("ascii")
    wrapped = "\n".join(f'    "{encoded[index:index + 100]}"' for index in range(0, len(encoded), 100))
    TARGET.write_text(
        '"""Frozen V3 host codebook trained from Reddit shared-link structure."""\n\n'
        "from __future__ import annotations\n\n"
        "import base64\n\n"
        "HOSTS = tuple(base64.b64decode(\n"
        "    (\n"
        f"{wrapped}\n"
        "    )\n"
        ").decode(\"ascii\").split(\"\\0\"))\n"
        "HOST_INDEX = {host: index for index, host in enumerate(HOSTS)}\n",
        encoding="utf-8",
    )
    print(f"Wrote {TARGET.relative_to(ROOT)} with {len(hosts)} hosts")


if __name__ == "__main__":
    main()
