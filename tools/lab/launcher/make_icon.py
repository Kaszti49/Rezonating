"""Draw the Lab's brand mark (the rail logo: a wave on a dark rounded square) into rezonating-lab.ico.

Run once with the repo's venv: ``.venv\\Scripts\\python.exe tools\\lab\\launcher\\make_icon.py``. PNG images inside
the ICO (fine since Windows Vista); numpy + the standard library only.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

# the rail logo's path in a 32-unit box: M3 17 h5 l3 -9 5 17 4 -14 3 6 h6
WAVE = [(3, 17), (8, 17), (11, 8), (16, 25), (20, 11), (23, 17), (29, 17)]
BG = (26, 34, 44)
ACCENT = (76, 201, 240)


def render(size: int, ss: int = 4) -> np.ndarray:
    n = size * ss
    u = (np.arange(n) + 0.5) / n * 32.0
    x, y = np.meshgrid(u, u)
    # rounded square (radius 6 of 32)
    r = 6.0
    dx = np.clip(np.maximum(r - x, x - (32 - r)), 0, None)
    dy = np.clip(np.maximum(r - y, y - (32 - r)), 0, None)
    inside = (dx**2 + dy**2) <= r**2
    # distance to the wave polyline
    d = np.full_like(x, 1e9)
    for (ax, ay), (bx, by) in zip(WAVE, WAVE[1:], strict=False):
        vx, vy = bx - ax, by - ay
        t = np.clip(((x - ax) * vx + (y - ay) * vy) / (vx * vx + vy * vy), 0, 1)
        d = np.minimum(d, np.hypot(x - ax - t * vx, y - ay - t * vy))
    line = d <= 1.5  # stroke width 3
    rgba = np.zeros((n, n, 4))
    rgba[inside] = (*BG, 255)
    rgba[inside & line] = (*ACCENT, 255)
    rgba = rgba.reshape(size, ss, size, ss, 4).mean(axis=(1, 3))
    return np.clip(np.rint(rgba), 0, 255).astype(np.uint8)


def png(img: np.ndarray) -> bytes:
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[i].tobytes() for i in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    sizes = [16, 32, 48, 256]
    images = [png(render(s)) for s in sizes]
    head = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, data in zip(sizes, images, strict=True):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out = Path(__file__).with_name("rezonating-lab.ico")
    out.write_bytes(head + entries + b"".join(images))
    print(out)


if __name__ == "__main__":
    main()
