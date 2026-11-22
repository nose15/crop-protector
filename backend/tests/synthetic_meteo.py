"""SYNTETYCZNA pogoda do testów (deterministyczna). Nie są to dane rzeczywiste.
ET0 i temperatura: sinusoida roczna (ET0 ok. 0,3 mm w zimie, ok. 4 mm w lipcu); opad: losowy z ziarnem,
co trzeci rok „suchy” (mniej deszczu w maju–lipcu)."""

import math
import random
from datetime import date, timedelta


def generate(start: date, end: date, seed: int = 7, dry_years=(2018, 2019, 2022, 2025)) -> list[dict]:
    rnd = random.Random(seed)
    out, d = [], start
    while d <= end:
        doy = d.timetuple().tm_yday
        season = math.sin(2 * math.pi * (doy - 105) / 365)            # max ok. lipca
        et0 = round(max(0.2, 2.1 + 1.9 * season), 2)
        tmean = 8.5 + 10.5 * season
        dry = d.year in dry_years and 5 <= d.month <= 7
        p = round(rnd.expovariate(1 / 6.0), 1) if rnd.random() < (0.18 if dry else 0.42) else 0.0
        out.append({"date": d.isoformat(), "p_mm": p, "et0_mm": et0, "tmax": round(tmean + 5, 1), "tmin": round(tmean - 5, 1)})
        d += timedelta(days=1)
    return out
