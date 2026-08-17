#!/usr/bin/env python3
"""Generate a placeholder banner/logo (simple bolt on gradient) for the store page."""
import struct
import zlib
from pathlib import Path

W, H = 512, 512
BG_TOP = (30, 41, 59)      # slate
BG_BOTTOM = (15, 23, 42)
BOLT = (125, 211, 252)     # light blue


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def in_bolt(x, y):
    # simple lightning bolt polygon (normalized coords)
    p = [(0.58, 0.08), (0.30, 0.55), (0.47, 0.55), (0.40, 0.92), (0.72, 0.42), (0.53, 0.42), (0.66, 0.08)]
    inside = False
    j = len(p) - 1
    for i in range(len(p)):
        xi, yi = p[i]
        xj, yj = p[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


rows = []
for y in range(H):
    row = bytearray([0])  # filter type 0
    for x in range(W):
        color = lerp(BG_TOP, BG_BOTTOM, y / H) if not in_bolt(x / W, y / H) else BOLT
        row += bytes(color)
    rows.append(bytes(row))

raw = b"".join(rows)
png = (
    b"\x89PNG\r\n\x1a\n"
    + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    + chunk(b"IDAT", zlib.compress(raw, 9))
    + chunk(b"IEND", b"")
)

out = Path(__file__).resolve().parent.parent / "assets" / "banner.png"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(png)
print(f"wrote {out} ({len(png)} bytes)")
