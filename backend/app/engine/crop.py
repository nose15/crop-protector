"""Fazy uprawy i współczynnik Kc(t) według FAO-56 (rozdz. 6, krzywa Kc z 4 fazami)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

from app.engine.weather import Series

CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / "data" / "crops.yaml").read_text(encoding="utf-8"))
CROPS = CFG["crops"]
KC_OFF = float(CFG["kc_off"]["value"])
KC_DORMANT = float(CFG["kc_dormant_winter"]["value"])
VEG_T = float(CFG["vegetation_start_temp_c"]["value"])
VEG_WIN = int(CFG["vegetation_start_window_days"]["value"])
STAGES = ("poczatkowa", "rozwoj", "srodkowa", "koncowa")
STAGE_KEYS = {"ini": "poczatkowa", "dev": "rozwoj", "mid": "srodkowa", "late": "koncowa"}


@dataclass
class Season:
    start: date                 # początek fazy początkowej (siew albo start wegetacji)
    ends: list[date]            # końce 4 faz; ends[-1] = zbiór / koniec sezonu
    start_source: str           # "rolnik" | "heurystyka_siewu" | "start_wegetacji" | "mediana_lat"
    winter_crop: bool

    def stage(self, d: date) -> str:
        if d < self.start:
            return "spoczynek" if self.winter_crop else "przed_siewem"
        for name, end in zip(STAGES, self.ends):
            if d <= end:
                return name
        return "po_zbiorze"


def vegetation_start(series: Series, year: int) -> date | None:
    """Pierwszy dzień od 1 marca, od którego średnia z 5 dni temperatury dobowej jest ≥ 5°C."""
    d, end = date(year, 3, 1), date(year, 6, 30)
    while d <= end:
        vals = [series.get(d + timedelta(days=k)) for k in range(VEG_WIN)]
        if any(v is None or v[2] is None or v[3] is None for v in vals):
            return None
        if statistics.mean((v[2] + v[3]) / 2 for v in vals) >= VEG_T:
            return d
        d += timedelta(days=1)
    return None


def season(crop: str, year: int, series: Series, sowing: date | None = None) -> Season:
    c = CROPS[crop]
    if c["start"] == "sowing":
        if sowing and sowing.year == year:
            start, src = sowing, "rolnik"
        else:
            m, d = map(int, c["sowing_mmdd"].split("-"))
            start, src = date(year, m, d), "heurystyka_siewu"
    else:
        start, src = vegetation_start(series, year), "start_wegetacji"
        if start is None:                       # brak temperatur dla tego roku (np. przyszły sezon)
            doys = [v.timetuple().tm_yday for y in range(year - 10, year)
                    if (v := vegetation_start(series, y)) is not None]
            doy = int(statistics.median(doys)) if doys else 80          # 80 ≈ 21 marca; tylko gdy brak danych
            start, src = date(year, 1, 1) + timedelta(days=doy - 1), "mediana_lat" if doys else "domyslna"
    ends, d = [], start
    for n in c["stages_days"]:
        d = d + timedelta(days=n)
        ends.append(d)
    return Season(start=start, ends=ends, start_source=src, winter_crop=c["start"] == "vegetation")


def kc(crop: str, s: Season, d: date) -> float:
    """Kc w dniu d: stały w fazie początkowej i środkowej, liniowy w fazie rozwoju i końcowej."""
    k = CROPS[crop]["kc"]
    st = s.stage(d)
    if st == "spoczynek":
        return KC_DORMANT
    if st in ("przed_siewem", "po_zbiorze"):
        return KC_OFF
    if st == "poczatkowa":
        return k["ini"]
    if st == "srodkowa":
        return k["mid"]
    i = STAGES.index(st)
    a = s.start if i == 0 else s.ends[i - 1]
    frac = (d - a).days / max((s.ends[i] - a).days, 1)
    lo, hi = (k["ini"], k["mid"]) if st == "rozwoj" else (k["mid"], k["end"])
    return lo + (hi - lo) * frac


def in_season(s: Season, d: date) -> bool:
    return s.start <= d <= s.ends[-1]


def stage_label(st: str) -> str:
    return {"spoczynek": "spoczynek zimowy", "przed_siewem": "przed siewem", "poczatkowa": "początek wzrostu",
            "rozwoj": "intensywny wzrost", "srodkowa": "pełnia wzrostu (największe zużycie wody)",
            "koncowa": "dojrzewanie", "po_zbiorze": "po zbiorze"}[st]
