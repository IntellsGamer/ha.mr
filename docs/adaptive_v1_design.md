# Adaptive codec experiment: V1 design

The original V0 codec is already extremely effective for familiar domains and short ordinary paths, but the real-URL benchmark exposed two weaknesses: it cannot encode every URL form accepted by a browser, and it loses efficiency on long query strings, opaque tokens, nested redirect URLs, and other high-entropy segments.

## Observed baseline

The deterministic 5,000-URL sample from Ada’s public URL corpus contained **4,640 URLs encoded by V0** and **360 unsupported URLs**. Across V0 successes, the mean payload/input ratio was **0.565** and the median was **0.594**. Query-heavy URLs averaged **0.768**, while the small set of 300+-character URLs averaged **0.826**. The source corpus is kept outside the application; it is used only for reproducible experiment scripts.

## Chosen V1 strategy

V1 is an **adaptive candidate codec**, not a replacement for V0. For a given transport alphabet it evaluates these fully reversible candidates and emits the shortest actual payload:

| Candidate | Best use | Method |
| --- | --- | --- |
| V0 structural codec | Common hosts and structured short URLs | Existing domain, path-segment, subalphabet, and Huffman logic |
| V1 raw DEFLATE | Long, irregular, or previously unsupported URLs | Raw DEFLATE over UTF-8 URL bytes |
| V1 static-dictionary DEFLATE | Tracking-heavy and repeated web phrases | Raw DEFLATE seeded with a frozen 28 KB URL phrase dictionary trained on a disjoint corpus slice |

V1 carries a byte-level method selector before the raw DEFLATE stream. A sentinel byte preserves leading zeroes while converting the binary frame into the selected printable alphabet. The decoder reads the V1 marker, reverses base conversion, chooses the raw or dictionary-backed DEFLATE path, and reconstructs the original UTF-8 URL. Existing V0 payloads continue to use their original decoder unchanged.

## Unicode transports

Compression must be measured in the right unit. A Japanese/CJK symbol can carry far more information than an ASCII character, but it is usually percent-encoded when copied into a strict URI context. Therefore V1 exposes non-ASCII as **explicit display/share transports**, not as a claim that the byte representation is universally shorter.

| Transport | Radix | Intended use | Important limitation |
| --- | ---:| --- | --- |
| ASCII | 84 | Conventional copy/paste links | Most interoperable; fewest bits per visible symbol |
| Existing emoji alphabet | 3,953 | High-density, expressive text links | Multi-code-point graphemes; URL serialisers may expand them |
| Japanese/CJK alphabet | 4,096 | Highest-density one-code-point text representation | Will usually percent-encode in URI-only channels; not QR-alphanumeric compatible |
| QR alphabet | 45 | QR mode | Must remain restricted to QR alphanumeric characters |

On the final 5,000-URL implementation benchmark, adaptive CJK output required **157,853 visible symbols**, compared with **167,335 for safe V1 emoji** and **294,182 for adaptive ASCII**. The V0 structural codec remained the winner on 4,638 familiar URLs in ASCII and CJK modes; the V1 codecs supply the long-tail coverage and win the difficult URL classes.

## Marker and compatibility rule

V1 is marked by an odd low bit in the packed integer; V0 values always terminate with an even low bit. ASCII, CJK, and QR reuse that numeric discriminator directly. V1 emoji additionally begins with a dedicated marker and uses a prefix-safe one-code-point alphabet, avoiding the ambiguity inherent in concatenating rich multi-grapheme emoji entries. This makes format selection deterministic, preserves old links, and avoids a database or a lookup service.

## Security and operational notes

The static dictionary is frozen and committed with the application; it is not trained at runtime and does not contain user-submitted URLs. All codecs are self-contained, deterministic, and still expose the destination to anyone who can decode the payload. The feature is compression, not secrecy.
