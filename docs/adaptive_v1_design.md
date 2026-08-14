# Adaptive V1 codec and ASGI boundary

## Why the codec stays separate from the web framework

The compression core is not a Flask, FastAPI, or browser concern. It is a deterministic transform between a URL and a self-contained payload. The project keeps that code in `ha_mr.codec` and exposes thin worker functions in `ha_mr.service`.

The HTTP layer is now FastAPI on ASGI. Request handlers validate input, derive the public base URL, and call the worker functions through a bounded spawned `ProcessPoolExecutor`. This is actual event-loop isolation: a CPU-bound DEFLATE or QR render does not occupy the asyncio loop while other connections are being served. A semaphore bounds outstanding CPU work, creating explicit back-pressure instead of allowing unbounded work to accumulate.

> Declaring a route `async` does not make CPU work asynchronous. CPU work must either be offloaded or made non-blocking at the implementation level.

The process pool is spawned rather than forked, avoiding unsafe copying of a multi-threaded ASGI runtime into workers. The codec has no request-local state, connection state, or database handle, so it can be tested and invoked independently.

## Reddit shared-links corpus

The static V1 dictionary and benchmark use `smythp/reddit_links_dataset`, whose `test.db` is documented as a random **one-million-row** sample of outbound links posted in Reddit comments. The table includes the outbound URL plus comment metadata. The database is **not** a runtime dependency.

The split is deterministic and disjoint:

| Role | Rows | Rule |
| --- | ---: | --- |
| Training | 498,996 | Odd database IDs; used only to derive dictionary phrase counts |
| Evaluation | Held-out deterministic sample | Even IDs with `id % 101 = 0` |

The dictionary trainer retains recurring structural phrases only: protocols, hosts, short safe path prefixes, and query keys. It intentionally omits query values, URL fragments, and one-off tokens. The generated dictionary is frozen in `ha_mr/codec_dictionary.py`; the database never ships with or is opened by the application.

## Adaptive encoding decision

For each selected transport, the encoder calculates the actual payload size for three reversible candidates and selects the shortest:

| Candidate | Intended strength |
| --- | --- |
| V0 structural codec | Common domains, familiar short paths, and URL structure recognised by the original format |
| V1 raw DEFLATE | Opaque or irregular URLs, including URL forms V0 cannot represent |
| V1 Reddit-dictionary DEFLATE | Repeated patterns characteristic of links people share, such as repeated hosts, path prefixes, and query keys |

V0 remains a candidate, not a deprecated format. V1 is selected only when it wins or when V0 cannot encode the input. V1 uses an odd low bit in the packed integer, while V0 values end with an even low bit. That gives deterministic, database-free format selection and preserves existing links.

## Unicode transports

ASCII is the interoperable default. V1 emoji uses a prefix-safe one-code-point alphabet and a dedicated marker before the V1 body; it does not rely on concatenating potentially ambiguous multi-grapheme emoji. Japanese/CJK uses 4,096 one-code-point digits and therefore carries more information per visible symbol, but strict URI serializers generally percent-encode it. QR stays within the QR alphanumeric alphabet.

These modes optimise **visible-symbol count**, not guaranteed wire-byte count after every chat application, browser, or URI serializer transforms the text.

## Reproduction

1. Retrieve the Git-LFS `test.db` from the source repository.
2. Run `tools/build_reddit_dictionary.py` to derive `.build/reddit_v1_dictionary.bin` and aggregate training metadata.
3. Run `tools/embed_static_dictionary.py` to package that binary into the pure codec module.
4. Run `tools/benchmark_reddit_adaptive.py` for held-out codec measurements.
5. Run `tools/benchmark_asgi_concurrency.py` to measure bounded endpoint concurrency.

## Reference

[1] [Patrick Smyth, *reddit_links_dataset*](https://github.com/smythp/reddit_links_dataset)

## V2 and V3 semantic candidates

A second design pass examined residual structure left after V0/V1 on the held-out Reddit links. The corpus contained canonical percent escapes, long decimal runs, hexadecimal identifiers, UUIDs, and opaque Base64URL/Base62 values. V2 transforms only these recognisable forms, recording a compact marker plus length and case information before DEFLATE. It can therefore restore the original UTF-8 bytes exactly without a corpus lookup.

V3 adds a frozen 255-host codebook learned from the same odd-ID training partition. The scheme remains literal and a matching lower-case host is replaced by a one-byte index. The decoder reinserts the host from the committed table before reversing V2. The static URL dictionary and host codebook are runtime constants; the Reddit database is not required at runtime.

A Brotli experiment was also performed against raw and semantic inputs. It won only three held-out links and saved nine visible ASCII symbols in total, which was insufficient to justify a new binary dependency or another frame type. It is retained as an experiment report, not part of the encoder.

| Candidate | Scope | Selection rule |
| --- | --- | --- |
| V0 | Original URL grammar codec | Preserve when it produces the shortest payload |
| V1 | Raw and static-dictionary DEFLATE | Use for long-tail or V0-unsupported input when shorter |
| V2 | Semantic byte transform plus DEFLATE | Use only when the fully framed payload is shorter |
| V3 | V2 plus frozen-host index plus DEFLATE | Use only when the fully framed payload is shorter |

The encoder compares the final transport symbol count, including all format headers and emoji marker overhead. It does not assume that a pre-transform is beneficial merely because its input is shorter.
