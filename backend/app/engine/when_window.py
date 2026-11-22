"""Czy termin rady mieści się w wybranym zakresie.

Miesiące zakresu to pary (rok, miesiąc), nie numery z końców przedziału: maj–maj w jednym
roku nie zawiera lutego, maj roku Y–maj roku Y+2 zawiera. Chip zostaje napisem pełnego
okna albo etykietą części wspólnej. Puste przecięcie usuwa kartę.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.engine import crop as cropmod, plain
from app.engine.crop import Season
from app.engine.terrain_rules import RULES
from app.engine.weather import build_series
from app.models import ParcelContext, Recommendation, RecommendRequest

# Okna miesięczne powtarzają się w każdym roku, przez który przechodzi zakres.
_R11 = {2, 3}
_R6 = {8, 9, 10}
_SPRING = {3, 4, 5}          # wiosna w R3 i R14
_R3_AUTUMN = {8, 9}
_R14_LATE = {8}
_SEASON_RULES = frozenset({"R1", "R2", "R7", "R8"})


def months_touched(frm: date, to: date) -> list[tuple[int, int]]:
    """Pary (rok, miesiąc) od `frm` do `to`, oba końce włącznie. Jeden dzień miesiąca wystarcza."""
    out = []
    y, m = frm.year, frm.month
    while (y, m) <= (to.year, to.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def months_label(months: set[int]) -> str:
    """Biegi ciągłe w kalendarzu. Grudzień styka się ze styczniem; rozłączne biegi łączy „ lub ”."""
    return " lub ".join(plain.month_range([f"{m:02d}" for m in run]) for run in _runs(months))


def apply(recs: list[Recommendation], ctx: ParcelContext, req: RecommendRequest) -> list[Recommendation]:
    """Karty z niepustym przecięciem okna i zakresu. Kolejność wejściowa zostaje."""
    frm, to = req.range.from_, req.range.to
    seasons = _seasons(ctx, req) if any(r.rule in _SEASON_RULES for r in recs) else None
    kept = []
    for rec in recs:
        out = clip(rec, frm, to, seasons)
        if out is not None:
            kept.append(out)
    return kept


def clip(rec: Recommendation, frm: date, to: date,
         seasons: dict[int, Season] | None = None) -> Recommendation | None:
    """Karta z chipem części wspólnej albo None, gdy okno mija się z zakresem."""
    if rec.rule in ("R16", "IRR"):
        return rec
    pairs = set(months_touched(frm, to))
    if rec.rule == "R15":
        return _clip_r15(rec, {m for _, m in pairs})
    if rec.rule == "R11":
        return _clip_span(rec, pairs, _R11)
    if rec.rule == "R6":
        return _clip_span(rec, pairs, _R6)
    if rec.rule == "R3":
        return _clip_sides(rec, pairs, _SPRING, _R3_AUTUMN, _r3_text)
    if rec.rule == "R14":
        return _clip_sides(rec, pairs, _SPRING, _R14_LATE, _r14_text)
    if rec.rule == "R1":
        return _clip_r1(rec, pairs, seasons or {})
    if rec.rule in ("R2", "R7", "R8"):
        return _clip_gap(rec, pairs, seasons or {})
    return rec


def _runs(months: set[int]) -> list[list[int]]:
    if not months:
        return []
    runs: list[list[int]] = []
    cur: list[int] = []
    for m in range(1, 13):
        if m in months:
            cur.append(m)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    if len(runs) >= 2 and runs[0][0] == 1 and runs[-1][-1] == 12:
        runs = [runs[-1] + runs[0], *runs[1:-1]]
    runs.sort(key=lambda run: run[0])
    return runs


def _yearly(pairs: set[tuple[int, int]], months: set[int]) -> set[tuple[int, int]]:
    years = {y for y, _ in pairs}
    return {(y, m) for y in years for m in months}


def _months(pairs: set[tuple[int, int]]) -> set[int]:
    return {m for _, m in pairs}


def _full(inter: set[tuple[int, int]], window: set[tuple[int, int]]) -> bool:
    return _months(inter) == _months(window)


def _clip_span(rec: Recommendation, pairs: set[tuple[int, int]], months: set[int]) -> Recommendation | None:
    window = _yearly(pairs, months)
    inter = pairs & window
    if not inter:
        return None
    if _full(inter, window):
        return rec
    label = months_label(_months(inter))
    text = rec.when_text.replace(rec.when_short, label, 1) if rec.when_text and rec.when_short else rec.when_text
    return rec.model_copy(update={"when_short": label, "when_text": text})


def _clip_sides(rec, pairs, left: set[int], right: set[int], text_of) -> Recommendation | None:
    window = _yearly(pairs, left | right)
    inter = pairs & window
    if not inter:
        return None
    if _full(inter, window):
        return rec
    got = _months(inter)
    return rec.model_copy(update={"when_short": months_label(got), "when_text": text_of(got & left, got & right)})


def _r3_text(spring: set[int], autumn: set[int]) -> str:
    clauses = []
    if autumn:
        clauses.append(f"pod koniec lata lub wczesną jesienią ({months_label(autumn)})")
    if spring:
        clauses.append(f"wiosną ({months_label(spring)})")
    body = clauses[0] if len(clauses) == 1 else f"{clauses[0]} albo {clauses[1]}"
    return f"Wysiej trawę w pasie {body}."


def _r14_text(spring: set[int], late: set[int]) -> str:
    clauses = []
    if spring:
        clauses.append(f"wiosną ({months_label(spring)})")
    if late:
        clauses.append(f"pod koniec lata ({months_label(late)})")
    body = clauses[0] if len(clauses) == 1 else f"{clauses[0]} lub {clauses[1]}"
    return f"Pas zakładaj {body}."


def _clip_r1(rec: Recommendation, pairs: set[tuple[int, int]],
             seasons: dict[int, Season]) -> Recommendation | None:
    window = {(s.start.year, s.start.month) for s in seasons.values()}
    inter = pairs & window
    if not inter:
        return None
    if _full(inter, window):
        return rec
    return rec.model_copy(update={"when_short": months_label(_months(inter))})


def _clip_gap(rec: Recommendation, pairs: set[tuple[int, int]],
              seasons: dict[int, Season]) -> Recommendation | None:
    window = _gap_pairs(seasons)
    inter = pairs & window
    if not inter:
        return None
    if _full(inter, window):
        return rec
    label = months_label(_months(inter))
    if rec.rule == "R2":
        text = rec.when_text.replace("(po zbiorze)", f"({label})", 1) if rec.when_text else None
    else:
        text = _at_time(rec.when_text, label)
    return rec.model_copy(update={"when_short": label, "when_text": text})


def _gap_pairs(seasons: dict[int, Season]) -> set[tuple[int, int]]:
    """Od dnia zbioru włącznie do startu następnego sezonu wyłącznie."""
    found: set[tuple[int, int]] = set()
    for year, current in seasons.items():
        nxt = seasons.get(year + 1)
        if nxt is None or current.ends[-1] >= nxt.start:
            continue
        found.update(months_touched(current.ends[-1], nxt.start - timedelta(days=1)))
    return found


def _at_time(text: str | None, label: str) -> str | None:
    if not text or ":" not in text:
        return text
    rest = text.split(":", 1)[1].lstrip()
    return f"W terminie {label}: {rest}"


def _clip_r15(rec: Recommendation, touched: set[int]) -> Recommendation | None:
    # Prognoza: dzień liczony od początku zakresu, napisu „przed …” nie składamy drugi raz.
    if any(item.field.startswith("forecast.") for item in rec.evidence):
        return rec
    if (rec.when_short or "").startswith("przed "):
        return rec
    codes = next((item.value for item in rec.evidence if item.field == "susceptibility.risk_months"), None)
    if not codes:
        return rec
    kept = [c for c in codes if int(c) in touched]
    if not kept:
        return None
    if len(kept) == len(list(codes)):
        return rec
    return rec.model_copy(update={
        "when_short": plain.month_range(kept),
        "when_text": RULES["R15"]["when_history"].format(months=plain.months(kept)),
    })


def _seasons(ctx: ParcelContext, req: RecommendRequest) -> dict[int, Season]:
    """Sezony od roku przed zakresem do roku po nim. Odczyt terminów, nie stan wody w glebie."""
    frm, to = req.range.from_, req.range.to
    series = build_series(ctx.meteo, frm)
    return {y: cropmod.season(req.crop, y, series, req.sowing_date) for y in range(frm.year - 1, to.year + 2)}
