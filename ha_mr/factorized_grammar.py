"""General compositional host and path-prefix grammar used by V11."""

from __future__ import annotations

from .factorized_codebook import HOST_PREFIXES, PATH_PREFIXES

_HOST_LOOKUP = {prefix: index for index, prefix in enumerate(HOST_PREFIXES)}
_PATHS_LONGEST = tuple(sorted(enumerate(PATH_PREFIXES), key=lambda item: len(item[1]), reverse=True))


def candidates(data: bytes) -> tuple[tuple[int, int, bytes], ...]:
    """Return every useful host/path-prefix decomposition of *data*.

    The host lookup is exact and the path table is examined longest-first. Each
    returned suffix is literal URL data and will be semantically transformed and
    compressed by the caller. The tables are frozen in the decoder package.
    """
    output: list[tuple[int, int, bytes]] = []
    for host, host_index in _HOST_LOOKUP.items():
        if not data.startswith(host):
            continue
        remainder = data[len(host):]
        for path_index, path in _PATHS_LONGEST:
            if remainder.startswith(path):
                output.append((host_index, path_index, remainder[len(path):]))
    return tuple(output)


def inverse(host_index: int, path_index: int, suffix: bytes) -> bytes:
    """Reassemble one V11 factorized grammar value."""
    if host_index >= len(HOST_PREFIXES) or path_index >= len(PATH_PREFIXES):
        raise ValueError("unknown factorized grammar index")
    return HOST_PREFIXES[host_index] + PATH_PREFIXES[path_index] + suffix
