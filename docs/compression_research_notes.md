# Compression Research Notes for a Self-Contained URL Codec

## Sources reviewed

1. [RFC 7541: HPACK](https://datatracker.ietf.org/doc/html/rfc7541)
2. [RFC 9204: QPACK](https://www.rfc-editor.org/rfc/rfc9204.html)
3. [Data Compression, Section 3](https://ics.uci.edu/~dhirschb/pubs/DC-Sec3.html)
4. [FiniteStateEntropy project](https://github.com/cyan4973/FiniteStateEntropy)

## Relevant design findings

HPACK represents structured fields through a mixture of indexed entries and literal values. Its static table is predefined, read-only, always available to encoder and decoder, and handles recurring structures without dynamic database state. HPACK also combines this with static Huffman literal coding. The transferable lesson is to make every structured component independently eligible for either a frozen-table index or a literal encoding, with the encoder choosing the smaller complete result.

QPACK reinforces that references to static table entries require no dynamic state. Its decoder treats invalid table references as errors, and table capacities or parsing bounds are explicit. For ha.mr, this supports frozen grammar/table references only, bounded indices, and strict rejection of malformed frames; a dynamic table is incompatible with independent self-contained URLs.

The University of California Irvine compression material explains a key small-message constraint: dynamic Huffman models can be theoretically optimal for a message but lose in practice once their mapping overhead is transmitted. It recommends prior-agreed codebooks for stable source classes, selected with a small identifier. It also documents that Huffman is optimal under a static mapping model, whereas arithmetic coding can approach entropy but requires an explicit probability model.

Finite State Entropy documentation describes ANS/FSE as approaching arithmetic-coding precision at high speed, while Huffman cannot represent probabilities below one bit per symbol. For ha.mr, a frozen static model is the only viable direction: per-payload model transmission would cost too much for URLs.

## Engineering implications

A prospective custom frame should use a frozen, domain-neutral URL alphabet model and component grammar. Candidate format: a compact bitstream with scheme/authority/path/query/fragment field tags; static indexes for frozen phrase/host/path entries; length-delimited literals entropy-coded under a frozen URL character model; and fixed universal integer codes for lengths and indexes. It must be compared as a whole against V0 and every existing adaptive frame, because small-message overhead can erase theoretical gains.

Any implementation must preserve bounded decompression, reject invalid indices and trailing bits, and keep historical frames decodable.

## References

[1] RFC 7541: HPACK: Header Compression for HTTP/2 — https://datatracker.ietf.org/doc/html/rfc7541

[2] RFC 9204: QPACK: Field Compression for HTTP/3 — https://www.rfc-editor.org/rfc/rfc9204.html

[3] Data Compression, Section 3 — https://ics.uci.edu/~dhirschb/pubs/DC-Sec3.html

[4] FiniteStateEntropy — https://github.com/cyan4973/FiniteStateEntropy
