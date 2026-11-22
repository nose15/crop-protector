"""Sentinel-2 L2A (Earth Search STAC, kolekcja sentinel-2-c1-l2a): NDMI i NDVI na działce w sezonie dnia D.

TYMCZASOWE podpięcie (21.11.2026), do oceny czy warto (docs/sentinel.md). Co pobieramy:
  - tryb lekki (/api/context): NDMI = (B8A − B11) / (B8A + B11), woda w roślinach, dla 3 najnowszych czystych scen;
  - tryb pełny (app/prefetch.py, do cache): do 20 scen, dodatkowo NDRE = (B8A − B05) / (B8A + B05) (zieleń, pasma
    20 m) i NDVI = (B08 − B04) / (B08 + B04) z pasm 10 m dla najnowszej sceny.
Odbicie = DN · 10⁻⁴ − 0,1 (offset kolekcji c1). Czyste piksele: SCL 4 (roślinność) i 5 (goła gleba).
Scena musi w całości obejmować działkę (kafle Sentinela się nakładają; działka na krawędzi kafla bywa ucięta).
Po LIMIT_S zwracamy sceny, które zdążyły się pobrać (status partial).
"""

from __future__ import annotations

import asyncio
from datetime import date

import httpx
import numpy as np

from app.geo import polygon_mask, to_utm
from app.models import Parcel
from app.sources import cog
from app.sources.base import EmptyResult, SourceAdapter, fetch_bytes

STAC_URL = "https://earth-search.aws.element84.com/v1/search"
# Koszt: kafel pasma 20 m ≈ 0,35 MB, SCL ≈ 75 kB, pasma 10 m ≈ 1,1 MB (zmierzone 21.11.2026). Wycinka mniejszego
# niż kafel nie da się pobrać (kompresja deflate obejmuje cały kafel), więc rozmiar zależy od liczby kafli.
N_SCENES = 3            # tryb lekki: tyle czystych scen liczymy (tylko NDMI: 2 pasma) → ok. 2 MB na działkę
N_CANDIDATES = 8        # tyle najnowszych scen sprawdzamy maską chmur (SCL)
MAX_SCENE_CLOUD = 40
MIN_CLEAR_FRAC = 0.6
LIMIT_S = 13.0


def season_of(d: date) -> tuple[date, date]:
    y = d.year if d >= date(d.year, 4, 1) else d.year - 1
    return date(y, 4, 1), min(date(y, 9, 30), d)


def _epsg(item: dict) -> int:
    return int(str(item["properties"].get("proj:code") or item["properties"].get("proj:epsg")).split(":")[-1])


def _covers(item: dict, ring: list[list[float]]) -> bool:
    w, s, e, n = item["bbox"]
    return all(w <= lon <= e and s <= lat <= n for lon, lat in ring)


def _refl(a: np.ndarray) -> np.ndarray:
    return a * 1e-4 - 0.1


def _mask(arr, x0, y0, res, ring_xy):
    xs = x0 + (np.arange(arr.shape[1]) + 0.5) * res
    ys = y0 - (np.arange(arr.shape[0]) + 0.5) * res
    return polygon_mask(ring_xy, xs, ys)


def _geom(item: dict, ring: list[list[float]]):
    epsg = _epsg(item)
    xy = [to_utm(lon, lat, epsg) for lon, lat in ring]
    return xy, (min(p[0] for p in xy), min(p[1] for p in xy), max(p[0] for p in xy), max(p[1] for p in xy))


async def _clear_mask(client, item: dict, ring) -> dict | None:
    """Etap 1: tylko SCL (mały plik). Zwraca opis sceny z maską czystych pikseli albo None (brak danych)."""
    xy, bb = _geom(item, ring)
    scl = await cog.read_window(client, item["assets"]["scl"]["href"], *bb)
    m20 = _mask(*scl, xy)
    if not m20.any() or ((scl[0] == 0) & m20).sum() > 0.05 * m20.sum():
        return None                                           # działka poza sceną albo na krawędzi pasa przelotu
    clear = m20 & np.isin(scl[0], [4, 5])
    return {"item": item, "xy": xy, "bb": bb, "clear": clear, "frac": float(clear.sum() / m20.sum())}


async def _indices20(client, sc: dict, with_ndre: bool) -> tuple[float, float | None]:
    """Etap 2: NDMI (zawsze) i NDRE (tryb pełny) z pasm 20 m na czystych pikselach."""
    a = sc["item"]["assets"]
    keys = ("nir08", "swir16", "rededge1") if with_ndre else ("nir08", "swir16")
    bands = await asyncio.gather(*(cog.read_window(client, a[k]["href"], *sc["bb"]) for k in keys))
    r8, r11 = _refl(bands[0][0][sc["clear"]]), _refl(bands[1][0][sc["clear"]])
    ndmi = round(float(np.mean((r8 - r11) / (r8 + r11))), 3)
    if not with_ndre:
        return ndmi, None
    r5 = _refl(bands[2][0][sc["clear"]])
    return ndmi, round(float(np.mean((r8 - r5) / (r8 + r5))), 3)


async def _ndvi(client, sc: dict) -> float:
    """Etap 3: NDVI z pasm 10 m (cała działka; scena wybrana jako czysta)."""
    a = sc["item"]["assets"]
    red, nir = await asyncio.gather(*(cog.read_window(client, a[k]["href"], *sc["bb"]) for k in ("red", "nir")))
    m10 = _mask(*red, sc["xy"])
    rr, nn = _refl(red[0][m10]), _refl(nir[0][m10])
    return round(float(np.mean((nn - rr) / (nn + rr))), 3)


async def _within(tasks: list, deadline: float) -> list:
    """Czeka na zadania do `deadline` (czas pętli); niedokończone anuluje. Zwraca wyniki albo None."""
    loop = asyncio.get_running_loop()
    if not tasks:
        return []
    done, pending = await asyncio.wait(tasks, timeout=max(deadline - loop.time(), 0.1))
    for t in pending:
        t.cancel()
    return [t.result() if t in done and not t.exception() else None for t in tasks]


class SatelliteAdapter(SourceAdapter[dict]):
    name = "Sentinel-2 L2A (Earth Search STAC)"
    licence = "Copernicus Sentinel data, bezpłatnie (dane zmodyfikowane)"

    def __init__(self, full: bool = False):
        """full=True: pobranie do cache – więcej scen, dłuższy limit, dodatkowo NDVI z pasm 10 m."""
        self.full = full
        self.n_scenes = 20 if full else N_SCENES
        self.n_candidates = 40 if full else N_CANDIDATES
        self.limit_s = 120.0 if full else LIMIT_S
        self.timeout_s = self.limit_s + 5

    async def _fetch(self, client: httpx.AsyncClient, parcel: Parcel, as_of: date):
        import json
        start, end = season_of(as_of)
        ring = parcel.rings[0]
        _, _, body = await fetch_bytes(client, "POST", STAC_URL, json={
            "collections": ["sentinel-2-c1-l2a"], "intersects": {"type": "Polygon", "coordinates": [ring]},
            "datetime": f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z", "limit": 200,
            "query": {"eo:cloud_cover": {"lt": MAX_SCENE_CLOUD}},
            "fields": {"include": ["id", "bbox", "properties.datetime", "properties.eo:cloud_cover", "properties.proj:code",
                                   "properties.proj:epsg", "assets.red.href", "assets.nir.href", "assets.nir08.href",
                                   "assets.swir16.href", "assets.rededge1.href", "assets.scl.href"]}})
        items = [f for f in json.loads(body).get("features", []) if _covers(f, ring)]
        by_date: dict[str, dict] = {}
        for f in sorted(items, key=lambda f: f["properties"].get("eo:cloud_cover", 100)):
            by_date.setdefault(f["properties"]["datetime"][:10], f)       # jedna (najmniej zachmurzona) scena na dzień
        cands = [by_date[d] for d in sorted(by_date, reverse=True)[:self.n_candidates]]
        if not cands:
            raise EmptyResult(f"brak scen bez chmur w sezonie {start.year}")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.limit_s
        masks = await _within([asyncio.create_task(_clear_mask(client, it, ring)) for it in cands], deadline)
        checked = [m for m in masks if m]
        clear = [m for m in checked if m["frac"] >= MIN_CLEAR_FRAC][:self.n_scenes]   # najnowsze czyste
        idx = await _within([asyncio.create_task(_indices20(client, m, self.full)) for m in clear], deadline)
        ndvi = None
        if clear and self.full:
            ndvi = (await _within([asyncio.create_task(_ndvi(client, clear[0]))], deadline))[0]
        obs = [{"date": m["item"]["properties"]["datetime"][:10], "scene": m["item"]["id"],
                "valid_frac": round(m["frac"], 2), "ndmi": idx[i][0], "ndre": idx[i][1], "ndvi": ndvi if i == 0 else None}
               for i, m in enumerate(clear) if idx[i] is not None]
        cloudy = sorted(m["item"]["properties"]["datetime"][:10] for m in checked if m["frac"] < MIN_CLEAR_FRAC)
        obs.sort(key=lambda o: o["date"])
        if not any(o["ndmi"] is not None for o in obs):
            raise EmptyResult("w ostatnich scenach działka była zasłonięta przez chmury")
        incomplete = len(checked) < len(cands) or any(v is None for v in idx) or (self.full and clear and ndvi is None)
        result = {"season": start.year, "obs": obs, "cloudy_dates": cloudy, "scenes_found": len(by_date),
                  "scenes_checked": len(checked),
                  "scenes_clear": len(clear), "partial": bool(incomplete), "mode": "pelny" if self.full else "lekki"}
        last = max(o["date"] for o in obs if o["ndmi"] is not None)
        return result, date.fromisoformat(last)
