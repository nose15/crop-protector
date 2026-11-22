"""Analiza terenu działki z NMT GUGiK (przeniesione z prototypu): spadki, zagłębienia (gdzie stoi woda), spływ i propozycje miejsc.

Dane: NMT siatka 1 m z usługi WCS Geoportalu (ASCII Grid), pobierany w EPSG:3857, żeby rastry
nakładały się 1:1 na mapę Leaflet. Obliczenia w numpy (bez GDAL):
  1. wypełnianie zagłębień metodą priority-flood (Barnes i in. 2014),
  2. kierunek spływu D8 i akumulacja spływu (powierzchnia zlewni każdej komórki),
  3. spadek terenu w %,
  4. klasyfikacja zagłębień: rów (wąski i wydłużony), miejsce na oczko, okresowe zastoisko.

Rowy: w NMT nie widać przepustów pod drogami, więc odcinek rowu między nasypami wygląda jak zamknięta,
głęboka niecka. Rozpoznajemy go po kształcie i nie proponujemy tam oczka, tylko zastawkę. Punkt przelewu
takiej niecki leży zwykle przy przepuście, czyli tam, gdzie zastawka ma sens.
Progi: app/data/terrain.yaml (każdy z opisem źródła albo jako heurystyka).
"""

from __future__ import annotations

import base64
import heapq
import math
import struct
import zlib

from pathlib import Path

import httpx
import numpy as np
import yaml

from app.sources.base import fetch_bytes

WCS_URL = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/GRID1/WCS/DigitalTerrainModel"
COVERAGE = "DTM_PL-EVRF2007-NH"
R = 6378137.0  # promień sfery Web Mercator

_CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / "data" / "terrain.yaml").read_text(encoding="utf-8"))


def _p(section: str, key: str) -> float:
    return float(_CFG[section][key]["value"])


DEPRESSION_MIN_DEPTH_M = _p("depression", "min_depth_m")
DEPRESSION_MIN_AREA_M2 = _p("depression", "min_area_m2")
NEAR_PARCEL_M = _p("depression", "near_parcel_m")
DITCH_MAX_WIDTH_M = _p("ditch", "max_effective_width_m")
DITCH_MIN_ELONGATION = _p("ditch", "min_elongation")
DITCH_MIN_DEPTH_M = _p("ditch", "min_depth_m")
POND_MIN_DEPTH_M = _p("pond", "min_depth_m")
POND_MIN_AREA_M2 = _p("pond", "min_area_m2")
POND_MIN_INSIDE = _p("pond", "min_inside_parcel_share")
WET_MIN_INSIDE = _p("wet_spot", "min_inside_parcel_share")
FLOW_PATH_MIN_CATCHMENT_M2 = _p("flow", "path_min_catchment_m2")
OUTLET_MIN_CATCHMENT_M2 = _p("flow", "outlet_min_catchment_m2")
FLAT_P90_DEG = _p("flow", "flat_terrain_p90_deg")


# ------------------------------------------------------------ projekcja

def to_3857(lon: float, lat: float) -> tuple[float, float]:
    x = math.radians(lon) * R
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R
    return x, y


def to_4326(x: float, y: float) -> tuple[float, float]:
    lon = math.degrees(x / R)
    lat = math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2)
    return lon, lat


# ------------------------------------------------------------ pobranie NMT

async def fetch_dem(client: httpx.AsyncClient, bbox: tuple[float, float, float, float], cell: float) -> dict:
    minx, miny, maxx, maxy = bbox
    w, h = max(int(round((maxx - minx) / cell)), 2), max(int(round((maxy - miny) / cell)), 2)
    params = {"SERVICE": "WCS", "VERSION": "1.0.0", "REQUEST": "GetCoverage", "FORMAT": "image/x-aaigrid",
              "COVERAGE": COVERAGE, "BBOX": f"{minx},{miny},{maxx},{maxy}", "CRS": "EPSG:3857",
              "RESPONSE_CRS": "EPSG:3857", "WIDTH": w, "HEIGHT": h}
    try:
        _, _, body = await fetch_bytes(client, "GET", WCS_URL, params=params)
    except (httpx.RemoteProtocolError, httpx.ReadError):
        # WCS GUGiK potrafi zerwać połączenie bez odpowiedzi (22.11.2026: na przemian ok w ~4 s i zerwania);
        # jedna powtórka w ramach limitu adaptera, bez dalszych prób
        _, _, body = await fetch_bytes(client, "GET", WCS_URL, params=params)
    text = body.decode("ascii", "replace")
    if not text.lstrip().lower().startswith("ncols"):
        raise ValueError(f"WCS nie zwrócił siatki ASCII: {text[:120]}")
    return parse_aaigrid(text)


def parse_aaigrid(text: str) -> dict:
    lines = text.splitlines()
    header, i = {}, 0
    while i < len(lines) and lines[i].split() and lines[i].split()[0][0].isalpha():
        k, v = lines[i].split()[:2]
        header[k.lower()] = float(v)
        i += 1
    data = np.array(" ".join(lines[i:]).split(), dtype=float)
    nrows, ncols = int(header["nrows"]), int(header["ncols"])
    z = data[: nrows * ncols].reshape(nrows, ncols)
    nodata = header.get("nodata_value")
    if nodata is not None:
        z[z == nodata] = np.nan
    cs = header.get("cellsize") or header.get("dx")
    csy = header.get("dy", cs)
    x0 = header.get("xllcorner", header.get("xllcenter", 0) - cs / 2)
    y0 = header.get("yllcorner", header.get("yllcenter", 0) - csy / 2)
    return {"z": z, "x0": x0, "y0": y0, "cs": cs, "csy": csy}


# ------------------------------------------------------------ hydrologia

NEIGH = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def priority_flood(z: np.ndarray, eps: float = 1e-4) -> np.ndarray:
    """Wypełnia zagłębienia; eps zapewnia spadek na płaskich, więc każda komórka ma odpływ do krawędzi."""
    nr, nc = z.shape
    filled = z.copy()
    closed = np.zeros(z.shape, bool)
    heap: list[tuple[float, int, int]] = []
    for r in range(nr):
        for c in (0, nc - 1):
            heap.append((filled[r, c], r, c)); closed[r, c] = True
    for c in range(1, nc - 1):
        for r in (0, nr - 1):
            heap.append((filled[r, c], r, c)); closed[r, c] = True
    heapq.heapify(heap)
    while heap:
        e, r, c = heapq.heappop(heap)
        for dr, dc in NEIGH:
            rr, cc = r + dr, c + dc
            if 0 <= rr < nr and 0 <= cc < nc and not closed[rr, cc]:
                closed[rr, cc] = True
                if filled[rr, cc] <= e:
                    filled[rr, cc] = e + eps
                heapq.heappush(heap, (filled[rr, cc], rr, cc))
    return filled


def d8_receivers(f: np.ndarray, cell: float) -> np.ndarray:
    nr, nc = f.shape
    best = np.zeros(f.shape)
    rec = np.full(f.shape, -1, dtype=np.int64)
    pad = np.pad(f, 1, constant_values=np.inf)
    idx = np.arange(nr * nc).reshape(nr, nc)
    for dr, dc in NEIGH:
        nb = pad[1 + dr: 1 + dr + nr, 1 + dc: 1 + dc + nc]
        drop = (f - nb) / (cell * math.hypot(dr, dc))
        rr = np.clip(np.arange(nr)[:, None] + dr, 0, nr - 1)
        cc = np.clip(np.arange(nc)[None, :] + dc, 0, nc - 1)
        better = drop > best
        best = np.where(better, drop, best)
        rec = np.where(better, idx[rr, cc], rec)
    return rec.ravel()


def accumulate(f: np.ndarray, rec: np.ndarray, cell_area: float) -> np.ndarray:
    acc = np.full(f.size, cell_area)
    for i in np.argsort(-f.ravel(), kind="stable"):
        j = rec[i]
        if j >= 0:
            acc[j] += acc[i]
    return acc.reshape(f.shape)


def label8(binary: np.ndarray) -> tuple[np.ndarray, int]:
    """Etykiety spójnych obszarów (sąsiedztwo 8), zamiennik scipy.ndimage.label."""
    nr, nc = binary.shape
    lab = np.zeros(binary.shape, dtype=np.int32)
    n = 0
    for r0, c0 in np.argwhere(binary):
        if lab[r0, c0]:
            continue
        n += 1
        lab[r0, c0] = n
        stack = [(r0, c0)]
        while stack:
            r, c = stack.pop()
            for dr, dc in NEIGH:
                rr, cc = r + dr, c + dc
                if 0 <= rr < nr and 0 <= cc < nc and binary[rr, cc] and not lab[rr, cc]:
                    lab[rr, cc] = n
                    stack.append((rr, cc))
    return lab, n


def dilate(mask: np.ndarray, iterations: int) -> np.ndarray:
    """Rozszerzenie maski o n komórek (sąsiedztwo 8), zamiennik scipy.ndimage.binary_dilation."""
    out = mask.copy()
    for _ in range(iterations):
        p = np.pad(out, 1)
        out = out | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:] \
            | p[:-2, :-2] | p[:-2, 2:] | p[2:, :-2] | p[2:, 2:]
    return out


def polygon_mask(ring_xy: list[tuple[float, float]], xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Środki komórek wewnątrz wielokąta (ray casting, wektorowo)."""
    X, Y = np.meshgrid(xs, ys)
    inside = np.zeros(X.shape, bool)
    n = len(ring_xy)
    for k in range(n):
        x1, y1 = ring_xy[k]
        x2, y2 = ring_xy[(k + 1) % n]
        cond = (y1 > Y) != (y2 > Y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (x2 - x1) * (Y - y1) / (y2 - y1) + x1
        inside ^= cond & (X < xint)
    return inside


# ------------------------------------------------------------ PNG (bez Pillow)

def png_data_url(rgba: np.ndarray) -> str:
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[r].astype(np.uint8).tobytes() for r in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


def slope_rgba(slope_pct: np.ndarray, mask: np.ndarray) -> np.ndarray:
    colors = [(2, (46, 125, 50)), (5, (253, 216, 53)), (10, (245, 124, 0)), (1e9, (198, 40, 40))]
    out = np.zeros(slope_pct.shape + (4,))
    lo = -np.inf
    for hi, rgb in colors:
        sel = (slope_pct >= lo) & (slope_pct < hi)
        out[sel, :3] = rgb
        lo = hi
    out[..., 3] = np.where(mask, 170, 60)
    out[np.isnan(slope_pct)] = 0
    return out


def depth_rgba(depth: np.ndarray) -> np.ndarray:
    out = np.zeros(depth.shape + (4,))
    sel = depth >= DEPRESSION_MIN_DEPTH_M
    out[sel, :3] = (21, 101, 192)
    out[sel, 3] = np.clip(90 + depth[sel] * 400, 90, 230)
    return out


def flow_rgba(acc: np.ndarray) -> np.ndarray:
    out = np.zeros(acc.shape + (4,))
    sel = acc >= FLOW_PATH_MIN_CATCHMENT_M2
    strength = np.clip(np.log10(acc[sel] / FLOW_PATH_MIN_CATCHMENT_M2 + 1) / 2, 0, 1)
    out[sel, 0] = 0
    out[sel, 1] = 180 + 75 * strength
    out[sel, 2] = 255
    out[sel, 3] = 140 + 115 * strength
    return out


# ------------------------------------------------------------ klasyfikacja zagłębień

def shape_metrics(sel: np.ndarray, cell: float) -> tuple[float, float, float]:
    """(obwód m, szerokość efektywna m, wydłużenie) obszaru z maski. Szerokość = pole / (obwód/2),
    działa też dla rowów zakrzywionych; wydłużenie = P² / (4πA): koło 1, pas 3×100 m ≈ 11."""
    p = np.pad(sel, 1)
    edges = sum(int((p[1:-1, 1:-1] & ~np.roll(p, sh, ax)[1:-1, 1:-1]).sum())
                for sh, ax in ((1, 0), (-1, 0), (1, 1), (-1, 1)))
    perim = edges * cell
    area = sel.sum() * cell * cell
    return float(perim), float(area / max(perim / 2, 1e-9)), float(perim * perim / (4 * math.pi * max(area, 1e-9)))


def classify(max_depth: float, area: float, width: float, elongation: float, inside: float) -> str | None:
    """'ditch' | 'pond' | 'wet_spot' | None (pomijamy)."""
    if max_depth >= DITCH_MIN_DEPTH_M and width <= DITCH_MAX_WIDTH_M and elongation >= DITCH_MIN_ELONGATION:
        return "ditch"
    if inside >= POND_MIN_INSIDE and max_depth >= POND_MIN_DEPTH_M and area >= POND_MIN_AREA_M2:
        return "pond"
    if inside >= WET_MIN_INSIDE:
        return "wet_spot"
    return None


def spill_point(sel: np.ndarray, rec: np.ndarray, start: int, nc: int) -> tuple[int, int]:
    """Idzie z najgłębszej komórki po kierunkach spływu do pierwszej komórki poza zagłębieniem."""
    flat_sel = sel.ravel()
    i, guard = start, 0
    while rec[i] >= 0 and flat_sel[i] and guard < sel.size:
        i, guard = rec[i], guard + 1
    return divmod(int(i), nc)


def find_depressions(depth: np.ndarray, rec: np.ndarray, mask: np.ndarray, cell: float,
                     label_out: np.ndarray | None = None) -> list[dict]:
    """Zagłębienia z klasyfikacją. `depth` z wypełnienia BEZ epsilonu (epsilon tylko do kierunków spływu)."""
    nr, nc = depth.shape
    cell_area = cell * cell
    lab, n = label8(depth >= DEPRESSION_MIN_DEPTH_M)
    near = dilate(mask, max(1, int(NEAR_PARCEL_M / cell)))
    out = []
    for i in range(1, n + 1):
        sel = lab == i
        area = sel.sum() * cell_area
        if area < DEPRESSION_MIN_AREA_M2 or not (sel & near).any():
            continue
        _, width, elong = shape_metrics(sel, cell)
        inside = float((sel & mask).sum() / sel.sum())
        max_depth = float(depth[sel].max())
        kind = classify(max_depth, area, width, elong, inside)
        if kind is None:
            continue
        # marker: najgłębszy punkt części na działce (dla rowu: punkt przelewu, zwykle przy przepuście)
        part = sel & mask if (sel & mask).any() else sel
        deepest = int(np.argmax(np.where(part, depth, -np.inf)))
        if kind == "ditch":
            r, c = spill_point(sel, rec, deepest, nc)
        else:
            r, c = divmod(deepest, nc)
        if label_out is not None:
            label_out[sel] = len(out) + 1             # numer zagłębienia na liście wyników (1..n)
        out.append({"kind": kind, "area_m2": round(area), "volume_m3": round(float(depth[sel].sum() * cell_area)),
                    "max_depth_m": round(max_depth, 2), "width_m": round(width, 1),
                    "length_m": round(area / max(width, 1e-9)), "elongation": round(elong, 1),
                    "inside_parcel_pct": round(100 * inside), "rc": (int(r), int(c))})
    return out


# ------------------------------------------------------------ analiza

async def analyze(client: httpx.AsyncClient, ring_lonlat: list[list[float]], buffer_m: float = 50,
                  cell_m: float = 2.0) -> dict:
    """Pobiera NMT (async), a obliczenia hydrologiczne robi w wątku, żeby nie blokować serwera."""
    import asyncio
    lat_c = sum(p[1] for p in ring_lonlat) / len(ring_lonlat)
    k = math.cos(math.radians(lat_c))
    ring = [to_3857(lon, lat) for lon, lat in ring_lonlat]
    xs_, ys_ = [p[0] for p in ring], [p[1] for p in ring]
    b = buffer_m / k
    bbox = (min(xs_) - b, min(ys_) - b, max(xs_) + b, max(ys_) + b)
    g = await fetch_dem(client, bbox, cell_m / k)
    return await asyncio.to_thread(compute, g, ring_lonlat, buffer_m)


def compute(g: dict, ring_lonlat: list[list[float]], buffer_m: float) -> dict:
    lat_c = sum(p[1] for p in ring_lonlat) / len(ring_lonlat)
    k = math.cos(math.radians(lat_c))           # skala Web Mercator: 1 m terenu = 1/k jednostek 3857
    ring = [to_3857(lon, lat) for lon, lat in ring_lonlat]
    z = g["z"]
    nr, nc = z.shape
    cell = g["cs"] * k                            # rozmiar komórki w metrach terenu
    cell_area = cell * (g["csy"] * k)
    if np.isnan(z).all():
        raise ValueError("Brak danych NMT dla tego obszaru.")
    z = np.where(np.isnan(z), np.nanmax(z), z)

    xs = g["x0"] + (np.arange(nc) + 0.5) * g["cs"]
    ys = g["y0"] + (nr - np.arange(nr) - 0.5) * g["csy"]   # wiersz 0 = północ
    mask = polygon_mask(ring, xs, ys)
    if not mask.any():
        raise ValueError("Działka jest mniejsza niż jedna komórka NMT.")

    gy, gx = np.gradient(z, cell)
    slope = np.hypot(gx, gy) * 100

    filled = priority_flood(z)
    depth = priority_flood(z, eps=0.0) - z     # głębokość bez sztucznego spadku epsilonu
    rec = d8_receivers(filled, cell)
    acc = accumulate(filled, rec, cell_area)

    def lonlat(r, c):
        lon, lat = to_4326(xs[c], ys[r])
        return [round(lat, 6), round(lon, 6)]

    markers = []
    dep_label = np.zeros(z.shape, np.int32)
    deps = find_depressions(depth, rec, mask, cell, label_out=dep_label)

    # 1) miejsca, gdzie skupiony spływ opuszcza działkę (bez przesądzania o działaniu – decydują reguły)
    flat_rec = rec
    inside = mask.ravel()
    leaving = [i for i in np.flatnonzero(inside) if flat_rec[i] < 0 or not inside[flat_rec[i]]]
    leaving.sort(key=lambda i: -acc.ravel()[i])
    outlets = []
    for i in leaving:
        if acc.ravel()[i] < OUTLET_MIN_CATCHMENT_M2:
            break
        r, c = divmod(i, nc)
        if any(abs(r - r2) + abs(c - c2) < 30 / cell for r2, c2, _ in outlets):
            continue
        outlets.append((r, c, acc.ravel()[i]))
        if len(outlets) == 3:
            break

    # 2) dokąd trafia woda z każdego odpływu: idziemy w dół spływu (do 150 m) do pierwszego zagłębienia
    flat_lab = dep_label.ravel()
    for d in deps:
        d["outlets_in"], d["inflow_from_parcel_ha"] = 0, 0.0
    outlet_list, outlet_target = [], []
    for r, c, a in outlets:
        i, steps, hit = r * nc + c, 0, 0
        while steps < int(150 / cell) and flat_rec[i] >= 0:
            i, steps = flat_rec[i], steps + 1
            if flat_lab[i]:
                hit = int(flat_lab[i])
                break
        o = {"at": lonlat(r, c), "catchment_ha": round(float(a) / 10000, 2), "drains_to": None}
        if hit:
            deps[hit - 1]["outlets_in"] += 1
            deps[hit - 1]["inflow_from_parcel_ha"] = round(deps[hit - 1]["inflow_from_parcel_ha"] + o["catchment_ha"], 2)
        outlet_list.append(o)
        outlet_target.append(hit - 1 if hit else None)

    # 3) kolejność: najpierw to, do czego spływa woda z działki, potem udział na działce i objętość; potem id
    order = sorted(range(len(deps)), key=lambda k: (-deps[k]["outlets_in"], -deps[k]["inflow_from_parcel_ha"],
                                                   -deps[k]["inside_parcel_pct"], -deps[k]["volume_m3"]))
    counters: dict[str, int] = {}
    for k in order:
        d = deps[k]
        d["at"] = lonlat(*d.pop("rc"))
        prefix = {"ditch": "ditch", "pond": "pond", "wet_spot": "wet"}[d["kind"]]
        d["id"] = f"{prefix}{counters.get(prefix, 0)}"
        counters[prefix] = counters.get(prefix, 0) + 1
    for o, tgt in zip(outlet_list, outlet_target):
        o["drains_to"] = deps[tgt]["id"] if tgt is not None else None
    deps = [deps[k] for k in order]

    ditches = [d for d in deps if d["kind"] == "ditch"]
    ponds = [d for d in deps if d["kind"] == "pond"]
    wet = [d for d in deps if d["kind"] == "wet_spot"]
    for d in ditches[:2]:
        markers.append({"kind": "ditch", "id": d["id"], "at": d["at"], "title": "Prawdopodobny rów",
                        "text": f"Wąskie obniżenie ok. {d['length_m']} m długości i do {d['max_depth_m']} m głębokości. "
                                f"Znacznik stoi w miejscu, którym woda odpływa z tego odcinka (często przepust)."})
    for d in ponds[:2]:
        markers.append({"kind": "pond", "id": d["id"], "at": d["at"], "title": "Zagłębienie: możliwe miejsce na oczko",
                        "text": f"Woda zbiera się tu naturalnie: ok. {d['area_m2']} m², do {d['max_depth_m']} m głębokości, "
                                f"ok. {d['volume_m3']} m³ pojemności terenu ({d['inside_parcel_pct']}% na działce)."})
    for d in wet[:2]:
        markers.append({"kind": "wet_spot", "id": d["id"], "at": d["at"], "title": "Płytkie zagłębienie: możliwe zastoisko",
                        "text": f"Ok. {d['area_m2']} m², do {d['max_depth_m']} m głębokości. Po roztopach i ulewach "
                                f"woda może tu stać dłużej."})
    for k, o in enumerate(outlet_list):
        markers.append({"kind": "outlet", "id": f"outlet{k}", "at": o["at"], "title": "Tędy woda odpływa z działki",
                        "text": f"Skupiony spływ z ok. {o['catchment_ha']:.2f} ha (w obrębie analizowanego obszaru)."
                                + (" Woda trafia do pobliskiego rowu." if o["drains_to"] and o["drains_to"].startswith("ditch") else "")})

    # dopływ z zewnątrz: zlewnie spoza działki, które spływają na działkę
    outside = np.flatnonzero(~inside)
    inflow = sum(acc.ravel()[i] for i in outside if flat_rec[i] >= 0 and inside[flat_rec[i]])

    if not ponds and not wet:
        r, c = np.unravel_index(np.where(mask, z, np.inf).argmin(), z.shape)
        markers.append({"kind": "low", "id": "low0", "at": lonlat(r, c), "title": "Najniższy punkt działki",
                        "text": "Brak wyraźnych zagłębień. Tu woda zbiera się najdłużej po roztopach i ulewach."})

    zin, sin = z[mask], slope[mask]
    lon0, lat0 = to_4326(g["x0"], g["y0"])
    lon1, lat1 = to_4326(g["x0"] + nc * g["cs"], g["y0"] + nr * g["csy"])
    return {
        "bounds": [[lat0, lon0], [lat1, lon1]],
        "layers": {"slope": png_data_url(slope_rgba(slope, mask)),
                   "depressions": png_data_url(depth_rgba(depth)),
                   "flow": png_data_url(flow_rgba(acc))},
        "markers": markers,
        "depressions": deps[:10],
        "outlets": outlet_list,
        "stats": {
            "cell_m": round(cell, 2),
            "elevation_min_m": round(float(zin.min()), 2), "elevation_max_m": round(float(zin.max()), 2),
            "relief_m": round(float(zin.max() - zin.min()), 2),
            "slope_mean_pct": round(float(sin.mean()), 1), "slope_p90_pct": round(float(np.percentile(sin, 90)), 1),
            "slope_mean_deg": round(math.degrees(math.atan(float(sin.mean()) / 100)), 2),
            "slope_p90_deg": round(math.degrees(math.atan(float(np.percentile(sin, 90)) / 100)), 2),
            "flow_paths_on_parcel": int(((acc >= FLOW_PATH_MIN_CATCHMENT_M2) & mask).sum() > 0),
            "area_slope_over_5pct_pct": round(float((sin > 5).mean() * 100)),
            "inflow_from_outside_ha": round(float(inflow) / 10000, 2),
            "inflow_is_lower_bound": True,       # zlewnia ucięta do bufora analizy
            "pond_volume_m3": round(sum(d["volume_m3"] * d["inside_parcel_pct"] / 100 for d in ponds)),
            "n_ponds": len(ponds), "n_wet_spots": len(wet), "n_ditches": len(ditches),
            "ditch_near_parcel": bool(ditches),
            "flat_terrain": bool(math.degrees(math.atan(float(np.percentile(sin, 90)) / 100)) < FLAT_P90_DEG),
        },
        "params": {"buffer_m": buffer_m, "coverage": COVERAGE, "thresholds": "app/data/terrain.yaml"},
    }
