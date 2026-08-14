# Static Context Arithmetic Frames: V24 and V26

## Purpose

The V24 and V26 frames add a **purpose-built, self-contained entropy codec** to ha.mr. They are designed for URLs whose byte patterns are predictable enough for a frozen URL grammar model to beat the existing structural encoder and DEFLATE candidates. They do not contain a destination lookup, dynamic state, redirect database, or per-user history.

> The encoder is free to emit an arithmetic frame only when the complete transport payload is smaller than every other candidate. The adaptive selector therefore retains all previously existing wins.

## Design basis

A dynamic Huffman model can lose on short messages because the model description must be sent with the data. Stable, pre-agreed models avoid that overhead and are particularly appropriate when the encoder and decoder can ship the same read-only table.[1] HPACK and QPACK apply the same principle to structured fields by combining static indexed entries with literal representations; their static table requires no dynamic decoder state.[2] [3]

Arithmetic coding supports finer probability allocations than a one-bit-per-symbol Huffman boundary, when both ends share a fixed model.[4] ha.mr uses this capability only under frozen tables and strict output limits.

| Frame | Wire payload after version/method | Decoder operation |
|---|---|---|
| **V24** | `varint(output_length) || arithmetic_stream` | Decode raw URL bytes under the frozen context model. |
| **V26** | `host_index || path_index || varint(suffix_length) || arithmetic_stream` | Recover the frozen host/path prefix, seed the model state from that prefix, then decode only the literal suffix. |

The existing integer-to-alphabet transport wraps both frames unchanged. The low adaptive marker bit, historical decoder paths, ASCII transport, emoji transport, and marked CJK V2 transport remain compatible.

## Frozen model

The model is trained only on the odd-ID training split of `smythp/reddit_links_dataset` and is emitted as a compressed Python constant in `ha_mr/context_model.py`. It contains 400 cumulative-frequency contexts derived from the product of eight URL grammar states and 50 preceding-byte classes.

The grammar states distinguish scheme, slash transition, authority, path, query key, query value, and fragment positions. The preceding-byte class captures lowercase letters, digits, high-value URL punctuation, uppercase letters, and an other-byte class. Every raw byte receives a nonzero probability floor, so arbitrary valid UTF-8 URL text remains encodable rather than being restricted to the corpus vocabulary.

## Production safeguards

The decoder accepts at most 65,536 reconstructed bytes. V24/V26 length prefixes are capped to three bytes and rejected if they exceed that bound. V26 validates frozen host/path indexes through the existing factorized grammar inverse. Arithmetic decoding uses bounded binary-search symbol lookup and raises an error for an invalid decoded symbol.

| Property | Production behavior |
|---|---|
| Redirect state | None; all reconstruction data is in payload and shipped frozen tables. |
| Model adaptation | None; every payload decodes independently. |
| Output expansion | Hard-capped at 65,536 bytes. |
| Table index validation | Frozen factorized grammar rejects unknown indices. |
| Historical payloads | Legacy V0 and all previously emitted adaptive frames remain decodable. |
| Candidate policy | Minimum emitted transport symbol count wins. |

## Validation

The held-out Reddit evaluation runs on even IDs satisfying `id % 101 = 0`; no individual URLs are written to reports. The benchmark measures V24 and V26 against every pre-existing adaptive candidate and validates exact adaptive round trips. Application regressions cover a public V24 nested redirect shape and a public V26 deep-path shape. The ASGI benchmark runs the normal `/api/compress` workload through the process pool.

## References

[1] [Data Compression, Section 3 — Static Huffman coding and model overhead](https://ics.uci.edu/~dhirschb/pubs/DC-Sec3.html)

[2] [RFC 7541 — HPACK static table and Huffman encoding](https://datatracker.ietf.org/doc/html/rfc7541)

[3] [RFC 9204 — QPACK static table](https://www.rfc-editor.org/rfc/rfc9204.html)

[4] [Finite State Entropy — entropy coding background](https://github.com/cyan4973/FiniteStateEntropy)
