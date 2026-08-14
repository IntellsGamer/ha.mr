"""Python implementation of the ha.mr reversible URL codec.

The encoded wire format deliberately matches the original JavaScript codec so
ASCII and QR payloads are interoperable with existing ha.mr links.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping, Sequence
import zlib
from urllib.parse import parse_qsl, quote, urlsplit

from .codec_dictionary import STATIC_URL_DICTIONARY
from .semantic import inverse as semantic_inverse
from .semantic import transform as semantic_transform
from .host_transform import inverse as host_inverse
from .host_transform import transform as host_transform
from .service_grammar import candidates as service_candidates
from .service_grammar import inverse as service_inverse
from .youtube_direct import pack_url as pack_youtube_url
from .youtube_direct import unpack_url as unpack_youtube_url
from .general_phrases import inverse as general_phrase_inverse
from .general_phrases import transform as general_phrase_transform
from .diverse_phrases import inverse as diverse_phrase_inverse
from .diverse_phrases import transform as diverse_phrase_transform
from .factorized_grammar import candidates as factorized_candidates
from .factorized_grammar import inverse as factorized_inverse
from .percent_protocol import inverse as percent_protocol_inverse
from .percent_protocol import transform as percent_protocol_transform
from .universal_prefix import inverse as universal_prefix_inverse
from .universal_prefix import transform as universal_prefix_transform
from .codec_data import (
    DOMAIN_ENCODE,
    OUTPUT_ALPHABET_ASCII,
    OUTPUT_ALPHABET_EMOJI,
    OUTPUT_ALPHABET_QR,
    PATH_ENCODE,
    SLD_ENCODE,
    SUBALPHABETS,
    TLD_ENCODE,
)

ASCII_ALPHABET = tuple(OUTPUT_ALPHABET_ASCII)
QR_ALPHABET = tuple(OUTPUT_ALPHABET_QR)
EMOJI_ALPHABET = tuple(OUTPUT_ALPHABET_EMOJI)
# V0's rich multi-code-point emoji entries are retained for old links. V1 uses
# a fixed single-code-point set so arbitrary adjacent digits are prefix-safe.
EMOJI_V1_ALPHABET = tuple(chr(0x1F300 + offset) for offset in range(1024))
EMOJI_V1_MARKER = "〄"  # Outside the V0 and V1 emoji digit alphabets.
# Historical one-code-point CJK transport. It stays frozen so existing links
# remain decodable. Newly emitted CJK payloads use the marked V2 alphabet below.
CJK_ALPHABET = tuple(chr(0x4E00 + offset) for offset in range(4096))
# 16,384 consecutive Han ideographs give fourteen bits per visible digit. The
# marker is outside both CJK digit ranges, making V2 unambiguous and allowing
# the decoder to select the old alphabet for unmarked payloads automatically.
CJK_V2_ALPHABET = tuple(chr(0x4E00 + offset) for offset in range(16_384))
CJK_V2_MARKER = chr(0x9FFF)

TLD_DECODE = {code: value for value, code in TLD_ENCODE.items()}
SLD_DECODE = {code: value for value, code in SLD_ENCODE.items()}
DOMAIN_DECODE = {code: value for value, code in DOMAIN_ENCODE.items()}
PATH_DECODE = {code: value for value, code in PATH_ENCODE.items()}
SLD_LIST = sorted(SLD_ENCODE, key=len, reverse=True)

# JavaScript's encodeURI(decodeURI(value)) leaves these URI delimiters intact.
_URI_SAFE = ";,/?:@&=+$,#-_.!~*'()[]%"


class CodecError(ValueError):
    """Raised when a URL or compressed payload cannot be processed."""


@dataclass(frozen=True)
class ParsedURL:
    scheme: str
    hostname: str
    port: int | None
    path: str
    query_pairs: tuple[tuple[str, str], ...]
    fragment: str


def _normalise_segment(value: str) -> str:
    """Produce a stable URI representation for an individual decoded segment."""
    return quote(value, safe=_URI_SAFE)


def _parse_url(input_url: str) -> ParsedURL:
    value = input_url.strip()
    if not value:
        raise CodecError("A URL is required.")

    # Mirror URL.canParse(input) ? new URL(input) : new URL('http://' + input).
    candidate = value if "://" in value else f"http://{value}"
    parts = urlsplit(candidate)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise CodecError("Only absolute HTTP(S) URLs are supported.")

    try:
        hostname = parts.hostname.encode("idna").decode("ascii").lower()
        port = parts.port
    except ValueError as exc:
        raise CodecError("The URL contains an invalid port.") from exc

    # WHATWG URL serialisation removes protocol-default ports.
    if (parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443):
        port = None

    return ParsedURL(
        scheme=parts.scheme,
        hostname=hostname,
        port=port,
        path=parts.path or "/",
        query_pairs=tuple(parse_qsl(parts.query, keep_blank_values=True)),
        fragment=parts.fragment,
    )


def _number_to_string(number: int, alphabet: Sequence[str]) -> str:
    if number < 0:
        raise CodecError("Cannot encode a negative value.")
    base = len(alphabet)
    output = ""
    while number > 0:
        number -= 1
        output += alphabet[number % base]
        number //= base
    return output


@lru_cache(maxsize=8)
def _reverse_transport_trie(alphabet: tuple[str, ...]) -> dict[str, object]:
    """Build a reverse trie for O(symbol length) transport parsing."""
    root: dict[str, object] = {}
    for index, symbol in enumerate(alphabet):
        node = root
        for character in reversed(symbol):
            node = node.setdefault(character, {})  # type: ignore[assignment]
        node["\0"] = (index, len(symbol))
    return root


def _take_symbol_from_end(remaining: str, alphabet: Sequence[str]) -> tuple[int, int]:
    trie = _reverse_transport_trie(tuple(alphabet))
    node: dict[str, object] = trie
    match: tuple[int, int] | None = None
    for character in reversed(remaining):
        child = node.get(character)
        if not isinstance(child, dict):
            break
        node = child
        terminal = node.get("\0")
        # The original JavaScript uses Array.find(), so the first alphabet
        # entry wins even when several symbols are valid suffixes. Preserve
        # that ordering rule rather than preferring the longest match.
        if isinstance(terminal, tuple) and (match is None or terminal[0] < match[0]):
            match = terminal
    if match is None:
        raise CodecError(f"Invalid payload character: {remaining[-1]!r}")
    return match


def _string_to_number(value: str, alphabet: Sequence[str]) -> int:
    base = len(alphabet)
    number = 0
    remaining = value
    while remaining:
        index, length = _take_symbol_from_end(remaining, alphabet)
        number = number * base + index + 1
        remaining = remaining[:-length]
    return number


def _huffman_encode(number: int, sequence: str) -> int:
    for bit in reversed(sequence):
        number <<= 1
        if bit == "1":
            number += 1
    return number


def _huffman_decode(number: int, lookup: Mapping[str, str]) -> tuple[int, str]:
    sequence = ""
    while True:
        sequence += str(number & 1)
        number >>= 1
        if len(sequence) > 20:
            raise CodecError(f"Huffman sequence is too long: {sequence!r}")
        try:
            return number, lookup[sequence]
        except KeyError:
            continue


def _choose_subalphabet(value: str) -> tuple[int, str]:
    for index, alphabet in enumerate(SUBALPHABETS[:-1]):
        if all(character in alphabet for character in value):
            return index, alphabet
    return len(SUBALPHABETS) - 1, SUBALPHABETS[-1]


def compress(input_url: str, alphabet: Sequence[str] = ASCII_ALPHABET) -> str:
    """Compress an HTTP(S) URL to a self-contained ha.mr payload."""
    url = _parse_url(input_url)
    number = 1

    hostname = url.hostname
    labels = hostname.split(".")
    tld = labels[-1] if len(labels) > 1 else ""
    if tld in TLD_ENCODE:
        hostname = ".".join(labels[:-1])

    has_www = url.hostname.startswith("www.")
    if has_www:
        hostname = hostname[4:]

    known_sld = next((value for value in SLD_LIST if hostname.endswith(value)), "")
    subdomain = hostname[: -len(known_sld)] if known_sld else ""

    path = url.path
    has_index_html = path.endswith("/index.html")
    has_index_php = path.endswith("/index.php")
    if has_index_html:
        path = path[:-11]
    elif has_index_php:
        path = path[:-10]

    segments: list[tuple[str, str]] = [
        ("path", _normalise_segment(segment))
        for segment in path.split("/")
        if segment
    ]
    segments.extend(("query", _normalise_segment(value)) for pair in url.query_pairs for value in pair)
    if url.fragment:
        segments.append(("hash", _normalise_segment(url.fragment)))

    last_segment_type = segments[-1][0] if segments else None
    query_parameter_index = 0
    for position in range(len(segments) - 1, -1, -1):
        segment_type, segment = segments[position]
        first_iteration = position == len(segments) - 1
        if not first_iteration and query_parameter_index % 2 != 1:
            number <<= 1
            if last_segment_type == "hash" and segment_type == "query":
                number += 1
            elif last_segment_type == "hash" and segment_type == "path":
                number += 1
                number <<= 1
                number += 1
            elif last_segment_type != segment_type:
                number <<= 1
                number += 1
            last_segment_type = segment_type

        if segment_type == "query":
            query_parameter_index += 1

        subalphabet_index, subalphabet = _choose_subalphabet(segment)
        huffman_number = number if first_iteration else _huffman_encode(number, PATH_ENCODE["#"])
        index = len(segment) - 1
        while index >= 0:
            if index >= 2 and segment[index - 2] == "%":
                byte = int(segment[index - 1 : index + 1], 16)
                huffman_number = _huffman_encode(huffman_number * 256 + byte, PATH_ENCODE["%"])
                index -= 3
                continue
            character = segment[index]
            if character == "~":
                huffman_number = _huffman_encode(huffman_number * 256 + 126, PATH_ENCODE["%"])
            else:
                try:
                    huffman_number = _huffman_encode(huffman_number, PATH_ENCODE[character])
                except KeyError as exc:
                    raise CodecError(f"Unsupported URL character: {character!r}") from exc
            index -= 1
        huffman_number *= len(SUBALPHABETS) + 1

        base = len(subalphabet) + 1
        subalphabet_number = number if first_iteration else number * base
        for character in reversed(segment):
            subalphabet_number = subalphabet_number * base + subalphabet.index(character) + 1
        subalphabet_number = subalphabet_number * (len(SUBALPHABETS) + 1) + subalphabet_index + 1
        number = min(huffman_number, subalphabet_number)

    if segments:
        number *= 3
        if segments[0][0] == "query":
            number += 1
        elif segments[0][0] == "hash":
            number += 2

    if not known_sld:
        if segments:
            number = _huffman_encode(number, DOMAIN_ENCODE["END"])
        for character in reversed(hostname):
            number = _huffman_encode(number, DOMAIN_ENCODE[character])
    else:
        if subdomain:
            if segments:
                number = _huffman_encode(number, DOMAIN_ENCODE["END"])
            for character in reversed(subdomain):
                number = _huffman_encode(number, DOMAIN_ENCODE[character])
        number = _huffman_encode(number, SLD_ENCODE[known_sld])

    if known_sld:
        number <<= 1
        if subdomain:
            number += 1
    number <<= 1
    if known_sld:
        number += 1

    number <<= 1
    if has_index_php:
        number += 1
    if has_index_html or has_index_php:
        number <<= 1
        number += 1

    number <<= 1
    if url.scheme == "https":
        number += 1
    number <<= 1
    if has_www:
        number += 1
    number = _huffman_encode(number, TLD_ENCODE.get(tld, TLD_ENCODE[""]))

    if url.port is not None:
        number = number * 65536 + url.port
    number <<= 1
    if url.port is not None:
        number += 1

    # Format version zero is represented by a terminating zero bit.
    number <<= 1
    return _number_to_string(number, alphabet)


def decompress(payload: str, alphabet: Sequence[str] = ASCII_ALPHABET) -> str:
    """Decode a self-contained ha.mr payload back into an absolute URL."""
    number = _string_to_number(payload, alphabet)

    # The original currently defines version zero; consume compatibility bits.
    version = 0
    while number & 1:
        version += 1
        number >>= 1
    number >>= 1

    has_port = bool(number & 1)
    number >>= 1
    port: int | None = None
    if has_port:
        port = number % 65536
        number //= 65536

    number, tld = _huffman_decode(number, TLD_DECODE)
    has_www = bool(number & 1)
    number >>= 1
    is_https = bool(number & 1)
    number >>= 1

    index_suffix = ""
    if number & 1:
        number >>= 1
        index_suffix = "/index.php" if number & 1 else "/index.html"
    number >>= 1

    has_known_sld = bool(number & 1)
    number >>= 1
    has_subdomain = False
    if has_known_sld:
        has_subdomain = bool(number & 1)
        number >>= 1

    domain = ""
    subdomain = ""
    path = ""
    if has_known_sld:
        number, domain = _huffman_decode(number, SLD_DECODE)
        if has_subdomain:
            while number > 1:
                number, digit = _huffman_decode(number, DOMAIN_DECODE)
                if digit == "END":
                    break
                subdomain += digit
    else:
        while number > 1:
            number, digit = _huffman_decode(number, DOMAIN_DECODE)
            if digit == "END":
                break
            domain += digit

    segment_type = ("path", "query", "hash")[number % 3]
    number //= 3
    query_parameter_index = 0
    while number > 1:
        if segment_type == "path":
            path += "/"
        elif segment_type == "hash":
            path += "#"
        elif query_parameter_index % 2:
            path += "="
        elif query_parameter_index == 0:
            path += "?"
        else:
            path += "&"
        if segment_type == "query":
            query_parameter_index += 1

        variant = number % (len(SUBALPHABETS) + 1)
        number //= len(SUBALPHABETS) + 1
        if variant == 0:
            while number > 1:
                number, digit = _huffman_decode(number, PATH_DECODE)
                if digit == "#" and segment_type != "hash":
                    break
                path += digit
                if digit == "%":
                    byte = number % 256
                    path += format(byte, "x")
                    number //= 256
        else:
            subalphabet = SUBALPHABETS[variant - 1]
            base = len(subalphabet) + 1
            while number > 1:
                index = number % base
                number //= base
                if index == 0:
                    break
                path += subalphabet[index - 1]

        if query_parameter_index % 2:
            continue
        if number & 1:
            if segment_type == "path":
                number >>= 1
                segment_type = "hash" if number & 1 else "query"
            else:
                segment_type = "hash"
        number >>= 1

    split_index = min((index for index in (path.find("?"), path.find("#")) if index >= 0), default=-1)
    path_before_query = path if split_index == -1 else path[:split_index]
    path_from_query = "" if split_index == -1 else path[split_index:]

    return (
        ("https://" if is_https else "http://")
        + ("www." if has_www else "")
        + subdomain
        + domain
        + (f".{tld}" if tld else "")
        + (f":{port}" if port is not None else "")
        + path_before_query
        + index_suffix
        + path_from_query
    )


def infer_alphabet(payload: str, *, qr: bool = False) -> Sequence[str]:
    """Choose the transport alphabet from a QR path or a text fragment."""
    if qr:
        return QR_ALPHABET
    if payload.startswith(CJK_V2_MARKER):
        return CJK_V2_ALPHABET
    if payload and all(character in CJK_ALPHABET for character in payload):
        return CJK_ALPHABET
    return EMOJI_ALPHABET if any(character not in ASCII_ALPHABET for character in payload) else ASCII_ALPHABET


# Adaptive frames are distinguished from V0 by the low bit of the packed
# integer. V0 always ends in zero; adaptive frames pack an odd value. Their
# byte frames are: version (1 or 2) | method (0=raw, 1=static dictionary) | stream.
# Version 2 applies the lossless semantic transform before DEFLATE.
_V1_VERSION = 1
_V2_VERSION = 2
_V3_VERSION = 3
_V4_VERSION = 4
_V5_VERSION = 5
_V7_VERSION = 7
_V8_VERSION = 8
_V11_VERSION = 11
# Compact successors omit the redundant 0x01 byte used by historic adaptive
# frames. Each begins with a non-zero version byte, so integer transport still
# preserves the header without any extra sentinel.
_COMPACT_BASE_VERSION = 16
_COMPACT_FACTORIZED_VERSION = 17
_COMPACT_SERVICE_VERSION = 18
_COMPACT_DIRECT_VERSION = 19
_COMPACT_PHRASE_VERSION = 20
_COMPACT_DIVERSE_VERSION = 21
_COMPACT_UNIVERSAL_VERSION = 22
_COMPACT_PERCENT_PROTOCOL_VERSION = 23
_COMPACT_VERSIONS = {
    _COMPACT_BASE_VERSION,
    _COMPACT_FACTORIZED_VERSION,
    _COMPACT_SERVICE_VERSION,
    _COMPACT_DIRECT_VERSION,
    _COMPACT_PHRASE_VERSION,
    _COMPACT_DIVERSE_VERSION,
    _COMPACT_UNIVERSAL_VERSION,
    _COMPACT_PERCENT_PROTOCOL_VERSION,
}
_LEGACY_ADAPTIVE_VERSIONS = {_V1_VERSION, _V2_VERSION, _V3_VERSION, _V4_VERSION, _V5_VERSION, _V7_VERSION, _V8_VERSION, _V11_VERSION}
_V1_METHOD_RAW = 0
_V1_METHOD_STATIC = 1
_MAX_V1_URL_BYTES = 65_536


def _symbol_count(value: str, alphabet: Sequence[str]) -> int:
    """Count transport symbols rather than Unicode code points."""
    count = 0
    remaining = value
    while remaining:
        _index, length = _take_symbol_from_end(remaining, alphabet)
        remaining = remaining[:-length]
        count += 1
    return count


def _deflate(url_bytes: bytes, method: int) -> bytes:
    if method == _V1_METHOD_RAW:
        compressor = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15, memLevel=9)
    elif method == _V1_METHOD_STATIC:
        compressor = zlib.compressobj(
            level=9,
            method=zlib.DEFLATED,
            wbits=-15,
            memLevel=9,
            zdict=STATIC_URL_DICTIONARY,
        )
    else:
        raise CodecError("Unknown V1 compression method.")
    return compressor.compress(url_bytes) + compressor.flush()


def _inflate(stream: bytes, method: int) -> bytes:
    try:
        if method == _V1_METHOD_RAW:
            decompressor = zlib.decompressobj(wbits=-15)
        elif method == _V1_METHOD_STATIC:
            decompressor = zlib.decompressobj(wbits=-15, zdict=STATIC_URL_DICTIONARY)
        else:
            raise CodecError("Unknown V1 compression method.")
        output = decompressor.decompress(stream, _MAX_V1_URL_BYTES + 1)
        if len(output) > _MAX_V1_URL_BYTES or decompressor.unconsumed_tail:
            raise CodecError("V1 payload expands beyond the configured URL limit.")
        output += decompressor.flush(_MAX_V1_URL_BYTES + 1 - len(output))
    except zlib.error as exc:
        raise CodecError("Invalid V1 compressed payload.") from exc
    if not decompressor.eof or len(output) > _MAX_V1_URL_BYTES:
        raise CodecError("Invalid or oversized V1 compressed payload.")
    return output


def _uses_legacy_emoji_alphabet(alphabet: Sequence[str]) -> bool:
    return tuple(alphabet) == EMOJI_ALPHABET


def _uses_cjk_v2_alphabet(alphabet: Sequence[str]) -> bool:
    return tuple(alphabet) == CJK_V2_ALPHABET


def _output_transport(alphabet: Sequence[str]) -> tuple[Sequence[str], str]:
    """Return the prefix-safe digit alphabet and any required transport marker."""
    if _uses_legacy_emoji_alphabet(alphabet):
        return EMOJI_V1_ALPHABET, EMOJI_V1_MARKER
    if _uses_cjk_v2_alphabet(alphabet):
        return CJK_V2_ALPHABET, CJK_V2_MARKER
    return alphabet, ""


def _v1_transport(payload: str, alphabet: Sequence[str]) -> tuple[str, Sequence[str]]:
    if payload.startswith(EMOJI_V1_MARKER):
        if not _uses_legacy_emoji_alphabet(alphabet):
            raise CodecError("Unexpected V1 emoji transport marker.")
        return payload[len(EMOJI_V1_MARKER):], EMOJI_V1_ALPHABET
    if payload.startswith(CJK_V2_MARKER):
        if tuple(alphabet) not in {CJK_ALPHABET, CJK_V2_ALPHABET}:
            raise CodecError("Unexpected CJK V2 transport marker.")
        return payload[len(CJK_V2_MARKER):], CJK_V2_ALPHABET
    # Explicit CJK mode must keep accepting unmarked historical base-4096 links.
    if _uses_cjk_v2_alphabet(alphabet):
        return payload, CJK_ALPHABET
    return payload, alphabet


def _pack_adaptive_frame(version: int, stream: bytes, method: int, alphabet: Sequence[str]) -> str:
    frame = bytes((version, method)) + stream
    # The leading one byte preserves zero bytes during integer conversion.
    value = int.from_bytes(b"\x01" + frame, "big")
    transport, marker = _output_transport(alphabet)
    payload = _number_to_string((value << 1) | 1, transport)
    return marker + payload


def _pack_direct_frame(version: int, value: bytes, alphabet: Sequence[str]) -> str:
    """Pack a historical fixed-layout adaptive frame that has no method byte."""
    packed = int.from_bytes(b"\x01" + bytes((version,)) + value, "big")
    transport, marker = _output_transport(alphabet)
    payload = _number_to_string((packed << 1) | 1, transport)
    return marker + payload


def _pack_compact_frame(version: int, stream: bytes, method: int, alphabet: Sequence[str]) -> str:
    """Pack a post-V11 adaptive frame without the redundant leading sentinel."""
    if version not in _COMPACT_VERSIONS:
        raise CodecError("Unknown compact adaptive frame version.")
    packed = int.from_bytes(bytes((version, method)) + stream, "big")
    transport, marker = _output_transport(alphabet)
    payload = _number_to_string((packed << 1) | 1, transport)
    return marker + payload


def _pack_compact_direct_frame(version: int, value: bytes, alphabet: Sequence[str]) -> str:
    """Pack a compact fixed-layout frame without a compression-method byte."""
    if version != _COMPACT_DIRECT_VERSION:
        raise CodecError("Unknown compact direct frame version.")
    packed = int.from_bytes(bytes((version,)) + value, "big")
    transport, marker = _output_transport(alphabet)
    payload = _number_to_string((packed << 1) | 1, transport)
    return marker + payload


def _adaptive_unpack(payload: str, alphabet: Sequence[str]) -> str:
    body, transport = _v1_transport(payload, alphabet)
    number = _string_to_number(body, transport)
    if not number & 1:
        raise CodecError("Payload is not an adaptive frame.")
    value = number >> 1
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    historical = len(raw) >= 3 and raw[0] == 1 and raw[1] in _LEGACY_ADAPTIVE_VERSIONS
    compact = len(raw) >= 2 and raw[0] in _COMPACT_VERSIONS
    if not historical and not compact:
        raise CodecError("Invalid adaptive frame header.")
    version = raw[1] if historical else raw[0]
    try:
        if version == _V5_VERSION:
            return unpack_youtube_url(raw[2:])
        if version == _COMPACT_DIRECT_VERSION:
            return unpack_youtube_url(raw[1:])
        method_offset = 2 if historical else 1
        method = raw[method_offset]
        stream = raw[method_offset + 1:]
        if version in {_V4_VERSION, _COMPACT_SERVICE_VERSION}:
            if not stream:
                raise ValueError("truncated service-prefix frame")
            prefix_index, stream = stream[0], stream[1:]
            output = service_inverse(prefix_index, _inflate(stream, method))
        elif version in {_V11_VERSION, _COMPACT_FACTORIZED_VERSION}:
            if len(stream) < 2:
                raise ValueError("truncated factorized grammar frame")
            host_index, path_index, stream = stream[0], stream[1], stream[2:]
            output = factorized_inverse(host_index, path_index, semantic_inverse(_inflate(stream, method)))
        else:
            # Compact V16 retains all historic V1/V2/V3 representations in a
            # single method family: raw=0/1, semantic=2/3, host=4/5.
            base_method = method % 2 if version == _COMPACT_BASE_VERSION else method
            output = _inflate(stream, base_method)
            if version == _V2_VERSION or (version == _COMPACT_BASE_VERSION and method in {2, 3}):
                output = semantic_inverse(output)
            elif version == _V3_VERSION or (version == _COMPACT_BASE_VERSION and method in {4, 5}):
                output = host_inverse(output)
            elif version in {_V7_VERSION, _COMPACT_PHRASE_VERSION}:
                output = general_phrase_inverse(semantic_inverse(output))
            elif version in {_V8_VERSION, _COMPACT_DIVERSE_VERSION}:
                output = diverse_phrase_inverse(semantic_inverse(output))
            elif version == _COMPACT_UNIVERSAL_VERSION:
                output = semantic_inverse(universal_prefix_inverse(output))
            elif version == _COMPACT_PERCENT_PROTOCOL_VERSION:
                output = percent_protocol_inverse(semantic_inverse(output))
        return output.decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise CodecError("Adaptive payload does not contain a valid UTF-8 URL.") from exc


def is_v1_payload(payload: str, alphabet: Sequence[str]) -> bool:
    """Return whether a transport payload belongs to any adaptive frame."""
    body, transport = _v1_transport(payload, alphabet)
    return bool(_string_to_number(body, transport) & 1)


def adaptive_payload_version(payload: str, alphabet: Sequence[str]) -> int:
    """Return 0 for legacy V0, otherwise the self-contained adaptive version."""
    body, transport = _v1_transport(payload, alphabet)
    number = _string_to_number(body, transport)
    if not number & 1:
        return 0
    raw = (number >> 1).to_bytes(((number >> 1).bit_length() + 7) // 8, "big")
    if len(raw) >= 3 and raw[0] == 1 and raw[1] in _LEGACY_ADAPTIVE_VERSIONS:
        return raw[1]
    if len(raw) >= 2 and raw[0] in _COMPACT_VERSIONS:
        return raw[0]
    raise CodecError("Invalid adaptive frame header.")


def payload_symbol_count(payload: str, alphabet: Sequence[str]) -> int:
    """Count visible transport digits, including any V1/V2 transport marker."""
    if payload.startswith((EMOJI_V1_MARKER, CJK_V2_MARKER)):
        body, transport = _v1_transport(payload, alphabet)
        return 1 + _symbol_count(body, transport)
    try:
        return _symbol_count(payload, alphabet)
    except CodecError:
        # The legacy multi-grapheme emoji list is not prefix-free. Fall back to
        # code-point count only for V0 candidate scoring; V1 avoids this issue.
        return len(payload)


def compress_adaptive(input_url: str, alphabet: Sequence[str] = ASCII_ALPHABET) -> str:
    """Emit the shortest of legacy V0, V1 raw, and V1 dictionary candidates.

    V0 is deliberately retained as a candidate: its URL-specific structure is
    much stronger than a generic compressor for common short web URLs. V1 fills
    the long-tail gap for opaque, nested, and previously unsupported inputs.
    """
    normalised = input_url.strip()
    if not normalised:
        raise CodecError("A URL is required.")
    # V1 accepts a wider long-tail set than the legacy hostname dictionary
    # parser. It validates only the absolute HTTP(S) envelope and keeps the
    # caller's original spelling for byte-exact reconstruction.
    candidate = normalised if "://" in normalised else f"http://{normalised}"
    try:
        parsed = urlsplit(candidate)
    except ValueError as exc:
        raise CodecError("The URL cannot be parsed.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise CodecError("Only absolute HTTP(S) URLs are supported.")
    candidates: list[tuple[str, int]] = []
    try:
        legacy_raw = compress(normalised, alphabet)
        # The old rich emoji alphabet is not prefix-free for arbitrary long
        # streams. Keep a V0 emoji candidate only if its legacy decoder can
        # parse it; V1 emoji is always safe and otherwise takes over.
        if _uses_legacy_emoji_alphabet(alphabet):
            decompress(legacy_raw, alphabet)
        # V0 emoji output must retain its original rich alphabet verbatim.
        # Only CJK V2 needs a marker because it replaces the historical radix.
        legacy = (CJK_V2_MARKER + legacy_raw) if _uses_cjk_v2_alphabet(alphabet) else legacy_raw
        candidates.append((legacy, payload_symbol_count(legacy, alphabet)))
    except (CodecError, ValueError):
        pass

    encoded = normalised.encode("utf-8")
    semantic = semantic_transform(encoded, opaque_tokens=True)

    # Compact V16 represents the old raw, semantic, and frozen-host paths in
    # one method family while removing their redundant leading frame byte.
    host_semantic = host_transform(encoded)
    for method in (_V1_METHOD_RAW, _V1_METHOD_STATIC):
        payload = _pack_compact_frame(_COMPACT_BASE_VERSION, _deflate(encoded, method), method, alphabet)
        candidates.append((payload, payload_symbol_count(payload, alphabet)))
        if semantic != encoded:
            payload = _pack_compact_frame(_COMPACT_BASE_VERSION, _deflate(semantic, method), 2 + method, alphabet)
            candidates.append((payload, payload_symbol_count(payload, alphabet)))
        if host_semantic != semantic:
            payload = _pack_compact_frame(_COMPACT_BASE_VERSION, _deflate(host_semantic, method), 4 + method, alphabet)
            candidates.append((payload, payload_symbol_count(payload, alphabet)))

    # V18 retains the full general service-prefix grammar while compacting the
    # frame header. Each matching prefix remains a separate exact-size choice.
    for prefix_index, suffix in service_candidates(encoded):
        for method in (_V1_METHOD_RAW, _V1_METHOD_STATIC):
            stream = bytes((prefix_index,)) + _deflate(suffix, method)
            payload = _pack_compact_frame(_COMPACT_SERVICE_VERSION, stream, method, alphabet)
            candidates.append((payload, payload_symbol_count(payload, alphabet)))

    # The direct Base64URL video-ID packing is retained as compact V19 for
    # compatibility with its historical V5 decoder, but it is only one of many
    # adaptive candidates and never displaces more general wins.
    youtube_id = pack_youtube_url(normalised)
    if youtube_id is not None:
        payload = _pack_compact_direct_frame(_COMPACT_DIRECT_VERSION, youtube_id, alphabet)
        candidates.append((payload, payload_symbol_count(payload, alphabet)))

    phrase_stream = general_phrase_transform(encoded)
    phrase_semantic = semantic_transform(phrase_stream, opaque_tokens=True)
    if phrase_semantic != encoded:
        for method in (_V1_METHOD_RAW, _V1_METHOD_STATIC):
            payload = _pack_compact_frame(_COMPACT_PHRASE_VERSION, _deflate(phrase_semantic, method), method, alphabet)
            candidates.append((payload, payload_symbol_count(payload, alphabet)))

    diverse_stream = diverse_phrase_transform(encoded)
    diverse_semantic = semantic_transform(diverse_stream, opaque_tokens=True)
    if diverse_semantic != encoded:
        for method in (_V1_METHOD_RAW, _V1_METHOD_STATIC):
            payload = _pack_compact_frame(_COMPACT_DIVERSE_VERSION, _deflate(diverse_semantic, method), method, alphabet)
            candidates.append((payload, payload_symbol_count(payload, alphabet)))

    # V17 composes independent frozen host and path/query tables. It is a
    # grammar over URL structure, not a database of destination redirects.
    for host_index, path_index, suffix in factorized_candidates(encoded):
        suffix_semantic = semantic_transform(suffix, opaque_tokens=True)
        for method in (_V1_METHOD_RAW, _V1_METHOD_STATIC):
            stream = bytes((host_index, path_index)) + _deflate(suffix_semantic, method)
            payload = _pack_compact_frame(_COMPACT_FACTORIZED_VERSION, stream, method, alphabet)
            candidates.append((payload, payload_symbol_count(payload, alphabet)))

    # Domain-neutral syntax candidates. V22 packs only the universal URL start;
    # V23 packs nested percent-encoded protocol strings commonly used by any
    # redirect or callback service. Both still compete on emitted size.
    universal = universal_prefix_transform(semantic)
    if universal != semantic:
        for method in (_V1_METHOD_RAW, _V1_METHOD_STATIC):
            payload = _pack_compact_frame(_COMPACT_UNIVERSAL_VERSION, _deflate(universal, method), method, alphabet)
            candidates.append((payload, payload_symbol_count(payload, alphabet)))
    nested_protocol = semantic_transform(percent_protocol_transform(encoded), opaque_tokens=True)
    if nested_protocol != semantic:
        for method in (_V1_METHOD_RAW, _V1_METHOD_STATIC):
            payload = _pack_compact_frame(_COMPACT_PERCENT_PROTOCOL_VERSION, _deflate(nested_protocol, method), method, alphabet)
            candidates.append((payload, payload_symbol_count(payload, alphabet)))
    return min(candidates, key=lambda item: item[1])[0]


def decompress_adaptive(payload: str, alphabet: Sequence[str] = ASCII_ALPHABET) -> str:
    """Decode legacy V0, historical adaptive frames, or compact V16+ frames."""
    if is_v1_payload(payload, alphabet):
        return _adaptive_unpack(payload, alphabet)
    body, transport = _v1_transport(payload, alphabet)
    return decompress(body, transport)


def adaptive_alphabet(name: str) -> Sequence[str]:
    """Resolve a named text transport without exposing QR-only settings."""
    transports = {
        "ascii": ASCII_ALPHABET,
        "emoji": EMOJI_ALPHABET,
        "cjk": CJK_V2_ALPHABET,
        "qr": QR_ALPHABET,
    }
    try:
        return transports[name]
    except KeyError as exc:
        raise CodecError("mode must be one of: ascii, emoji, cjk, qr") from exc
