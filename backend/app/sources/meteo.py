"""Open-Meteo: archiwum dobowe (ERA5 / ERA5-Land) od 1 marca sprzed 10 lat + prognoza 16 dni."""

from __future__ import annotations

import json
from datetime import date, timedelta

import httpx

from app.models import Meteo, MeteoDay, Parcel
from app.sources.base import EmptyResult, SourceAdapter, fetch_bytes

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DAILY = ["precipitation_sum", "et0_fao_evapotranspiration", "temperature_2m_max", "temperature_2m_min"]
ARCHIVE_LAG_DAYS = 5      # archiwum ma kilka dni opóźnienia
YEARS_BACK = 10


def _days(d: dict) -> list[MeteoDay]:
    return [MeteoDay(date=t, p_mm=p, et0_mm=e, tmax=tx, tmin=tn)
            for t, p, e, tx, tn in zip(d["time"], d["precipitation_sum"], d["et0_fao_evapotranspiration"],
                                       d["temperature_2m_max"], d["temperature_2m_min"])]


def history_start(as_of: date, years_back: int = YEARS_BACK) -> date:
    return date(as_of.year - years_back, 3, 1)


class MeteoAdapter(SourceAdapter[Meteo]):
    name = "Open-Meteo (archiwum ERA5 + prognoza)"
    licence = "CC BY 4.0, Open-Meteo.com"
    timeout_s = 8.0

    def __init__(self, years_back: int = YEARS_BACK):
        self.years_back = years_back

    async def _fetch(self, client: httpx.AsyncClient, parcel: Parcel, as_of: date):
        lon, lat = parcel.centroid
        today = date.today()
        base = {"latitude": lat, "longitude": lon, "daily": ",".join(DAILY), "timezone": "Europe/Warsaw"}
        archive_end = min(as_of, today - timedelta(days=ARCHIVE_LAG_DAYS))
        _, _, body = await fetch_bytes(client, "GET", ARCHIVE_URL, params=base | {
            "start_date": history_start(as_of, self.years_back).isoformat(), "end_date": archive_end.isoformat()})
        daily = _days(json.loads(body)["daily"])
        if not daily:
            raise EmptyResult("brak danych pogodowych dla tego punktu")
        data_until = daily[-1].date

        forecast: list[MeteoDay] = []
        if as_of >= today - timedelta(days=ARCHIVE_LAG_DAYS + 2):
            _, _, body = await fetch_bytes(client, "GET", FORECAST_URL, params=base | {
                "past_days": ARCHIVE_LAG_DAYS + 3, "forecast_days": 16})
            for day in _days(json.loads(body)["daily"]):
                if data_until < day.date <= as_of:
                    daily.append(day)            # dociągnięcie luki archiwum do dnia analizy
                elif day.date > as_of:
                    forecast.append(day)
        return Meteo(daily=daily, forecast=forecast, resolution="ERA5 / ERA5-Land, ok. 0,1–0,25°"), data_until
