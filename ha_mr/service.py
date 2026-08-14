"""Pure, pickle-safe CPU worker functions for the ASGI boundary.

These functions intentionally have no request, template, or server state. The
web layer can send them to a bounded process pool without blocking its event
loop, while direct callers can still use the codec module without an ASGI
runtime.
"""

from __future__ import annotations

import base64
import io

import qrcode

from .codec import CodecError, QR_ALPHABET, adaptive_alphabet, compress_adaptive, decompress_adaptive, infer_alphabet

_ERROR_LEVELS = (
    qrcode.constants.ERROR_CORRECT_L,
    qrcode.constants.ERROR_CORRECT_M,
    qrcode.constants.ERROR_CORRECT_Q,
    qrcode.constants.ERROR_CORRECT_H,
)


def compress_payload(url: str, mode: str) -> str:
    """Compress a URL using the requested transport in a CPU worker."""
    if mode not in {"ascii", "emoji", "cjk", "qr"}:
        raise CodecError("mode must be one of: ascii, emoji, cjk, qr")
    return compress_adaptive(url, adaptive_alphabet(mode))


def decode_payload(payload: str, mode: str = "auto") -> str:
    """Decode a text fragment or QR path payload in a CPU worker."""
    if mode not in {"auto", "ascii", "emoji", "cjk", "qr"}:
        raise CodecError("mode must be one of: auto, ascii, emoji, cjk, qr")
    alphabet = infer_alphabet(payload, qr=mode == "qr") if mode == "auto" else adaptive_alphabet(mode)
    return decompress_adaptive(payload, alphabet)


def make_qr_data_url(link: str, correction_level: int) -> str:
    """Render a QR PNG inside the worker and return a data URL to the ASGI layer."""
    level = _ERROR_LEVELS[max(0, min(correction_level, len(_ERROR_LEVELS) - 1))]
    code = qrcode.QRCode(error_correction=level, box_size=8, border=4)
    code.add_data(link, optimize=0)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def qr_result(url: str, base_url: str, correction_level: int) -> dict[str, str]:
    """Build both a QR-mode path link and its image in one process-pool task."""
    payload = compress_adaptive(url, QR_ALPHABET)
    link = f"{base_url.upper()}/{payload}"
    return {"payload": payload, "link": link, "image": make_qr_data_url(link, correction_level)}
