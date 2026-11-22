"""ISRIC SoilGrids 2.0 (250 m): retencja wody (wv0033, wv1500) z kwantylami, tekstura, SOC.

Usługa bywa wolna (zmierzone 2,7–27 s), dlatego dwa małe zapytania równolegle zamiast jednego dużego.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date

import httpx

from app.models import Parcel, Quantiles, SoilGrids
from app.sources.base import EmptyResult, SourceAdapter, fetch_bytes

URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
WATER_DEPTHS = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15, "30-60cm": 30, "60-100cm": 40}   # wagi = miąższość
TOP_DEPTHS = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15}


def _weighted(layer: dict, depths: dict[str, int], value: str) -> float | None:
    f = layer["unit_measure"].get("d_factor") or 1
    num = den = 0.0
    for d in layer["depths"]:
        w, v = depths.get(d["label"]), d["values"].get(value)
        if w and v is not None:
            num += w * v / f
            den += w
    return round(num / den, 2) if den else None


async def _query(client, lon, lat, props, depths, values) -> dict:
    params = [("lon", lon), ("lat", lat)] + [("property", p) for p in props] \
        + [("depth", d) for d in depths] + [("value", v) for v in values]
    _, _, body = await fetch_bytes(client, "GET", URL, params=params)
    return {layer["name"]: layer for layer in json.loads(body)["properties"]["layers"]}


class SoilGridsAdapter(SourceAdapter[SoilGrids]):
    name = "ISRIC SoilGrids 2.0"
    licence = "CC BY 4.0, ISRIC"
    timeout_s = 6.0

    async def _fetch(self, client: httpx.AsyncClient, parcel: Parcel, as_of: date):
        lon, lat = parcel.centroid
        water, top = await asyncio.gather(
            _query(client, lon, lat, ["wv0033", "wv1500"], WATER_DEPTHS, ["Q0.05", "mean", "Q0.95"]),
            _query(client, lon, lat, ["sand", "clay", "soc"], TOP_DEPTHS, ["mean"]))

        def q(name):
            layer = water.get(name)
            if not layer:
                return None
            out = Quantiles(q05=_weighted(layer, WATER_DEPTHS, "Q0.05"), mean=_weighted(layer, WATER_DEPTHS, "mean"),
                            q95=_weighted(layer, WATER_DEPTHS, "Q0.95"))
            return out if out.mean is not None else None

        def m(name):
            return _weighted(top[name], TOP_DEPTHS, "mean") if name in top else None

        res = SoilGrids(wv0033=q("wv0033"), wv1500=q("wv1500"), sand_pct=m("sand"), clay_pct=m("clay"), soc_gkg=m("soc"))
        if res.wv0033 is None and res.sand_pct is None:
            raise EmptyResult("SoilGrids nie ma danych dla tego punktu")
        return res, None
