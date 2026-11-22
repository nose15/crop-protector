"""Pogoda dobowa dla działki: historia od 1 marca sprzed 10 lat + ostatnie dni i prognoza 16 dni.

Źródła (decyzja 22.11.2026, jak w sprawdzonej starej aplikacji):
- historia: NASA POWER (główne; bez dziennego limitu, ET0 FAO-56 liczone w aplikacji), zapas: Open-Meteo Archive.
  Przełącznik KOWR_METEO_PRIMARY = nasa_power | open_meteo (drugie źródło zawsze jest zapasem);
- luka kilku ostatnich dni i prognoza 16 dni: Open-Meteo Forecast. Gdy nie odpowie (np. HTTP 429), ocena i tak
  powstaje: dalej niż dane sięgają działają scenariusze z poprzednich lat, a provenance dostaje status `partial`
  z opisem, czego brakuje (bez cichej wartości domyślnej).
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

import httpx

from app.models import Meteo, MeteoDay, Parcel
from app.sources import nasa_power
from app.sources.base import EmptyResult, SourceAdapter, SourceError, fetch_bytes

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DAILY = ["precipitation_sum", "et0_fao_evapotranspiration", "temperature_2m_max", "temperature_2m_min"]
RECENT_DAYS = 10          # ile ostatnich dni dociągamy z prognozy (POWER ma kilka dni opóźnienia, archiwum ok. 5)
YEARS_BACK = 10
OM_RESOLUTION = "Open-Meteo (ERA5 / ERA5-Land), ok. 0,1–0,25°"


def primary() -> str:
    v = os.environ.get("KOWR_METEO_PRIMARY", "nasa_power").strip().lower()
    return v if v in ("nasa_power", "open_meteo") else "nasa_power"


def _days(d: dict) -> list[MeteoDay]:
    return [MeteoDay(date=t, p_mm=p, et0_mm=e, tmax=tx, tmin=tn)
            for t, p, e, tx, tn in zip(d["time"], d["precipitation_sum"], d["et0_fao_evapotranspiration"],
                                       d["temperature_2m_max"], d["temperature_2m_min"])]


def history_start(as_of: date, years_back: int = YEARS_BACK) -> date:
    return date(as_of.year - years_back, 3, 1)


def _why(exc: Exception) -> str:
    if isinstance(exc, SourceError):
        return str(exc)
    if isinstance(exc, httpx.TimeoutException):
        return "brak odpowiedzi w limicie czasu"
    return f"błąd połączenia ({type(exc).__name__})"


async def _open_meteo_archive(client, lon, lat, start: date, end: date) -> list[MeteoDay]:
    _, _, body = await fetch_bytes(client, "GET", ARCHIVE_URL, params={
        "latitude": lat, "longitude": lon, "daily": ",".join(DAILY), "timezone": "Europe/Warsaw",
        "start_date": start.isoformat(), "end_date": end.isoformat()})
    days = [d for d in _days(json.loads(body)["daily"]) if d.p_mm is not None and d.et0_mm is not None]
    if not days:
        raise EmptyResult("Open-Meteo nie ma danych dla tego punktu")
    return days


class MeteoAdapter(SourceAdapter[Meteo]):
    name = "Pogoda: NASA POWER i Open-Meteo"
    licence = "NASA POWER (dane publiczne NASA); Open-Meteo CC BY 4.0"
    timeout_s = 14.0

    def __init__(self, years_back: int = YEARS_BACK):
        self.years_back = years_back

    async def _history(self, client, lon, lat, start: date, end: date) -> tuple[list[MeteoDay], str, list[str]]:
        """Historia z głównego źródła, a gdy zawiedzie – z zapasowego. Zwraca (dni, nazwa źródła, uwagi)."""
        order = ["nasa_power", "open_meteo"] if primary() == "nasa_power" else ["open_meteo", "nasa_power"]
        notes: list[str] = []
        last: Exception | None = None
        for src in order:
            try:
                if src == "nasa_power":
                    return await nasa_power.fetch_history(client, lon, lat, start, end), src, notes
                return await _open_meteo_archive(client, lon, lat, start, end), src, notes
            except (SourceError, httpx.HTTPError, ValueError, KeyError) as exc:
                last = exc
                notes.append(f"{'NASA POWER' if src == 'nasa_power' else 'Open-Meteo (archiwum)'}: {_why(exc)}")
        raise SourceError("; ".join(notes)) from last

    async def _fetch(self, client: httpx.AsyncClient, parcel: Parcel, as_of: date):
        lon, lat = parcel.centroid
        today = date.today()
        end = min(as_of, today)
        daily, src, notes = await self._history(client, lon, lat, history_start(as_of, self.years_back), end)
        data_until = daily[-1].date
        resolution = nasa_power.RESOLUTION if src == "nasa_power" else OM_RESOLUTION
        if src != primary():
            notes.insert(0, f"historia z zapasowego źródła ({'NASA POWER' if src == 'nasa_power' else 'Open-Meteo'})")

        forecast: list[MeteoDay] = []
        needs_recent = as_of >= today - timedelta(days=RECENT_DAYS)
        if needs_recent:
            try:
                _, _, body = await fetch_bytes(client, "GET", FORECAST_URL, params={
                    "latitude": lat, "longitude": lon, "daily": ",".join(DAILY), "timezone": "Europe/Warsaw",
                    "past_days": RECENT_DAYS + 2, "forecast_days": 16})
                for day in _days(json.loads(body)["daily"]):
                    if day.p_mm is None or day.et0_mm is None:
                        continue
                    if data_until < day.date <= as_of:
                        daily.append(day)          # dociągnięcie luki do dnia analizy (ten sam wzór ET0 FAO-56)
                    elif day.date > as_of:
                        forecast.append(day)
                if daily[-1].date > data_until:
                    notes.append(f"dni {data_until + timedelta(days=1):%d.%m}–{daily[-1].date:%d.%m} z Open-Meteo (prognoza)")
            except (SourceError, httpx.HTTPError, ValueError, KeyError) as exc:
                notes.append(f"prognoza i ostatnie dni (Open-Meteo) niedostępne: {_why(exc)}; dalej scenariusze z lat ubiegłych")
        meteo = Meteo(daily=daily, forecast=forecast, resolution=resolution, history_source=src, notes=notes,
                      complete=not (needs_recent and not forecast))
        return meteo, daily[-1].date
