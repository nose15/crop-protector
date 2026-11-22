"""Minimalny czytnik Cloud Optimized GeoTIFF (Sentinel-2 L2A z Earth Search) bez rasterio/GDAL.

Obsługuje dokładnie to, co mają pliki sentinel-2-c1-l2a (sprawdzone 21.11.2026): klasyczny TIFF (nie BigTIFF),
kafle 1024×1024, uint16 albo uint8, kompresja deflate (8), predyktor poziomy (2), georeferencja przez
ModelTiepoint + PixelScale. Pobieramy nagłówek i tylko kafle przecinające okno działki (HTTP Range).
"""

from __future__ import annotations

import asyncio
import struct
import zlib

import httpx
import numpy as np

from app.sources.base import SourceError

HEADER_BYTES = 65536
_TYPES = {1: ("B", 1), 2: ("c", 1), 3: ("H", 2), 4: ("I", 4), 12: ("d", 8), 16: ("Q", 8)}


async def _range(client: httpx.AsyncClient, url: str, start: int, length: int) -> bytes:
    r = await client.get(url, headers={"Range": f"bytes={start}-{start + length - 1}"})
    if r.status_code not in (200, 206):
        raise SourceError(f"COG: HTTP {r.status_code}")
    return r.content


async def read_header(client: httpx.AsyncClient, url: str) -> dict:
    b = await _range(client, url, 0, HEADER_BYTES)
    bo = "<" if b[:2] == b"II" else ">"
    if struct.unpack(bo + "H", b[2:4])[0] != 42:
        raise SourceError("COG: obsługiwany jest tylko klasyczny TIFF")
    off = struct.unpack(bo + "I", b[4:8])[0]
    n = struct.unpack(bo + "H", b[off:off + 2])[0]
    tags = {}
    for i in range(n):
        e = b[off + 2 + 12 * i: off + 14 + 12 * i]
        tag, typ, cnt = struct.unpack(bo + "HHI", e[:8])
        fmt, sz = _TYPES.get(typ, ("B", 1))
        if sz * cnt <= 4:
            raw = e[8:8 + sz * cnt]
        else:
            o = struct.unpack(bo + "I", e[8:12])[0]
            raw = b[o:o + sz * cnt]
            if len(raw) < sz * cnt:                       # tablica poza pobranym nagłówkiem
                raw = await _range(client, url, o, sz * cnt)
        tags[tag] = raw.decode(errors="ignore") if typ == 2 else struct.unpack(bo + fmt * cnt, raw)
    if tags.get(259, (1,))[0] != 8:
        raise SourceError("COG: oczekiwana kompresja deflate")
    return {"bo": bo, "width": tags[256][0], "height": tags[257][0], "bits": tags[258][0],
            "predictor": tags.get(317, (1,))[0], "tw": tags[322][0], "th": tags[323][0],
            "offsets": tags[324], "counts": tags[325], "x0": tags[33922][3], "y0": tags[33922][4],
            "res": tags[33550][0]}


def _decode_tile(h: dict, raw: bytes) -> np.ndarray:
    dt = np.dtype(h["bo"] + ("u2" if h["bits"] == 16 else "u1"))
    a = np.frombuffer(zlib.decompress(raw), dtype=dt).reshape(h["th"], h["tw"]).astype(np.int64)
    if h["predictor"] == 2:                               # predyktor poziomy: różnice w wierszu
        a = np.cumsum(a, axis=1) & (0xFFFF if h["bits"] == 16 else 0xFF)
    return a


async def read_window(client: httpx.AsyncClient, url: str, x_min: float, y_min: float, x_max: float, y_max: float,
                      header: dict | None = None) -> tuple[np.ndarray, float, float, float]:
    """Okno [x_min, x_max] × [y_min, y_max] (metry, układ pliku) → (tablica, x lewej krawędzi, y górnej krawędzi, rozdzielczość)."""
    h = header or await read_header(client, url)
    res = h["res"]
    c0 = max(int((x_min - h["x0"]) // res), 0)
    c1 = min(int((x_max - h["x0"]) // res) + 1, h["width"])
    r0 = max(int((h["y0"] - y_max) // res), 0)
    r1 = min(int((h["y0"] - y_min) // res) + 1, h["height"])
    if c0 >= c1 or r0 >= r1:
        raise SourceError("COG: działka poza zasięgiem sceny")
    tiles_x = (h["width"] + h["tw"] - 1) // h["tw"]
    need = [(tr, tc) for tr in range(r0 // h["th"], (r1 - 1) // h["th"] + 1)
            for tc in range(c0 // h["tw"], (c1 - 1) // h["tw"] + 1)]
    raws = await asyncio.gather(*(_range(client, url, h["offsets"][tr * tiles_x + tc], h["counts"][tr * tiles_x + tc])
                                  for tr, tc in need))
    out = np.zeros((r1 - r0, c1 - c0), dtype=np.int64)
    for (tr, tc), raw in zip(need, raws):
        tile = _decode_tile(h, raw)
        tr0, tc0 = tr * h["th"], tc * h["tw"]
        rs, re_ = max(r0, tr0), min(r1, tr0 + h["th"])
        cs, ce = max(c0, tc0), min(c1, tc0 + h["tw"])
        out[rs - r0:re_ - r0, cs - c0:ce - c0] = tile[rs - tr0:re_ - tr0, cs - tc0:ce - tc0]
    return out, h["x0"] + c0 * res, h["y0"] - r0 * res, res
