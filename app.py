"""Flask entry point for the Python ha.mr implementation."""

from __future__ import annotations

import base64
import io
import os
from urllib.parse import quote

import qrcode
from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

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

_ERROR_LEVELS = [qrcode.constants.ERROR_CORRECT_L, qrcode.constants.ERROR_CORRECT_M,
                 qrcode.constants.ERROR_CORRECT_Q, qrcode.constants.ERROR_CORRECT_H]


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


def _build_result(input_url: str, *, emoji: bool, qr_enabled: bool, correction_level: int) -> dict[str, object]:
    text_alphabet = EMOJI_ALPHABET if emoji else ASCII_ALPHABET
    text_payload = compress(input_url, text_alphabet)
    compact_link = f"{_base_url()}#{quote(text_payload, safe='') if emoji else text_payload}"

    normalised = input_url.strip()
    if normalised.startswith("https://"):
        normalised = normalised[8:]
    elif normalised.startswith("http://"):
        normalised = normalised[7:]
    input_length = max(len(normalised), 1)
    ratio = (1 - (len(text_payload) + len(request.host)) / input_length) * 100

    qr_link = None
    qr_data_url = None
    if qr_enabled:
        qr_payload = compress(input_url, QR_ALPHABET)
        # Uppercase makes the payload eligible for QR alphanumeric mode.
        qr_link = f"{_base_url().upper()}/{qr_payload}"
        qr_data_url = _make_qr_data_url(qr_link, correction_level)

    return {
        "input_url": input_url,
        "compact_link": compact_link,
        "payload": text_payload,
        "ratio": ratio,
        "qr_link": qr_link,
        "qr_data_url": qr_data_url,
        "emoji": emoji,
        "qr_enabled": qr_enabled,
        "correction_level": correction_level,
    }


@app.get("/")
def index() -> str:
    return render_template("index.html", result=None, error=None)


@app.post("/")
def create_link() -> str:
    input_url = request.form.get("url", "").strip()
    emoji = request.form.get("emoji") == "on"
    qr_enabled = request.form.get("qr") == "on"
    try:
        correction_level = int(request.form.get("correction_level", "1"))
    except ValueError:
        correction_level = 1

    try:
        result = _build_result(
            input_url,
            emoji=emoji,
            qr_enabled=qr_enabled,
            correction_level=correction_level,
        )
        return render_template("index.html", result=result, error=None)
    except CodecError as exc:
        return render_template(
            "index.html",
            result={"input_url": input_url, "emoji": emoji, "qr_enabled": qr_enabled, "correction_level": correction_level},
            error=str(exc),
        ), 400


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

    if mode == "qr":
        link = f"{_base_url().upper()}/{payload}"
    else:
        link = f"{_base_url()}#{quote(payload, safe='') if mode == 'emoji' else payload}"
    return jsonify(payload=payload, link=link, mode=mode)


@app.post("/api/decompress")
def api_decompress() -> Response:
    body = request.get_json(silent=True) or {}
    payload = str(body.get("payload", "")).strip()
    mode = body.get("mode", "auto")
    if mode not in {"auto", "ascii", "emoji", "qr"}:
        return jsonify(error="mode must be one of: auto, ascii, emoji, qr"), 400
    try:
        alphabet = infer_alphabet(payload, qr=mode == "qr") if mode == "auto" else {
            "ascii": ASCII_ALPHABET,
            "emoji": EMOJI_ALPHABET,
            "qr": QR_ALPHABET,
        }[mode]
        return jsonify(url=decompress(payload, alphabet))
    except CodecError as exc:
        return jsonify(error=str(exc)), 400


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
