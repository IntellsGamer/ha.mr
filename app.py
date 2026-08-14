"""Flask entry point for the Python ha.mr implementation."""

from __future__ import annotations

import base64
import io
import os

import qrcode
from flask import Flask, Response, jsonify, redirect, render_template, request

from ha_mr.codec import (
    ASCII_ALPHABET,
    EMOJI_ALPHABET,
    QR_ALPHABET,
    CodecError,
    compress,
    decompress,
    infer_alphabet,
)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

_ERROR_LEVELS = [
    qrcode.constants.ERROR_CORRECT_L,
    qrcode.constants.ERROR_CORRECT_M,
    qrcode.constants.ERROR_CORRECT_Q,
    qrcode.constants.ERROR_CORRECT_H,
]


def _base_url() -> str:
    return request.url_root.rstrip("/")


def _make_qr_data_url(value: str, correction_level: int) -> str:
    level = _ERROR_LEVELS[max(0, min(correction_level, len(_ERROR_LEVELS) - 1))]
    code = qrcode.QRCode(error_correction=level, box_size=8, border=4)
    code.add_data(value, optimize=0)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _decode_payload(payload: str, mode: str) -> str:
    if mode not in {"auto", "ascii", "emoji", "qr"}:
        raise CodecError("mode must be one of: auto, ascii, emoji, qr")
    alphabet = infer_alphabet(payload, qr=mode == "qr") if mode == "auto" else {
        "ascii": ASCII_ALPHABET,
        "emoji": EMOJI_ALPHABET,
        "qr": QR_ALPHABET,
    }[mode]
    return decompress(payload, alphabet)


@app.get("/")
def index() -> str:
    """Serve the original ha.mr-style page; fragment resolution occurs in app.js."""
    return render_template("index.html")


@app.post("/api/compress")
def api_compress() -> Response:
    body = request.get_json(silent=True) or {}
    input_url = str(body.get("url", "")).strip()
    mode = body.get("mode", "ascii")
    if mode not in {"ascii", "emoji", "qr"}:
        return jsonify(error="mode must be one of: ascii, emoji, qr"), 400

    alphabet = {"ascii": ASCII_ALPHABET, "emoji": EMOJI_ALPHABET, "qr": QR_ALPHABET}[mode]
    try:
        payload = compress(input_url, alphabet)
    except CodecError as exc:
        return jsonify(error=str(exc)), 400

    link = f"{_base_url().upper()}/{payload}" if mode == "qr" else f"{_base_url()}#{payload}"
    return jsonify(payload=payload, link=link, mode=mode)


@app.post("/api/decompress")
def api_decompress() -> Response:
    body = request.get_json(silent=True) or {}
    payload = str(body.get("payload", "")).strip()
    mode = body.get("mode", "auto")
    try:
        return jsonify(url=_decode_payload(payload, mode))
    except CodecError as exc:
        return jsonify(error=str(exc)), 400


@app.get("/resolve")
def resolve_fragment_payload() -> Response:
    """Receive a hash payload from the browser bridge and redirect to its target."""
    payload = request.args.get("payload", "").replace(" ", "")
    try:
        return redirect(_decode_payload(payload, "auto"), code=302)
    except CodecError:
        return Response("Unknown ha.mr payload", status=404, mimetype="text/plain")


@app.post("/api/qr")
def api_qr() -> Response:
    body = request.get_json(silent=True) or {}
    input_url = str(body.get("url", "")).strip()
    try:
        correction_level = int(body.get("correction_level", 1))
    except (TypeError, ValueError):
        correction_level = 1

    try:
        payload = compress(input_url, QR_ALPHABET)
    except CodecError as exc:
        return jsonify(error=str(exc)), 400

    link = f"{_base_url().upper()}/{payload}"
    return jsonify(payload=payload, link=link, image=_make_qr_data_url(link, correction_level))


@app.get("/healthz")
def healthz() -> Response:
    return jsonify(status="ok", codec="python")


@app.get("/<path:payload>")
def resolve_qr_payload(payload: str) -> Response:
    """Decode a QR-mode path payload and perform the destination redirect."""
    try:
        destination = decompress(payload, QR_ALPHABET)
    except CodecError:
        return Response("Unknown ha.mr payload", status=404, mimetype="text/plain")
    return redirect(destination, code=302)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
