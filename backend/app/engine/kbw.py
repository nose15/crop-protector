"""Klimatyczny bilans wodny (KBW) w okresach sześciodekadowych i progi z Dz.U. 2019 poz. 739.

KBW = ΣP − ΣET0 w 60-dniowym okresie. UWAGA: SMSR (IUNG) liczy ewapotranspirację potencjalną własną
metodą; my używamy ET0 FAO Penman-Monteith z Open-Meteo, więc wynik jest PRZYBLIŻENIEM metodyki SMSR.
Próg dla działki: średnia progów kategorii I–IV ważona udziałem kategorii na działce.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from app.engine.weather import Series

CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / "data" / "kbw_thresholds.yaml").read_text(encoding="utf-8"))
PERIODS = CFG["periods"]
ROMAN = {3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX"}
MARGIN_MM = 15.0          # |margines| < 15 mm -> na_granicy (SPEC)
METHOD = "ET0_FAO_PM_przyblizenie_SMSR"
METHOD_NOTE = "Przybliżenie metodyki SMSR: zamiast parowania liczonego przez IUNG używamy ET0 (FAO Penman-Monteith)."


def periods_of(year: int) -> list[dict]:
    out = []
    for i, p in enumerate(PERIODS):
        sm, sd = map(int, p["start"].split("-"))
        em, ed = map(int, p["end"].split("-"))
        out.append({"idx": i, "start": date(year, sm, sd), "end": date(year, em, ed),
                    "label": f"{sd} {ROMAN[sm]}–{ed} {ROMAN[em]}"})   # etykieta z dat (w tekście aktu są literówki OCR)
    return out


def kbw_mm(series: Series, start: date, end: date) -> float | None:
    w = series.window(start, end)
    return None if w is None else round(sum(v[0] - v[1] for v in w), 1)


def threshold(crop: str, shares: dict[str, float], idx: int) -> tuple[float | None, str]:
    """(próg ważony albo None, kod): 'ok' | 'brak_progu' (x – brak obniżenia plonów) | 'niewskazana' | 'brak_kategorii'."""
    table = CFG["crops"].get(crop)
    if table is None:
        return None, "brak_progu"
    agri = {c: shares.get(c, 0.0) for c in ("I", "II", "III", "IV")}
    total = sum(agri.values())
    if total <= 0:
        return None, "brak_kategorii"
    num = den = 0.0
    any_x = False
    for c, w in agri.items():
        if w <= 0:
            continue
        v = table[c][idx]
        if v == "x":
            any_x = True
        elif v == "-":
            continue                       # uprawa niewskazana na tej kategorii: pomijamy jej udział
        else:
            num += w * v
            den += w
    if den == 0:
        return None, "brak_progu" if any_x else "niewskazana"
    return round(num / den, 1), "ok"


def status_of(kbw: float | None, thr: float | None, code: str) -> tuple[str, float | None]:
    if kbw is None:
        return "brak_danych", None
    if code != "ok" or thr is None:
        return "brak_progu", None
    margin = round(kbw - thr, 1)
    if abs(margin) < MARGIN_MM:
        return "na_granicy", margin
    return ("zagrozenie" if margin < 0 else "brak_zagrozenia"), margin


def season_table(series: Series, year: int, crop: str, shares: dict[str, float]) -> list[dict]:
    rows = []
    for p in periods_of(year):
        k = kbw_mm(series, p["start"], p["end"])
        thr, code = threshold(crop, shares, p["idx"])
        st, margin = status_of(k, thr, code)
        rows.append({"label": p["label"], "start": p["start"], "end": p["end"], "kbw_mm": k,
                     "threshold_mm": thr, "margin_mm": margin, "status": st})
    return rows


def status_at(series: Series, d: date, crop: str, shares: dict[str, float] | None) -> dict:
    """Status KBW w dniu D: ostatni pełny okres kończący się najpóźniej w D. Poza 21 III–30 IX:
    status `poza_okresem` i wartości ostatniego okresu sezonu (żeby rolnik widział, jak było)."""
    if shares is None:
        return {"status": "brak_danych", "method": METHOD, "note": "Brak kategorii gleby IUNG: nie da się dobrać progu."}
    year = d.year
    table = season_table(series, year, crop, shares)
    done = [r for r in table if r["end"] <= d]
    in_season = date(year, 5, 20) <= d <= date(year, 9, 30)
    if not done:                                    # przed końcem pierwszego okresu: pokazujemy poprzedni sezon
        table = season_table(series, year - 1, crop, shares)
        done = [r for r in table if r["status"] != "brak_danych"]
    ref = done[-1] if done else None
    if ref is None:
        return {"status": "brak_danych", "method": METHOD, "note": "Za mało danych pogodowych."}
    status = ref["status"] if in_season else "poza_okresem"
    return {"status": status, "period_status": ref["status"],
            "period": {"start": ref["start"], "end": ref["end"], "label": ref["label"]},
            "kbw_mm": ref["kbw_mm"], "threshold_mm": ref["threshold_mm"], "margin_mm": ref["margin_mm"],
            "method": METHOD, "note": METHOD_NOTE if in_season else
            "Dzień analizy jest poza okresem monitoringu suszy (21 III–30 IX). Pokazujemy ostatni okres sezonu. " + METHOD_NOTE,
            "season": [{k: r[k] for k in ("label", "kbw_mm", "threshold_mm", "status")} for r in table]}


def season_exceeded(series: Series, year: int, crop: str, shares: dict[str, float]) -> bool | None:
    """Czy w sezonie `year` KBW choć raz spadł poniżej progu. None, gdy brak danych dla któregoś okresu z progiem."""
    rows = season_table(series, year, crop, shares)
    relevant = [r for r in rows if r["status"] != "brak_progu"]
    if not relevant or any(r["status"] == "brak_danych" for r in relevant):
        return None
    return any(r["status"] == "zagrozenie" for r in relevant)
