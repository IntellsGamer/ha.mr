# ha.mr — Flask edition

A **Python/Flask implementation** of ha.mr’s reversible URL compressor and QR-code optimiser. It retains the original format’s self-contained payload model: links are encoded and decoded without a redirect database.

## What changed

The runtime implementation is now Python. `ha_mr/codec.py` ports the `BigInt` packing, Huffman dictionaries, URL component encoding, ASCII output alphabet, emoji output alphabet, and QR-specific alphanumeric alphabet to Python integers and native data structures. `app.py` exposes the Flask UI, JSON APIs, QR image generation, and QR-path redirect handling.

| Concern | Flask implementation |
| --- | --- |
| Web application | Flask with server-rendered Jinja templates |
| Compression/decompression | `ha_mr.codec` — pure Python |
| QR image rendering | Python `qrcode` package |
| Text-link transport | `/#<payload>` |
| QR-link transport | `/<QR-alphanumeric-payload>` |
| Storage | None; payloads remain self-contained |
| Existing payload compatibility | ASCII and QR codec formats match the upstream version-0 format |

The upstream browser implementation is retained under `legacy/browser-reference/` solely as provenance and a format-reference source. It is **not loaded or executed by the Flask application**. `tools/extract_codec_data.py` turns its published tables into the committed native Python table module `ha_mr/codec_data.py`.

## Run locally

Create a virtual environment if desired, install dependencies, and start Flask:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open `http://127.0.0.1:5000`.

## API

`POST /api/compress` accepts JSON with `url` and an optional `mode` of `ascii`, `emoji`, or `qr`.

```json
{"url":"https://example.com/docs/guide?ref=ha#intro","mode":"qr"}
```

`POST /api/decompress` accepts `payload` and optional `mode` (`auto`, `ascii`, `emoji`, or `qr`). `GET /healthz` returns a small readiness response.

## Test

```bash
python3 -m unittest -v tests/test_app.py
```

The suite checks codec round trips, a payload captured from the original public deployment, QR-alphabet output, Flask APIs, server-side QR PNG generation, and redirect resolution.

## Regenerate codec tables

If intentionally updating the retained upstream reference implementation, regenerate the native Python dictionaries and re-run the test suite:

```bash
python3 tools/extract_codec_data.py
python3 -m unittest -v tests/test_app.py
```

## Deployment

Deploy as a normal WSGI application using the module-level `app` object. Set `PORT` to override the default `5000` when invoking `python app.py`. For production, place it behind a WSGI server and reverse proxy, and make sure the proxy forwards arbitrary path payloads to Flask so QR redirects resolve.

## License

This conversion retains the upstream project’s MIT licence; see [`LICENSE`](LICENSE).
