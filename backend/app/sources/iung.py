"""IUNG-PIB: kategorie podatności gleb na suszę (warstwa SMSR), WCS 2.0.1, siatka 5 m, EPSG:2180.

Kody (legenda GetLegendGraphic, 21.11.2026): 1–4 = kategorie I–IV, 5 = gleby organiczne,
11 = lasy, 12 = wody, 13 = zabudowa, 14 = komunikacja i nieużytki, 19 i 99 = nieklasyfikowane,
0 i 255 = brak danych. Kod 9 występuje w danych, ale nie ma go w legendzie: liczymy go jako nieklasyfikowany.

UWAGA na osie: w EPSG:2180 (konwencja geodezyjna) oś `x` to NORTHING, a `y` to EASTING.
Subset musi więc mieć postać x(northing…) i y(easting…). Odwrotnie usługa zwraca siatkę z miejsca
oddalonego o ok. 140 km (sprawdzone porównaniem z obrazem WMS, liczebności klas zgodne co do komórki).
Odpowiedź tekstowa to zwykły raster: wiersz 0 = północ, kolumna 0 = zachód,
a „Grid bounds” podaje (easting, northing).
Pobieramy `format=text/plain` (GeoServer), żeby nie czytać GeoTIFF.
"""

from __future__ import annotations

import re
from datetime import date

import httpx
import numpy as np

from app.geo import bbox_2180, polygon_mask, to_2180
from app.models import IungSoil, Parcel
from app.sources.base import EmptyResult, SourceAdapter, fetch_bytes

URL = "https://sgeo.iung.pl/geoserver/ows"
COVERAGE = "Susza__katgl_landuse2024"
CELL_M = 5.0

CODE_TO_CLASS = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "organic",
                 11: "non_agri", 12: "non_agri", 13: "non_agri", 14: "non_agri",
                 9: "unclassified", 19: "unclassified", 99: "unclassified"}
CLASSES = ["I", "II", "III", "IV", "organic", "non_agri", "unclassified"]


def parse_text_grid(text: str) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Tekstowy wynik GeoServer → (siatka, (minx, miny, maxx, maxy)), x = easting, y = northing."""
    m = re.search(r"GeneralBounds\[\(([-\d.]+),\s*([-\d.]+)\),\s*\(([-\d.]+),\s*([-\d.]+)\)\]", text)
    if not m:
        raise ValueError("brak 'Grid bounds' w odpowiedzi IUNG")
    minx, miny, maxx, maxy = (float(v) for v in m.groups())   # GeneralBounds: (easting, northing)
    body = text.split("Band 0:", 1)[1]
    rows = [ln.split() for ln in body.strip().splitlines() if ln.strip()]
    grid = np.array(rows, dtype=float)
    nr, nc = grid.shape
    if abs((maxx - minx) / nc - (maxy - miny) / nr) > 0.01:   # komórki muszą być kwadratowe; inaczej osie są zamienione
        raise ValueError(f"niespójna siatka IUNG: {nr}×{nc} dla {maxx - minx:.0f}×{maxy - miny:.0f} m")
    return grid, (minx, miny, maxx, maxy)


def shares_on_parcel(grid: np.ndarray, bounds, ring_xy) -> IungSoil:
    minx, miny, maxx, maxy = bounds
    nr, nc = grid.shape
    cw, ch = (maxx - minx) / nc, (maxy - miny) / nr
    xs = minx + (np.arange(nc) + 0.5) * cw
    ys = maxy - (np.arange(nr) + 0.5) * ch          # wiersz 0 = północ
    mask = polygon_mask(ring_xy, xs, ys)
    if not mask.any():                              # działka węższa niż komórka: bierzemy najbliższą komórkę
        cx = sum(p[0] for p in ring_xy) / len(ring_xy)
        cy = sum(p[1] for p in ring_xy) / len(ring_xy)
        mask = np.zeros(grid.shape, bool)
        mask[int(np.clip((maxy - cy) // ch, 0, nr - 1)), int(np.clip((cx - minx) // cw, 0, nc - 1))] = True
    vals = grid[mask].astype(int)
    counts = {c: 0 for c in CLASSES}
    for code, n in zip(*np.unique(vals, return_counts=True)):
        cls = CODE_TO_CLASS.get(int(code))
        if cls:
            counts[cls] += int(n)
    total = sum(counts.values())
    if total == 0:
        raise EmptyResult("brak klasyfikacji gleby IUNG dla działki")
    shares = {c: round(n / total, 3) for c, n in counts.items()}
    agri = {c: shares[c] for c in ("I", "II", "III", "IV", "organic") if shares[c] > 0}
    dominant = max(agri, key=agri.get) if agri else None
    return IungSoil(shares=shares, dominant=dominant, n_cells=total)


class IungSoilAdapter(SourceAdapter[IungSoil]):
    name = "IUNG-PIB, kategorie gleb SMSR (WCS)"
    licence = "IUNG-PIB; brak jawnej licencji, użycie informacyjne"
    timeout_s = 4.0

    async def _fetch(self, client: httpx.AsyncClient, parcel: Parcel, as_of: date):
        ring = parcel.rings[0]
        minx, miny, maxx, maxy = bbox_2180(ring, buffer_m=CELL_M * 2)
        params = [("service", "WCS"), ("version", "2.0.1"), ("request", "GetCoverage"),
                  ("coverageId", COVERAGE), ("format", "text/plain"),
                  # x = northing, y = easting (patrz uwaga w nagłówku modułu)
                  ("subset", f"x({miny:.1f},{maxy:.1f})"), ("subset", f"y({minx:.1f},{maxx:.1f})")]
        _, _, body = await fetch_bytes(client, "GET", URL, params=params)
        text = body.decode("utf-8", "replace")
        if "ExceptionReport" in text[:500]:
            raise ValueError(re.sub(r"\s+", " ", text)[:150])
        grid, bounds = parse_text_grid(text)
        return shares_on_parcel(grid, bounds, [to_2180(lon, lat) for lon, lat in ring]), None
