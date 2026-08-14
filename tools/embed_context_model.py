#!/usr/bin/env python3
"""Freeze the custom raw-URL arithmetic model into a compact decoder module."""

from __future__ import annotations

import base64
import sqlite3
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from prototype_context_arithmetic import ALPHABET, CLASS_COUNT, STATE_COUNT, TARGET_TOTAL, train  # noqa: E402

DATABASE = Path("/home/ubuntu/reddit-links-dataset/test.db")
OUTPUT = ROOT / "ha_mr" / "context_model.py"


def main() -> None:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    tables = train(connection, lambda data: data)
    flat = [value for table in tables for value in table]
    raw = struct.pack(f">{len(flat)}H", *flat)
    payload = base64.b85encode(zlib.compress(raw, level=9)).decode("ascii")
    OUTPUT.write_text(
        f'''"""Frozen raw-URL grammar-context arithmetic model generated from odd IDs."""\n\nfrom __future__ import annotations\n\nimport base64\nimport struct\nimport zlib\n\nSTATE_COUNT = {STATE_COUNT}\nCLASS_COUNT = {CLASS_COUNT}\nALPHABET_SIZE = {ALPHABET}\nNORMALIZATION_TOTAL = {TARGET_TOTAL}\n_TABLE_WIDTH = ALPHABET_SIZE + 1\n_VALUE_COUNT = STATE_COUNT * CLASS_COUNT * _TABLE_WIDTH\n_ENCODED = "{payload}"\n\n_values = struct.unpack(\n    f">{{_VALUE_COUNT}}H",\n    zlib.decompress(base64.b85decode(_ENCODED.encode("ascii"))),\n)\nCUMULATIVE = tuple(\n    _values[offset:offset + _TABLE_WIDTH]\n    for offset in range(0, len(_values), _TABLE_WIDTH)\n)\n''',
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT}: {len(tables)} contexts, {len(raw)} bytes raw, {len(payload)} base85 characters")


if __name__ == "__main__":
    main()
