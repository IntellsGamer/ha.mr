#!/usr/bin/env python3
"""Build immutable browser assets for the exact V26 Python/WebAssembly codec."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ha_mr.codec import (  # noqa: E402
    ASCII_ALPHABET,
    CJK_V2_ALPHABET,
    EMOJI_ALPHABET,
    compress_adaptive,
)

RUNTIME_VERSION = "0.26.3"
STATIC = ROOT / "static"
RUNTIME = STATIC / "pyodide" / RUNTIME_VERSION
CODEC_DIR = STATIC / "codec" / "v26"
ARCHIVE = CODEC_DIR / "ha_mr_v26.zip"
CONFORMANCE = CODEC_DIR / "conformance.json"
MANIFEST = CODEC_DIR / "manifest.json"

PUBLIC_URLS = (
    "https://manus.im/docs/agents?mode=asgi",
    "https://www.youtube.com/watch?v=Xic_cDYrtnM",
    "https://example.com/redirect/12345678901234567890?next=https%3A%2F%2Fnews.example%2F"
    "a%20b&id=1ae03060-3f06-4a5c-9ac6-b5c1b4a62664&token=QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo",
    "https://example.com/redirect?next=https%3A%2F%2Fmanus.im%2Fdocs%3Fmode%3Dasgi",
    "https://www.reddit.com/r/AskReddit/comments/24mzcw/what_is_the_most_interesting_fact_you_know/",
)

BRIDGE = '''"""Browser-only bridge for the exact V26 ha.mr codec."""
from ha_mr.codec import (
    ASCII_ALPHABET,
    CJK_ALPHABET,
    CJK_V2_ALPHABET,
    EMOJI_ALPHABET,
    CodecError,
    compress_adaptive,
    decompress_adaptive,
    infer_alphabet,
)

_ALPHABETS = {
    "ascii": ASCII_ALPHABET,
    "emoji": EMOJI_ALPHABET,
    "cjk": CJK_V2_ALPHABET,
}

def _alphabet(mode):
    try:
        return _ALPHABETS[mode]
    except KeyError as exc:
        raise CodecError("Unknown browser transport mode.") from exc

def compress_url(url, mode):
    return compress_adaptive(str(url), _alphabet(str(mode)))

def decompress_payload(payload, mode):
    return decompress_adaptive(str(payload), _alphabet(str(mode)))

def decompress_auto(payload):
    value = str(payload)
    return decompress_adaptive(value, infer_alphabet(value))
'''


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def asset(path: Path) -> dict[str, object]:
    return {
        "url": "/static/" + path.relative_to(STATIC).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def build_archive() -> None:
    CODEC_DIR.mkdir(parents=True, exist_ok=True)
    modules = sorted((ROOT / "ha_mr").glob("*.py"))
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for module in modules:
            if module.name == "service.py":
                continue
            entry = zipfile.ZipInfo(f"ha_mr/{module.name}", date_time=(2025, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, module.read_bytes())
        bridge = zipfile.ZipInfo("browser_codec_bridge.py", date_time=(2025, 1, 1, 0, 0, 0))
        bridge.compress_type = zipfile.ZIP_DEFLATED
        bridge.external_attr = 0o644 << 16
        archive.writestr(bridge, BRIDGE.encode("utf-8"))


def build_conformance() -> None:
    vectors = []
    for url in PUBLIC_URLS:
        vectors.append({
            "url": url,
            "payloads": {
                "ascii": compress_adaptive(url, ASCII_ALPHABET),
                "emoji": compress_adaptive(url, EMOJI_ALPHABET),
                "cjk": compress_adaptive(url, CJK_V2_ALPHABET),
            },
        })
    payload = {
        "vectors": vectors,
        "historical_decode": {
            "payload": "oz~KA/;60*rw5",
            "mode": "ascii",
            "url": "https://www.youtube.com/watch?v=Xic_cDYrtnM",
        },
    }
    CONFORMANCE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    build_archive()
    build_conformance()
    required_runtime = [
        RUNTIME / "pyodide.js",
        RUNTIME / "pyodide.asm.js",
        RUNTIME / "pyodide.asm.wasm",
        RUNTIME / "python_stdlib.zip",
        RUNTIME / "pyodide-lock.json",
    ]
    missing = [str(path) for path in required_runtime if not path.is_file()]
    if missing:
        raise SystemExit("Missing pinned runtime assets: " + ", ".join(missing))
    runtime_assets = [asset(path) for path in required_runtime]
    manifest = {
        "runtime": {"version": RUNTIME_VERSION, "index_url": f"/static/pyodide/{RUNTIME_VERSION}/"},
        "codec": {
            "archive": asset(ARCHIVE),
            "conformance": asset(CONFORMANCE),
            "revision": sha256(ARCHIVE)[:20],
        },
        "runtime_assets": runtime_assets,
        "cache_name": f"ha-mr-v26-{sha256(ARCHIVE)[:20]}",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"archive_bytes": ARCHIVE.stat().st_size, "revision": manifest["codec"]["revision"], "vectors": len(PUBLIC_URLS)}, indent=2))


if __name__ == "__main__":
    main()
