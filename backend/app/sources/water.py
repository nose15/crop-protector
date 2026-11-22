"""OpenStreetMap (Overpass): cieki i rowy w promieniu 500 m od działki.

Z sieci hackathonu Overpass nie odpowiadał (3 serwery, >40 s), więc limit jest krótki,
a reguły R11 i R14 bez tych danych stają się warunkowe.
"""

from __future__ import annotations

import json
import math
from datetime import date

import httpx

from app.geo import to_2180
from app.models import Parcel, Water
from app.sources.base import SourceAdapter, fetch_bytes

URL = "https://overpass-api.de/api/interpreter"
RADIUS_M = 500
DITCH = {"ditch", "drain"}
WATERCOURSE = {"stream", "river", "canal"}


def _seg_dist(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def distance_to_parcel(line_xy, ring_xy) -> float:
    """Najmniejsza odległość linii od obwodu działki (wierzchołki ↔ odcinki), w metrach."""
    best = math.inf
    for i in range(len(ring_xy) - 1):
        for p in line_xy:
            best = min(best, _seg_dist(p, ring_xy[i], ring_xy[i + 1]))
    for j in range(len(line_xy) - 1):
        for p in ring_xy:
            best = min(best, _seg_dist(p, line_xy[j], line_xy[j + 1]))
    return best


class WaterAdapter(SourceAdapter[Water]):
    name = "OpenStreetMap (Overpass API)"
    licence = "ODbL, © współtwórcy OpenStreetMap"
    timeout_s = 5.0
    query_timeout_s = 5

    async def _fetch(self, client: httpx.AsyncClient, parcel: Parcel, as_of: date):
        lon, lat = parcel.centroid
        q = f'[out:json][timeout:{self.query_timeout_s}];way["waterway"](around:{RADIUS_M},{lat},{lon});out geom;'
        _, _, body = await fetch_bytes(client, "POST", URL, data={"data": q})
        ring_xy = [to_2180(*p) for p in parcel.rings[0]]
        feats, near_ditch, near_course = [], math.inf, math.inf
        for el in json.loads(body).get("elements", []):
            coords = [[g["lon"], g["lat"]] for g in el.get("geometry", [])]
            kind = el.get("tags", {}).get("waterway")
            if len(coords) < 2:
                continue
            d = distance_to_parcel([to_2180(*c) for c in coords], ring_xy)
            if kind in DITCH:
                near_ditch = min(near_ditch, d)
            elif kind in WATERCOURSE:
                near_course = min(near_course, d)
            feats.append({"type": "Feature", "properties": {"kind": kind, "name": el.get("tags", {}).get("name"),
                                                            "distance_m": round(d)},
                          "geometry": {"type": "LineString", "coordinates": coords}})
        fin = lambda v: round(v) if math.isfinite(v) else None  # noqa: E731
        return Water(nearest_ditch_m=fin(near_ditch), nearest_watercourse_m=fin(near_course),
                     geojson={"type": "FeatureCollection", "features": feats}), None
