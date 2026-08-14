#!/usr/bin/env python3
"""Generate native Python codec tables from the upstream JavaScript source.

The generated module is committed so the Flask application has no JavaScript
runtime dependency. Keeping this extractor makes codec-table provenance and
future upstream synchronisation explicit and repeatable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_SOURCE = ROOT / "legacy" / "browser-reference"
COMPRESS_SOURCE = LEGACY_SOURCE / "compress.js"
ALPHABET_SOURCE = LEGACY_SOURCE / "alphabets.js"
OUTPUT = ROOT / "ha_mr" / "codec_data.py"


def extract_object(source: str, name: str) -> dict[str, str]:
    match = re.search(rf"const {name} = (\{{.*?\}});", source, re.DOTALL)
    if not match:
        raise RuntimeError(f"Could not find object declaration: {name}")
    return json.loads(match.group(1))


def extract_string_list(source: str, name: str) -> list[str]:
    match = re.search(rf"const {name} = \[(.*?)\];", source, re.DOTALL)
    if not match:
        raise RuntimeError(f"Could not find array declaration: {name}")
    return json.loads("[" + match.group(1) + "]")


def main() -> None:
    compress_source = COMPRESS_SOURCE.read_text(encoding="utf-8")
    alphabet_source = ALPHABET_SOURCE.read_text(encoding="utf-8")

    subalphabet_match = re.search(
        r"const subalphabets = \[(.*?)\];", compress_source, re.DOTALL
    )
    if not subalphabet_match:
        raise RuntimeError("Could not find subalphabets declaration")
    subalphabets = re.findall(r'"((?:\\.|[^"\\])*)"', subalphabet_match.group(1))
    subalphabets = [json.loads(f'"{value}"') for value in subalphabets]

    ascii_match = re.search(
        r'outputAlphabetASCII = "((?:\\.|[^"\\])*)"\.split\(""\)',
        alphabet_source,
    )
    qr_match = re.search(
        r'outputAlphabetQR = "((?:\\.|[^"\\])*)"\.split\(""\)',
        alphabet_source,
    )
    if not ascii_match or not qr_match:
        raise RuntimeError("Could not find text output alphabets")

    data = {
        "VERSION": 0,
        "SUBALPHABETS": subalphabets,
        "TLD_ENCODE": extract_object(compress_source, "tldEncode"),
        "SLD_ENCODE": extract_object(compress_source, "sldEncode"),
        "DOMAIN_ENCODE": extract_object(compress_source, "domainEncode"),
        "PATH_ENCODE": extract_object(compress_source, "pathEncode"),
        "OUTPUT_ALPHABET_ASCII": list(json.loads(f'"{ascii_match.group(1)}"')),
        "OUTPUT_ALPHABET_QR": list(json.loads(f'"{qr_match.group(1)}"')),
        "OUTPUT_ALPHABET_EMOJI": extract_string_list(alphabet_source, "outputAlphabetEmoji"),
    }

    lines = [
        '"""Generated codec tables. Do not edit by hand; use tools/extract_codec_data.py."""',
        "",
    ]
    for name, value in data.items():
        lines.append(f"{name} = {value!r}")
        lines.append("")
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
