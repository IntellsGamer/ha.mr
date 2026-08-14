#!/usr/bin/env python3
"""Inspect the Reddit shared-links SQLite database without modifying it."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    tables = connection.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    for table in tables:
        print(f"TABLE {table['name']}")
        print(table["sql"])
        count = connection.execute(f'SELECT COUNT(*) AS count FROM "{table["name"]}"').fetchone()["count"]
        print(f"ROWS {count}")
        rows = connection.execute(f'SELECT * FROM "{table["name"]}" LIMIT 3').fetchall()
        for row in rows:
            print(dict(row))
        print()


if __name__ == "__main__":
    main()
