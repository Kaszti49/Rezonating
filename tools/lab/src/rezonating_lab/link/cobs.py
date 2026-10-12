"""COBS exactly as pinned in PROTOCOL.md section 2.

Differences from the textbook algorithm, all deliberate:

* a final block of exactly 254 non-zero bytes gets *no* extra code byte after it
  (254 x 0x01 encodes to 255 bytes: ``FF 01 ... 01``);
* a raw frame that ends in ``0x00`` gets a final empty block, written as ``01``
  (``01 00`` encodes to ``02 01 01``).

The delimiter ``0x00`` is not part of the encoding; the caller appends it.
"""

from __future__ import annotations

MAX_BLOCK = 254


class CobsError(ValueError):
    """The input is not a valid COBS encoding."""


def encode(raw: bytes) -> bytes:
    """COBS-encode a non-empty raw frame. The result contains no 0x00 byte."""
    n = len(raw)
    if n == 0:
        raise ValueError("an empty raw frame never occurs (minimum 6 bytes)")
    out = bytearray()
    find = raw.find
    i = 0
    while i < n:
        limit = min(n, i + MAX_BLOCK)
        j = find(0, i, limit)
        if j < 0:
            # No zero in the next (up to) 254 bytes: a full block, or the final short block.
            run = limit - i
            out.append(run + 1)
            out += raw[i:limit]
            i = limit
        else:
            out.append(j - i + 1)
            out += raw[i:j]
            i = j + 1
            if i == n:
                out.append(1)  # the frame ends in 0x00: final empty block
    return bytes(out)


def decode(enc: bytes) -> bytes:
    """Inverse of :func:`encode`. Raises :class:`CobsError` on malformed input."""
    n = len(enc)
    if n == 0:
        raise CobsError("empty chunk")
    out = bytearray()
    i = 0
    while i < n:
        code = enc[i]
        if code == 0:
            raise CobsError("zero code byte")
        end = i + code
        if end > n:
            raise CobsError("block runs past the end of the chunk")
        block = enc[i + 1 : end]
        if 0 in block:
            raise CobsError("zero byte inside a block")
        out += block
        i = end
        if i < n and code != 0xFF:
            out.append(0)  # implied zero between blocks (not after a full 254-byte block)
    return bytes(out)
