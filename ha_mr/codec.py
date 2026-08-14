"""Python implementation of the ha.mr reversible URL codec.

The encoded wire format deliberately matches the original JavaScript codec so
ASCII and QR payloads are interoperable with existing ha.mr links.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence
from urllib.parse import parse_qsl, quote, urlsplit

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


def _string_to_number(value: str, alphabet: Sequence[str]) -> int:
    base = len(alphabet)
    number = 0
    remaining = value
    while remaining:
        index = next((i for i, symbol in enumerate(alphabet) if remaining.endswith(symbol)), -1)
        if index < 0:
            raise CodecError(f"Invalid payload character: {remaining[-1]!r}")
        number = number * base + index + 1
        remaining = remaining[: -len(alphabet[index])]
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
    """Choose the original project’s payload alphabet from its transport form."""
    if qr:
        return QR_ALPHABET
    return EMOJI_ALPHABET if any(character not in ASCII_ALPHABET for character in payload) else ASCII_ALPHABET
