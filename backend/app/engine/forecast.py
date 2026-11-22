"""Stan wody w dniu D, prognoza na zakres dat (scenariusze) i podatność z 10 lat.

Prognoza: od stanu w dniu D do `range.to`. Na każdy dzień t od D+1: doba z archiwum (także po D),
potem prognoza (≤ 16 dni, tylko gdy D = dzień pobrania), potem analog — ten sam dzień k lat wcześniej,
cofany o całe lata, aż data wypada ≤ D.
To NIE jest prognoza pogody na miesiące, tylko „co by było, gdyby pogoda była jak w latach X”.
Wynik jako „n z 10” i przedziały (rozrzut gleby: przebiegi TAW).
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import date, timedelta

from app.engine import balance, crop as cropmod, kbw
from app.engine.weather import Series, shift_year

N_SCEN = 10
STRESS_DAYS_SEASON = 10          # SPEC: sezon z ≥ 10 dniami stresu w fazie krytycznej
STRESS_DAYS_MONTH = 5            # heurystyka: miesiąc ryzyka = ≥ 5 dni stresu w tym miesiącu


def season_start(d: date) -> date:
    return date(d.year, 3, 1) if d >= date(d.year, 3, 1) else date(d.year - 1, 3, 1)


def seasons_for(crop: str, series: Series, years: range, sowing: date | None) -> dict[int, cropmod.Season]:
    return {y: cropmod.season(crop, y, series, sowing) for y in years}


def state_at(series: Series, crop: str, runs: list[balance.TawRun], d: date, to: date,
             sowing: date | None):
    """Bilans od 1 marca sezonu do D dla każdego przebiegu TAW. Zwraca (stany końcowe, sezony) albo None.

    Sezony sięgają roku `to` włącznie, żeby dzień w roku D+2 miał wpis w słowniku.
    """
    start = season_start(d)
    days = balance.history_days(series, start, d)
    if days is None:
        return None
    seasons = seasons_for(crop, series, range(start.year, to.year + 1), sowing)
    finals = [balance.simulate(days, crop, seasons, r.taw_mm)[-1] if days else None for r in runs]
    return finals, seasons


def _p_et0(v) -> bool:
    return v is not None and v[0] is not None and v[1] is not None


def day_weather(series: Series, t: date, k: int, d: date, use_forecast: bool):
    """Pogoda doby t i etykieta źródła. Kolejność: archiwum, prognoza, analog. Brak P i ET0 → None."""
    v = series.get(t)
    if _p_et0(v):
        return "archiwum", v[0], v[1]
    if use_forecast:
        v = series.forecast.get(t)
        if _p_et0(v):
            return "prognoza", v[0], v[1]
    src = shift_year(t, -k)
    while src > d:
        src = shift_year(src, -1)
    v = series.get(src)
    if not _p_et0(v):
        return None
    return "analog", v[0], v[1]


def scenario_days(series: Series, d: date, to: date, k: int, use_forecast: bool) -> list | None:
    """Pogoda doby t: archiwum, potem prognoza, potem analog cofany całymi latami aż data ≤ D."""
    out, t = [], d + timedelta(days=1)
    while t <= to:
        w = day_weather(series, t, k, d, use_forecast)
        if w is None:
            return None
        _, p, et0 = w
        out.append((t, p, et0))
        t += timedelta(days=1)
    return out


def forecast(series: Series, crop: str, runs: list[balance.TawRun], finals, seasons, d: date, to: date,
             area_ha: float, use_forecast: bool) -> dict:
    s_days = [x for x in (d + timedelta(days=i) for i in range(1, (to - d).days + 1))
              if cropmod.in_season(seasons[x.year], x)]
    fc_used = sum(1 for t in series.forecast if d < t <= to) if use_forecast else 0
    base = {"range": {"from": d, "to": to}, "forecast_days_used": min(fc_used, 16), "scenario_years":
            [d.year - k for k in range(1, N_SCEN + 1)], "in_season_days": len(s_days)}
    if not s_days:
        return base | {"status": "poza_sezonem_uprawy"}
    scen = [scenario_days(series, d, to, k, use_forecast) for k in range(1, N_SCEN + 1)]
    valid = [(k, s) for k, s in enumerate(scen, 1) if s is not None]
    if len(valid) < N_SCEN:
        return base | {"status": "brak_danych", "note": f"Brak pogody dla {N_SCEN - len(valid)} lat scenariuszy."}

    order = sorted(range(len(runs)), key=lambda i: runs[i].taw_mm)
    mid = order[len(order) // 2]
    per_run_deficit, first_stress, stressed = [], [], 0
    for i, r in enumerate(runs):
        deficits = []
        for k, days in valid:
            sim = balance.simulate(days, crop, seasons, r.taw_mm, dr0=finals[i].dr)
            ins = [x for x in sim if cropmod.in_season(seasons[x.date.year], x.date)]
            deficits.append(sum(x.etc - x.etc_adj for x in ins))
            if i == mid:
                hit = next((x for x in ins if x.dr > x.raw), None)
                if hit:
                    stressed += 1
                    first_stress.append((hit.date - d).days)
        per_run_deficit.append(statistics.median(deficits))
    deficit = balance.interval(per_run_deficit)
    return base | {
        "status": "ok",
        "stress_chance": {"n": stressed, "of": N_SCEN},
        "days_to_raw": balance.interval(first_stress) | {"n": len(first_stress)},
        "deficit_mm": deficit,
        "deficit_m3": {k: (round(v * area_ha * 10) if v is not None else None) for k, v in deficit.items()},
        "taw_run_used_for_chance": runs[mid].label,
    }


def _mm_point(when: date, estimated: bool, levels: list[float], raws: list[float]) -> dict:
    return {
        "date": when.isoformat(),
        "estimated": estimated,
        "level_mm": balance.interval(levels),
        "raw_mm": balance.interval(raws),
    }


def water_series(series: Series, crop: str, runs: list[balance.TawRun], finals, seasons, d: date, to: date,
                 use_forecast: bool) -> list[dict] | None:
    """Zapas (TAW − Dr) i próg RAW (TAW − DayState.raw) od `d` do `to` włącznie.

    Dzień `d` bierze stany końcowe `state_at` (to nie jest scenariusz). Dni późniejsze: na każdym
    przebiegu TAW mediana po 10 ścieżkach `simulate`, potem `interval` po przebiegach. Sezony są
    tym słownikiem, który zwrócił `state_at`. Brak pogody na którykolwiek dzień → None.
    """
    points = [_mm_point(
        d, False,
        [r.taw_mm - f.dr for f, r in zip(finals, runs)],
        [r.taw_mm - f.raw for f, r in zip(finals, runs)],
    )]
    if d == to:
        return points
    paths = []
    for k in range(1, N_SCEN + 1):
        days = scenario_days(series, d, to, k, use_forecast)
        if days is None:
            return None
        paths.append(days)
    n = len(paths[0])
    level_med = [[] for _ in range(n)]
    raw_med = [[] for _ in range(n)]
    for i, r in enumerate(runs):
        sims = [balance.simulate(days, crop, seasons, r.taw_mm, dr0=finals[i].dr) for days in paths]
        for j in range(n):
            level_med[j].append(statistics.median([r.taw_mm - sim[j].dr for sim in sims]))
            raw_med[j].append(statistics.median([r.taw_mm - sim[j].raw for sim in sims]))
    t = d + timedelta(days=1)
    for j in range(n):
        w = day_weather(series, t, 1, d, use_forecast)
        if w is None:
            return None
        points.append(_mm_point(t, w[0] != "archiwum", level_med[j], raw_med[j]))
        t += timedelta(days=1)
    return points


def susceptibility(series: Series, crop: str, runs: list[balance.TawRun], shares: dict | None, d: date,
                   sowing: date | None, no_kbw: bool) -> dict:
    """Ostatnie 10 pełnych sezonów przed D: przekroczenia progu KBW, sezony z ≥ 10 dniami stresu w pełni wzrostu,
    typowe miesiące ryzyka. Bilans na środkowym przebiegu TAW."""
    last_full = d.year if d >= date(d.year, 10, 1) else d.year - 1
    years = range(last_full - N_SCEN + 1, last_full + 1)
    order = sorted(runs, key=lambda r: r.taw_mm)
    taw = order[len(order) // 2].taw_mm
    n_kbw = of_kbw = n_ks = of_ks = 0
    month_hits: Counter = Counter()
    per_year = []
    for y in years:
        s = cropmod.season(crop, y, series, sowing if sowing and sowing.year == y else None)
        exc = None if (no_kbw or shares is None) else kbw.season_exceeded(series, y, crop, shares)
        if exc is not None:
            of_kbw += 1
            n_kbw += int(exc)
        days = balance.history_days(series, date(y, 3, 1), date(y, 10, 31))
        stress_crit = None
        if days is not None:
            sim = balance.simulate(days, crop, {y: s}, taw)
            crit = [x for x in sim if s.stage(x.date) == cropmod.STAGE_KEYS[cropmod.CROPS[crop]["critical_stage"]]]
            stress_crit = sum(1 for x in crit if x.ks < 1)
            of_ks += 1
            n_ks += int(stress_crit >= STRESS_DAYS_SEASON)
            per_month = Counter(x.date.month for x in sim if x.ks < 1 and cropmod.in_season(s, x.date))
            for m, c in per_month.items():
                if c >= STRESS_DAYS_MONTH:
                    month_hits[m] += 1
        per_year.append({"year": y, "kbw_exceeded": exc, "stress_days_critical": stress_crit})
    risk = sorted((m for m, c in month_hits.items() if c >= 3), key=lambda m: (-month_hits[m], m))
    return {"years": [years.start, years.stop - 1], "n_kbw": n_kbw if of_kbw else None, "of_kbw": of_kbw,
            "n_ks": n_ks if of_ks else None, "of": of_ks,
            "risk_months": [f"{m:02d}" for m in sorted(risk)],
            "risk_months_counts": {f"{m:02d}": month_hits[m] for m in sorted(month_hits)},
            "per_year": per_year, "taw_mm_used": taw}
