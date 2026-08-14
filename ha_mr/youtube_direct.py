"""Direct V5 representation for canonical YouTube watch links.

A normal watch URL contains a fixed literal grammar plus an eleven-character
Base64URL video identifier. The identifier has exactly 66 bits of information,
so V5 stores those bits directly rather than applying a general compressor to
a very short suffix.
"""

from __future__ import annotations

PREFIX = "https://www.youtube.com/watch?v="
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
INDEX = {character: value for value, character in enumerate(ALPHABET)}
PACKED_BYTES = 9


def pack_url(url: str) -> bytes | None:
    """Return nine exact bytes for a canonical watch URL, otherwise ``None``."""
    if not url.startswith(PREFIX):
        return None
    video_id = url[len(PREFIX):]
    if len(video_id) != 11 or any(character not in INDEX for character in video_id):
        return None
    value = 0
    for character in video_id:
        value = (value << 6) | INDEX[character]
    return value.to_bytes(PACKED_BYTES, "big")


def unpack_url(packed: bytes) -> str:
    """Restore the canonical watch URL from its nine-byte video-ID payload."""
    if len(packed) != PACKED_BYTES:
        raise ValueError("invalid YouTube direct frame length")
    value = int.from_bytes(packed, "big")
    output = ["A"] * 11
    for position in range(10, -1, -1):
        value, digit = divmod(value, 64)
        output[position] = ALPHABET[digit]
    return PREFIX + "".join(output)
