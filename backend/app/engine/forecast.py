"""Stan wody w dniu D, prognoza na zakres dat (scenariusze) i podatność z 10 lat.

Prognoza: od stanu w dniu D do `range.to`. Pierwsze dni (≤ 16) z prognozy pogody, jeśli D = dzień pobrania
danych; dalej 10 scenariuszy: pogoda z tych samych dni kalendarzowych w każdym z 10 poprzednich lat.
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


def state_at(series: Series, crop: str, runs: list[balance.TawRun], d: date, sowing: date | None):
    """Bilans od 1 marca sezonu do D dla każdego przebiegu TAW. Zwraca (stany końcowe, sezony) albo None."""
    start = season_start(d)
    days = balance.history_days(series, start, d)
    if days is None:
        return None
    seasons = seasons_for(crop, series, range(start.year, d.year + 2), sowing)
    finals = [balance.simulate(days, crop, seasons, r.taw_mm)[-1] if days else None for r in runs]
    return finals, seasons


def scenario_days(series: Series, d: date, to: date, k: int, use_forecast: bool) -> list | None:
    out, t = [], d + timedelta(days=1)
    while t <= to:
        v = series.forecast.get(t) if use_forecast else None
        if v is None or v[0] is None or v[1] is None:
            v = series.get(shift_year(t, -k))
            if v is None or v[0] is None or v[1] is None:
                return None
        out.append((t, v[0], v[1]))
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
