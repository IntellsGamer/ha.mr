#!/usr/bin/env python3
"""Freeze the V11 factorized host and path-prefix tables from Reddit training."""

from __future__ import annotations

import base64
import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
TARGET = ROOT / "ha_mr" / "factorized_codebook.py"
MAX_ITEMS = 255
DELIMITERS = b"/?&=.#-_"


def split_host(raw: bytes) -> tuple[bytes, bytes] | None:
    try:
        parts = urlsplit(raw.decode("utf-8"))
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    host = f"{parts.scheme}://{parts.netloc}".encode("utf-8")
    return host, raw[len(host):]


def path_prefixes(remainder: bytes) -> set[bytes]:
    bounds = [0] + [index + 1 for index, value in enumerate(remainder) if value in DELIMITERS] + [len(remainder)]
    output: set[bytes] = set()
    for left_index, left in enumerate(bounds[:-1]):
        if left_index > 0:
            break
        for right in bounds[left_index + 1:left_index + 6]:
            prefix = remainder[left:right]
            if 2 <= len(prefix) <= 96:
                output.add(prefix)
    return output


def ranked_table(counts: Counter[bytes]) -> list[bytes]:
    ranked = sorted(
        ((item, count, (len(item) - 2) * count) for item, count in counts.items() if count >= 3),
        key=lambda item: (item[2], item[1], len(item[0]), item[0]),
        reverse=True,
    )
    return [item for item, _count, _score in ranked[:MAX_ITEMS]]


def frozen_tuple(items: list[bytes], name: str) -> str:
    encoded = base64.b64encode(b"\0".join(items)).decode("ascii")
    wrapped = "\n".join(f'        "{encoded[index:index + 100]}"' for index in range(0, len(encoded), 100))
    return (
        f"{name} = tuple(base64.b64decode(\n"
        "    (\n"
        f"{wrapped}\n"
        "    )\n"
        ").split(b\"\\0\"))\n"
    )


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    hosts: Counter[bytes] = Counter()
    paths: Counter[bytes] = Counter()
    for (url,) in connection.execute("SELECT outbound_link FROM links WHERE (id % 2) = 1 AND outbound_link LIKE 'http%'"):
        split = split_host(url.encode("utf-8"))
        if split is None:
            continue
        host, remainder = split
        hosts[host] += 1
        paths.update(path_prefixes(remainder))
    host_table = ranked_table(hosts)
    path_table = ranked_table(paths)
    TARGET.write_text(
        '"""Frozen V11 factorized URL grammar tables trained from Reddit links."""\n\n'
        "from __future__ import annotations\n\n"
        "import base64\n\n"
        + frozen_tuple(host_table, "HOST_PREFIXES")
        + "\n"
        + frozen_tuple(path_table, "PATH_PREFIXES"),
        encoding="utf-8",
    )
    print(f"Wrote {TARGET.relative_to(ROOT)} with {len(host_table)} hosts and {len(path_table)} paths")


if __name__ == "__main__":
    main()
