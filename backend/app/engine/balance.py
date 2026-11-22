"""Dobowy bilans wody w strefie korzeniowej, FAO-56 rozdz. 8 (wersja uproszczona).

  Dr_i = clip(Dr_{i-1} − P_i + ETc,adj_i, 0, TAW)        (nadmiar opadu odpływa w głąb, bez spływu powierzchniowego)
  ETc = Kc·ET0;  p = clip(p_tab + 0,04·(5 − ETc), 0,1, 0,8)  (FAO-56 eq. 81 / tab. 22)
  RAW = p·TAW;  Ks = 1 gdy Dr ≤ RAW, inaczej (TAW − Dr)/((1 − p)·TAW)   (eq. 84)
  ETc,adj = Ks·ETc
Start 1 marca z Dr = 0 (gleba przy polowej pojemności po zimie – założenie FAO-56 dla klimatu wilgotnego).

TAW jako przedział: do 3 oszacowań zapasu wody (dolna i górna granica kategorii IUNG na działce, SoilGrids)
× 2 głębokości korzeni (Zr min/max z FAO-56 tab. 22) = do 6 przebiegów.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

from app.engine import crop as cropmod
from app.engine.weather import Series
from app.models import ParcelContext

CROPS_CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / "data" / "crops.yaml").read_text(encoding="utf-8"))
TAW_CAT = CROPS_CFG["taw_by_category_mm_per_1_5m"]


@dataclass
class TawRun:
    label: str          # np. "IUNG dolna, Zr 1,5 m"
    taw_mm: float


def wod_estimates(ctx: ParcelContext) -> list[tuple[str, float]]:
    """Zapas wody dostępnej na 1,5 m (mm): granice kategorii IUNG ważone udziałem oraz SoilGrids."""
    out = []
    iung = ctx.soil.iung if ctx.soil else None
    if iung:
        cats = {c: iung.shares.get(c, 0.0) for c in TAW_CAT}
        tot = sum(cats.values())
        if tot > 0:
            for bound in ("low", "high"):
                out.append((f"IUNG {'dolna' if bound == 'low' else 'górna'} granica",
                            sum(w * TAW_CAT[c][bound] for c, w in cats.items()) / tot))
    sg = ctx.soil.soilgrids if ctx.soil else None
    if sg and sg.wv0033 and sg.wv1500 and sg.wv0033.mean is not None and sg.wv1500.mean is not None:
        # SoilGrids: obj. % wody (0–100 cm, średnia ważona); (FC − WP) · 1,5 m
        out.append(("SoilGrids", max(sg.wv0033.mean - sg.wv1500.mean, 0.0) / 100 * 1500))
    return out


def taw_runs(ctx: ParcelContext, crop: str) -> list[TawRun]:
    zr = cropmod.CROPS[crop]["zr_m"]
    runs = []
    for label, wod in wod_estimates(ctx):
        for z in zr:
            runs.append(TawRun(f"{label}, korzenie {str(z).replace('.', ',')} m", round(wod * z / 1.5, 1)))
    return runs


@dataclass
class DayState:
    date: date
    dr: float
    raw: float
    ks: float
    etc: float
    etc_adj: float
    kc: float


def step(dr: float, p_mm: float, et0: float, kc: float, taw: float, p_tab: float) -> tuple[float, float, float, float, float]:
    etc = kc * et0
    p = min(max(p_tab + 0.04 * (5 - etc), 0.1), 0.8)
    raw = p * taw
    ks = 1.0 if dr <= raw else max((taw - dr) / ((1 - p) * taw), 0.0)
    etc_adj = ks * etc
    dr_new = min(max(dr - p_mm + etc_adj, 0.0), taw)
    return dr_new, raw, ks, etc, etc_adj


def simulate(days: list[tuple[date, float, float]], crop: str, seasons: dict[int, "cropmod.Season"], taw: float,
             dr0: float = 0.0) -> list[DayState]:
    """days: [(data, P, ET0)]; seasons: rok -> Season (Kc liczone wg sezonu roku danego dnia)."""
    p_tab = cropmod.CROPS[crop]["p"]
    out, dr = [], dr0
    for d, p_mm, et0 in days:
        s = seasons[d.year]
        k = cropmod.kc(crop, s, d)
        dr, raw, ks, etc, etc_adj = step(dr, p_mm, et0, k, taw, p_tab)
        out.append(DayState(d, dr, raw, ks, etc, etc_adj, k))
    return out


def history_days(series: Series, start: date, end: date) -> list[tuple[date, float, float]] | None:
    w = series.window(start, end)
    if w is None:
        return None
    return [(start + timedelta(days=i), v[0], v[1]) for i, v in enumerate(w)]


def interval(values: list[float]) -> dict:
    if not values:
        return {"median": None, "low": None, "high": None}
    return {"median": round(statistics.median(values), 1), "low": round(min(values), 1), "high": round(max(values), 1)}
