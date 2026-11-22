"""Szereg dobowy pogody z ParcelContext: słownik data -> (P, ET0, Tmax, Tmin).

Zasady: historię ucinamy na dniu analizy D, a gdy podano `through` — na max(D, through). Pojedyncze braki
(do 2 dni z rzędu) uzupełniamy interpolacją liniową i zgłaszamy w ograniczeniach; dłuższe luki zostają
brakami, a obliczenia, które na nie trafią, dostają „brak danych” (bez cichych wartości domyślnych).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.models import Meteo

FIELDS = ("p_mm", "et0_mm", "tmax", "tmin")
MAX_GAP_DAYS = 2


@dataclass
class Series:
    days: dict[date, tuple[float | None, float | None, float | None, float | None]]
    first: date
    last: date
    forecast: dict[date, tuple] = field(default_factory=dict)
    filled: int = 0

    def get(self, d: date):
        return self.days.get(d)

    def window(self, start: date, end: date) -> list[tuple] | None:
        """Wszystkie dni [start, end] albo None, gdy brakuje choć jednego dnia lub wartości P/ET0."""
        out, d = [], start
        while d <= end:
            v = self.days.get(d)
            if v is None or v[0] is None or v[1] is None:
                return None
            out.append(v)
            d += timedelta(days=1)
        return out


def _interp(rows: list[list], col: int) -> int:
    n, filled, i = len(rows), 0, 0
    while i < n:
        if rows[i][col] is None:
            j = i
            while j < n and rows[j][col] is None:
                j += 1
            if 0 < i and j < n and (j - i) <= MAX_GAP_DAYS:
                a, b = rows[i - 1][col], rows[j][col]
                for k in range(i, j):
                    rows[k][col] = a + (b - a) * (k - i + 1) / (j - i + 1)
                    filled += 1
            i = j
        else:
            i += 1
    return filled


def build_series(meteo: Meteo, d_analysis: date, through: date | None = None) -> Series:
    end = max(d_analysis, through) if through is not None else d_analysis
    hist = sorted((m for m in meteo.daily if m.date <= end), key=lambda m: m.date)
    rows = [[getattr(m, f) for f in FIELDS] for m in hist]
    filled = sum(_interp(rows, c) for c in range(4))
    days = {m.date: tuple(r) for m, r in zip(hist, rows)}
    fc = {m.date: tuple(getattr(m, f) for f in FIELDS) for m in meteo.forecast if m.date > d_analysis}
    first = hist[0].date if hist else d_analysis
    last = hist[-1].date if hist else d_analysis
    return Series(days=days, first=first, last=last, forecast=fc, filled=filled)


def shift_year(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:            # 29 lutego
        return d.replace(year=d.year + years, day=28)
