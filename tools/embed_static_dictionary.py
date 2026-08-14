#!/usr/bin/env python3
"""Embed the frozen V1 static dictionary as a Python bytes constant."""

from __future__ import annotations

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".build" / "reddit_v1_dictionary.bin"
TARGET = ROOT / "ha_mr" / "codec_dictionary.py"


def main() -> None:
    encoded = base64.b64encode(SOURCE.read_bytes()).decode("ascii")
    wrapped = "\n".join(f'    "{encoded[index:index + 100]}"' for index in range(0, len(encoded), 100))
    TARGET.write_text(
        '"""Frozen V1 URL phrase dictionary generated from the Reddit shared-links training split."""\n\n'
        "from __future__ import annotations\n\n"
        "import base64\n\n"
        "STATIC_URL_DICTIONARY = base64.b64decode(\n"
        "    (\n"
        f"{wrapped}\n"
        "    )\n"
        ")\n",
        encoding="utf-8",
    )
    print(f"Wrote {TARGET.relative_to(ROOT)} ({len(SOURCE.read_bytes())} bytes)")


if __name__ == "__main__":
    main()
