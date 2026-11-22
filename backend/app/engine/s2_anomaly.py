"""Porównanie satelitarne: czy rośliny na tej działce wyglądają gorzej niż zwykle o tej porze (metodyka-openeo.md §4).

Wejście: wieloletni szereg z openEO (app/baseline.py): {date, ndvi, ndmi, valid_frac}.
1. Czyszczenie: tylko sceny z validFrac ≥ 0,5; usuwamy pojedyncze nagłe spadki (> 0,2 NDVI poniżej obu sąsiadów
   w odstępie ≤ 20 dni) – artefakty chmur i cieni.
2. Kompozyt dekadowy (1–10, 11–20, 21–koniec miesiąca) = mediana scen.
3. Odporny z-score: z = (x − med(B)) / (1,4826 · MAD(B)), B = ta sama dekada w latach < rok D; dolne ograniczenie
   skali 0,05 [heurystyka: zmienność międzyroczna NDVI ok. 0,05–0,1]; potrzeba ≥ 3 lat bazy.
4. Okno: ostatnie 3 dekady z obserwacją do dnia D (bez danych z przyszłości), tylko 1 IV – 30 IX.
5. Flagi „to nie susza”: baza_mieszana (|z| > 3 albo NDVI i NDMI rozjechane o > 3 – inna uprawa w latach bazowych),
   zbior_zabieg (szczyt sezonu > 0,5 i ostatnia wartość ≈ goła gleba), nie_susza_mokro (anomalia ≤ −1 przy opadzie
   ostatnich 30 dni wyraźnie powyżej normy).
Wynik `signal`: „niedobor” (z ≤ −1), „norma” (z ≥ −0,5), „niejasny” albo None (nie oceniono, z powodem).
Zestawienie z bilansem wody (`agreement`): „potwierdza”, „przeczy”, „nie_rozstrzyga”.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta

VALID_MIN = 0.5
MIN_BASE_YEARS = 3
GOOD_BASE_YEARS = 5         # poniżej – porównanie ma niską pewność
BARE_NDVI = 0.25
Z_DEFICIT, Z_NORMAL = -1.0, -0.5
MAD_FLOOR = 0.05


def decade_of(d: date) -> int:
    return (d.month - 1) * 3 + (0 if d.day <= 10 else 1 if d.day <= 20 else 2)


def _clean(obs: list[dict]) -> list[dict]:
    v = [o for o in obs if o.get("ndvi") is not None and (o.get("valid_frac") or 0) >= VALID_MIN]
    out = []
    for i, o in enumerate(v):
        if 0 < i < len(v) - 1:
            a, b = v[i - 1], v[i + 1]
            da = (date.fromisoformat(o["date"]) - date.fromisoformat(a["date"])).days
            db = (date.fromisoformat(b["date"]) - date.fromisoformat(o["date"])).days
            if da <= 20 and db <= 20 and o["ndvi"] < a["ndvi"] - 0.2 and o["ndvi"] < b["ndvi"] - 0.2:
                continue
        out.append(o)
    return out


def _composite(obs: list[dict]) -> dict[tuple[int, int], dict]:
    by = defaultdict(list)
    for o in obs:
        d = date.fromisoformat(o["date"])
        by[(d.year, decade_of(d))].append(o)
    out = {}
    for k, items in by.items():
        ndmi = [o["ndmi"] for o in items if o.get("ndmi") is not None]
        out[k] = {"ndvi": statistics.median(o["ndvi"] for o in items),
                  "ndmi": statistics.median(ndmi) if ndmi else None, "n": len(items)}
    return out


def robust_z(x: float | None, base: list[float]) -> float | None:
    b = [v for v in base if v is not None]
    if x is None or len(b) < MIN_BASE_YEARS:
        return None
    med = statistics.median(b)
    mad = max(statistics.median(abs(v - med) for v in b) * 1.4826, MAD_FLOOR)
    return (x - med) / mad


def analyse(obs: list[dict], d: date, wet_recently: bool = False) -> dict:
    """Anomalia dla dnia analizy d. Bez danych z przyszłości: obserwacje po d są pomijane."""
    if not (date(d.year, 4, 1) <= d <= date(d.year, 9, 30)):
        return {"signal": None, "reason": "poza okresem wzrostu (1 IV – 30 IX) zdjęcia nie mówią o suszy"}
    clean = _clean([o for o in obs if o["date"] <= d.isoformat()])
    comp = _composite(clean)
    base_years = sorted({y for (y, _) in comp if y < d.year})
    if len(base_years) < MIN_BASE_YEARS:
        return {"signal": None, "reason": f"za krótka baza satelitarna ({len(base_years)} lat)", "base_years": len(base_years)}
    cur = sorted(k for k in comp if k[0] == d.year and k[1] <= decade_of(d) and k[1] >= decade_of(date(d.year, 4, 1)))
    window = cur[-3:]
    if not window:
        return {"signal": None, "reason": "brak czystych zdjęć działki w ostatnich tygodniach", "base_years": len(base_years)}
    zn, zm, rows = [], [], []
    for (y, dec) in window:
        x = comp[(y, dec)]
        bn = [comp[(by, dec)]["ndvi"] for by in base_years if (by, dec) in comp]
        bm = [comp[(by, dec)]["ndmi"] for by in base_years if (by, dec) in comp]
        a, b = robust_z(x["ndvi"], bn), robust_z(x["ndmi"], bm)
        if a is not None:
            zn.append(a)
        if b is not None:
            zm.append(b)
        rows.append({"decade": dec, "ndvi": round(x["ndvi"], 3), "ndmi": None if x["ndmi"] is None else round(x["ndmi"], 3),
                     "base_ndvi": round(statistics.median(bn), 3) if bn else None, "n_base": len(bn)})
    z_ndvi = round(statistics.mean(zn), 2) if zn else None
    z_ndmi = round(statistics.mean(zm), 2) if zm else None
    flags = []
    if any(abs(z) > 3 for z in zn + zm) or (z_ndvi is not None and z_ndmi is not None and abs(z_ndvi - z_ndmi) > 3):
        flags.append("baza_mieszana")
    season = [comp[k]["ndvi"] for k in sorted(comp) if k[0] == d.year]
    if len(season) >= 2 and max(season) > 0.5 and season[-1] < BARE_NDVI + 0.05:
        flags.append("zbior_zabieg")
    zs = [z for z in (z_ndvi, z_ndmi) if z is not None]
    zmin = min(zs) if zs else None
    if zmin is not None and zmin <= Z_DEFICIT and wet_recently:
        flags.append("nie_susza_mokro")
    res = {"z_ndvi": z_ndvi, "z_ndmi": z_ndmi, "base_years": len(base_years), "n_obs": len(window),
           "window": [r["decade"] for r in rows], "rows": rows, "flags": flags}
    if zmin is None:
        return res | {"signal": None, "reason": "brak porównywalnych dekad w latach bazowych"}
    if flags:
        why = {"baza_mieszana": "w latach bazowych rosła tu najpewniej inna uprawa",
               "zbior_zabieg": "spadek zieleni wygląda na zbiór albo zabieg, nie na suszę",
               "nie_susza_mokro": "rośliny słabsze mimo mokrego miesiąca – to nie wygląda na suszę"}
        return res | {"signal": None, "reason": why[flags[0]]}
    signal = "niedobor" if zmin <= Z_DEFICIT else "norma" if zmin >= Z_NORMAL else "niejasny"
    return res | {"signal": signal, "z": round(zmin, 2)}


def agreement(sat: dict, balance_deficit: bool | None) -> str:
    """Czy zdjęcia satelitarne zgadzają się z bilansem wody (niedobór w dniu analizy albo w wybranym okresie)."""
    if balance_deficit is None or sat.get("signal") not in ("niedobor", "norma"):
        return "nie_rozstrzyga"
    sat_deficit = sat["signal"] == "niedobor"
    return "potwierdza" if sat_deficit == balance_deficit else "przeczy"


def wet_last_30(series, d: date, years: int = 10) -> bool:
    """Opad ostatnich 30 dni wyraźnie powyżej normy (> mediana z lat ubiegłych + 50%)."""
    def p_sum(end: date) -> float | None:
        vals = [series.get(end - timedelta(days=i)) for i in range(30)]
        if any(v is None or v[0] is None for v in vals):
            return None
        return sum(v[0] for v in vals)
    now = p_sum(d)
    past = [s for s in (p_sum(date(d.year - k, d.month, min(d.day, 28))) for k in range(1, years + 1)) if s is not None]
    return now is not None and len(past) >= 3 and now > 1.5 * statistics.median(past)
