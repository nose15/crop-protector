"""NASA POWER (daily point API, społeczność AG): historia pogody dla punktu działki.

Dlaczego (decyzja 22.11.2026): Open-Meteo z jednego IP (sala, Render) kończy dzienny limit (HTTP 429) i wtedy
nowa działka nie dostaje żadnej oceny. POWER nie ma dziennego limitu, jedno zapytanie niesie cały zakres dat
(10 lat ≈ 1,7 s, 376 kB; pomiar 21.11.2026), bez klucza. Siatka meteorologiczna ok. 0,5° × 0,625° (~50 km),
opóźnienie kilka dni, brak prognozy – prognozę i ostatnie dni dokłada Open-Meteo, gdy odpowiada.

ET0 nie ma w POWER, więc liczymy je w aplikacji wzorem FAO-56 Penman-Monteith (`app/engine/et0.py`):
Tmax, Tmin, wiatr na 2 m (WS2M), punkt rosy (T2MDEW), promieniowanie (ALLSKY_SFC_SW_DWN; brak → z temperatury).
Opad: PRECTOTCORR (opad skorygowany). Wartość braku danych (-999) zamieniamy na brak, nie na zero.
Czas: LST (lokalny czas słoneczny), jak w sprawdzonej wersji starej aplikacji.
"""

from __future__ import annotations

import json
from datetime import date

import httpx
import numpy as np

from app.engine.et0 import fao_pm
from app.models import MeteoDay
from app.sources.base import EmptyResult, SourceError, fetch_bytes

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = "PRECTOTCORR,T2M_MAX,T2M_MIN,WS2M,T2MDEW,ALLSKY_SFC_SW_DWN"
NAME = "NASA POWER (MERRA-2, CERES), ET0 FAO-56 liczone w aplikacji"
LICENCE = "NASA POWER – dane publiczne, bez opłat, z podaniem źródła"
RESOLUTION = "NASA POWER, ok. 0,5° × 0,625° (~50 km)"


def parse(payload: dict, lat: float) -> list[MeteoDay]:
    """Odpowiedź POWER (JSON) → dni z P, ET0 (FAO-PM), Tmax, Tmin. Braki (-999) zostają brakami."""
    par = payload["properties"]["parameter"]
    coords = payload.get("geometry", {}).get("coordinates", [])
    z = float(coords[2]) if len(coords) > 2 and coords[2] is not None else 100.0
    fill = float(payload.get("header", {}).get("fill_value", -999.0))
    keys = sorted(par["T2M_MAX"].keys())

    def arr(name: str) -> np.ndarray:
        a = np.array([par.get(name, {}).get(k, fill) for k in keys], float)
        a[a <= fill + 1e-6] = np.nan
        return a

    p, tmax, tmin = arr("PRECTOTCORR"), arr("T2M_MAX"), arr("T2M_MIN")
    days = [date(int(k[:4]), int(k[4:6]), int(k[6:])) for k in keys]
    doy = np.array([d.timetuple().tm_yday for d in days], float)
    et0 = fao_pm(tmax, tmin, doy, lat, z, u2=arr("WS2M"), tdew=arr("T2MDEW"), rs=arr("ALLSKY_SFC_SW_DWN"))
    et0[np.isnan(tmax) | np.isnan(tmin)] = np.nan

    def val(a: np.ndarray, i: int) -> float | None:
        return None if np.isnan(a[i]) else round(float(a[i]), 2)

    return [MeteoDay(date=d, p_mm=val(p, i), et0_mm=val(et0, i), tmax=val(tmax, i), tmin=val(tmin, i))
            for i, d in enumerate(days)]


async def fetch_history(client: httpx.AsyncClient, lon: float, lat: float, start: date, end: date) -> list[MeteoDay]:
    """Dni [start, end] z POWER; końcowe dni bez danych (opóźnienie POWER) są odcinane."""
    status, _, body = await fetch_bytes(client, "GET", POWER_URL, params={
        "parameters": PARAMS, "community": "AG", "longitude": round(lon, 4), "latitude": round(lat, 4),
        "start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"), "format": "JSON", "time-standard": "LST"})
    try:
        days = parse(json.loads(body), lat)
    except (KeyError, ValueError) as exc:
        raise SourceError(f"nieoczekiwany format odpowiedzi NASA POWER ({type(exc).__name__})") from exc
    while days and (days[-1].p_mm is None or days[-1].et0_mm is None):
        days.pop()                                   # opóźnienie POWER: ostatnie dni jeszcze bez danych
    if not days:
        raise EmptyResult("NASA POWER nie ma danych dla tego punktu")
    return days
