# ha.mr — Python ASGI edition

A **Python implementation** of ha.mr’s self-contained URL compressor. The project preserves the upstream V0 format, adds an adaptive V1 codec for difficult URLs, and does not use a redirect database: the destination is recovered from the payload itself.

## Runtime architecture

The web application is no longer a Flask/WSGI process. `app.py` is a **FastAPI ASGI** boundary that owns HTTP parsing, static assets, templates, and response assembly. It does not execute compression, decompression, or QR rendering on the asyncio event loop. Those CPU-bound operations are pure, pickle-safe functions in `ha_mr/service.py`, dispatched through a bounded spawned process pool.

| Concern | Implementation |
| --- | --- |
| HTTP runtime | FastAPI + Uvicorn ASGI |
| Event-loop protection | Bounded `ProcessPoolExecutor` with spawned workers |
| Codec | `ha_mr.codec` pure Python, no request or server state |
| QR rendering | Worker-only `qrcode` rendering |
| Back-pressure | Semaphore-bounded CPU queue; `HA_MR_CPU_QUEUE_LIMIT` |
| Worker parallelism | `HA_MR_CPU_WORKERS`, defaulting to at most four processes |
| Storage | None; payloads remain self-contained |
| Text links | `/#<payload>` resolved through a browser bridge |
| QR links | `/<QR-alphanumeric-payload>` |

This split is deliberate: moving a CPU-bound codec into an `async def` alone does not make it non-blocking. The ASGI event loop remains responsive while process workers execute codec or QR work. The pure codec is also usable directly without importing FastAPI or starting a server.

The retained browser implementation under `legacy/browser-reference/` is format provenance only. It is not loaded at runtime. `tools/extract_codec_data.py` turns its published tables into `ha_mr/codec_data.py`.

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn asgi:app --host 0.0.0.0 --port 5000
```

Then open `http://127.0.0.1:5000`.

## Adaptive V1–V3 codec

For the selected output transport, the encoder emits the shortest valid candidate among the original structural V0 codec, V1 raw/static-dictionary DEFLATE, V2 semantic-DEFLATE, and V3 host-codebook semantic-DEFLATE. V0 remains the best representation for most familiar shared links; the later frames handle long, opaque, nested, query-heavy, and V0-unsupported URLs.

V2 makes a byte-level, fully reversible pass before DEFLATE. It packs canonical `%HH` escapes, long isolated decimal identifiers, homogeneous-case hexadecimal identifiers, UUIDs, canonical Base64URL values, and Base62 opaque tokens only when the representation is shorter. V3 additionally replaces a host from a frozen 255-entry Reddit-trained codebook with a one-byte index. Every transform stores its own marker, length, and case information; decoding remains self-contained and does not need the Reddit database.

The V1 static dictionary is trained reproducibly from the **odd-ID half** of the one-million-row Reddit outbound-links sample. It learns only repeated safe link structure—protocol fragments, hosts, short path prefixes, and query keys—and excludes fragments, query values, and one-off identifiers. Evaluation uses a deterministic subset of the disjoint even-ID half. The runtime contains only the frozen dictionary, never the source database.

| Transport | Use | Trade-off |
| --- | --- | --- |
| ASCII | Default interoperable payload | Lowest visible-symbol density |
| Emoji | Dense display transport | V1 uses a safe one-code-point alphabet; URI serializers may expand it |
| Japanese/CJK | Densest visible text transport | Often percent-encoded by strict URL-only channels |
| QR | QR-compatible alphanumeric transport | Restricted alphabet by design |

V0 payloads stay valid. Adaptive frames V1, V2, and V3 are self-identifying through packed-number framing; emoji adaptive frames additionally use a dedicated marker before their prefix-safe body.

## API

`POST /api/compress` accepts `url` and optional `mode` (`ascii`, `emoji`, `cjk`, or `qr`). `POST /api/decompress` accepts a `payload` and optional `mode` (`auto`, `ascii`, `emoji`, `cjk`, or `qr`). `POST /api/qr` returns a QR path payload plus PNG data URL. `GET /healthz` reports the ASGI runtime and worker-pool configuration.

```json
{"url":"https://example.com/docs/guide?ref=ha#intro","mode":"qr"}
```

## Benchmarks and tests

Run all regression tests:

```bash
python3 -m unittest -v tests/test_app.py tests/test_adaptive.py
```

Download the Git-LFS-tracked Reddit database before reproducing the corpus work:

```bash
git lfs pull  # in a clone of smythp/reddit_links_dataset
python3 tools/build_reddit_dictionary.py
python3 tools/embed_static_dictionary.py
python3 tools/benchmark_reddit_adaptive.py
python3 tools/benchmark_asgi_concurrency.py
```

The provenance and results files under `reports/` intentionally store aggregate metadata and measurements, not individual shared links.

## Deployment

Deploy `asgi:app` with an ASGI server such as Uvicorn or an ASGI worker class behind a reverse proxy. Do not use a WSGI worker. The proxy must forward arbitrary path payloads to the application so QR redirects resolve. Set `HA_MR_CPU_WORKERS`, `HA_MR_CPU_QUEUE_LIMIT`, `HA_MR_MAX_INPUT_CHARS`, and the ASGI server worker count according to available CPU and desired per-instance concurrency.

## License

This conversion retains the upstream project’s MIT licence; see [`LICENSE`](LICENSE).
