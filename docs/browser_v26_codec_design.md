# Exact Browser V26 Codec Design

## Compatibility requirement

The browser implementation must preserve **the exact latest V26 Python codec contract**. A client-side result is considered correct only when it has the same transport payload and decoded URL as Python for the same input, selected alphabet, frozen tables, and current codec source revision.

> A smaller, approximate JavaScript encoder is explicitly out of scope. Every legacy decoder, V16–V26 frame, static DEFLATE dictionary, codebook, and tie-breaking rule must remain identical.

## Runtime choice

ha.mr will run the project’s existing pure-Python `ha_mr` codec package inside a pinned, self-hosted CPython/WebAssembly runtime. This is an implementation of Python delivered to the browser, not a codec rewrite. The choice eliminates semantic drift from URL parsing, raw-DEFLATE behavior, static dictionary handling, arithmetic coding arithmetic, and byte-to-integer transport conversion.[1] [2]

| Area | Browser implementation |
|---|---|
| Codec logic | The shipped `ha_mr` V26 Python dependency closure, imported unchanged in the browser runtime. |
| Runtime | Pinned self-hosted Pyodide release and only its required standard-library support. |
| Frozen tables | Existing project modules, including V26 arithmetic model and all historic codebooks. |
| Asset cache | Version-named Cache Storage entries; old version is never used for a new codec revision. |
| Loading feedback | Byte-accurate download progress for prefetchable assets; an explicit indeterminate compiling/initializing stage for WebAssembly. |
| Default execution | Client-side. Server API remains a user-selectable fallback. |
| Fragment resolution | Client decodes directly by default; server `/resolve` remains used only in server mode. |

## Asset lifecycle

The page will discover a versioned manifest generated with the deployed codec. The client loads the manifest, then fetches the runtime and codec archive through a progress-aware reader. Every successfully fetched immutable response is placed in the browser Cache Storage namespace derived from the manifest revision. Cached responses report as already available instead of simulating a download.

The first load is divided into visible stages: fetching the runtime loader, downloading the WebAssembly/standard-library runtime, downloading the V26 codec archive, compiling/initializing WebAssembly, installing the codec package into the runtime filesystem, and verifying a built-in V26 test vector. Only the download stages present a percentage because compilation duration cannot be measured honestly in advance.

The client exposes no codec call until the verification vector succeeds. If initialization fails, the UI explains the failure and lets the user choose server mode without silently changing the selected execution mode.

## Browser bridge

A small Python bridge imports `ha_mr.codec` and exposes `compress_url(url, mode)` and `decompress_payload(payload, mode)`. JavaScript passes strings via Pyodide globals rather than interpolating user text into Python code. The bridge maps `ascii`, `emoji`, and `cjk` to the exact Python alphabets and invokes `compress_adaptive` and `decompress_adaptive` directly.

The service layer remains responsible for HTTP page delivery, server-mode compression/decompression, redirects, and QR-image delivery. The default browser path does not call `/api/compress`, `/api/decompress`, or `/resolve`.

## Cross-runtime proof

A generated conformance corpus records public representative URLs plus deterministic frame coverage. The browser test harness runs that corpus in the browser runtime and compares emitted payload strings to the Python outputs generated in the same revision. It also checks Python-produced historical payload decoding in the browser and browser-produced payload decoding in Python.

## References

[1] [Pyodide quickstart](https://pyodide.org/en/stable/usage/quickstart.html)

[2] [Pyodide JavaScript API](https://pyodide.org/en/stable/usage/api/js-api.html)

[3] [Pyodide deployment guidance](https://pyodide.org/en/0.26.3/usage/downloading-and-deploying.html)

[4] [Pyodide service-worker guidance](https://pyodide.org/en/latest/usage/service-worker.html)
