"""Pogoda z NASA POWER (ET0 FAO-56 liczone w aplikacji) i zapas Open-Meteo. Bez sieci (httpx.MockTransport)."""

import asyncio
import math
from datetime import date, timedelta

import httpx

from app.engine.et0 import e0, fao_pm
from app.models import Parcel
from app.sources import meteo, nasa_power

RING = [[18.130, 53.100], [18.140, 53.100], [18.140, 53.110], [18.130, 53.110], [18.130, 53.100]]
PARCEL = Parcel(id="000000_0.0000.1", rings=[RING], centroid=[18.135, 53.105], area_ha=7.4)


def test_et0_fao56_example_18():
    """FAO-56 przykład 18 (Uccle, 6 lipca): Tmax 21,5, Tmin 12,3, ea 1,409 kPa, u2 2,078 m/s, Rs 22,07 MJ → 3,9 mm/d."""
    ln = math.log(1.409 / 0.6108)
    tdew = 237.3 * ln / (17.27 - ln)
    assert abs(float(e0(tdew)) - 1.409) < 1e-3
    et0 = fao_pm([21.5], [12.3], [187], 50.8, 100, u2=[2.078], tdew=[tdew], rs=[22.07])
    assert abs(float(et0[0]) - 3.9) < 0.1


def _power_payload(days: list[str], tmax=20.0, missing_last=0) -> dict:
    p = {k: {} for k in ("PRECTOTCORR", "T2M_MAX", "T2M_MIN", "WS2M", "T2MDEW", "ALLSKY_SFC_SW_DWN")}
    for i, d in enumerate(days):
        miss = i >= len(days) - missing_last
        for k, v in (("PRECTOTCORR", 1.5), ("T2M_MAX", tmax), ("T2M_MIN", 10.0), ("WS2M", 2.0),
                     ("T2MDEW", 8.0), ("ALLSKY_SFC_SW_DWN", 18.0)):
            p[k][d] = -999.0 if miss else v
    return {"geometry": {"coordinates": [18.1, 53.1, 70.0]}, "header": {"fill_value": -999.0},
            "properties": {"parameter": p}}


def test_power_parse_computes_et0_and_keeps_gaps():
    days = nasa_power.parse(_power_payload(["20250601", "20250602", "20250603"], missing_last=1), lat=53.1)
    assert [d.date for d in days] == [date(2025, 6, 1), date(2025, 6, 2), date(2025, 6, 3)]
    assert days[0].p_mm == 1.5 and days[0].tmax == 20.0
    assert 2.0 < days[0].et0_mm < 5.0                      # czerwcowe ET0 FAO-PM w Polsce
    assert days[2].p_mm is None and days[2].et0_mm is None  # -999 to brak, nie zero


def _transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_meteo_power_primary_and_forecast_failure_is_partial(monkeypatch):
    """Historia z POWER; Open-Meteo prognoza 429 → ocena i tak ma pogodę, a w uwagach jest, czego brakuje."""
    monkeypatch.delenv("KOWR_METEO_PRIMARY", raising=False)
    today = date.today()
    keys = [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(40, 2, -1)]

    def handler(req: httpx.Request):
        if "power.larc.nasa.gov" in str(req.url):
            return httpx.Response(200, json=_power_payload(keys))
        return httpx.Response(429, json={"reason": "Daily API request limit exceeded"})

    async def go():
        async with _transport(handler) as c:
            return await meteo.MeteoAdapter().fetch(c, PARCEL, today)
    res = asyncio.run(go())
    assert res.provenance.status == "ok" and res.data.history_source == "nasa_power"
    assert not res.data.complete and any("prognoza" in n for n in res.data.notes)
    assert res.data.daily[-1].date == today - timedelta(days=3)


def test_meteo_falls_back_to_open_meteo_when_power_fails(monkeypatch):
    monkeypatch.delenv("KOWR_METEO_PRIMARY", raising=False)
    d0 = date(2024, 6, 1)
    days = [(d0 + timedelta(days=i)).isoformat() for i in range(5)]

    def handler(req: httpx.Request):
        if "power.larc.nasa.gov" in str(req.url):
            return httpx.Response(503)
        return httpx.Response(200, json={"daily": {"time": days, "precipitation_sum": [1.0] * 5,
                                                   "et0_fao_evapotranspiration": [3.0] * 5,
                                                   "temperature_2m_max": [20.0] * 5, "temperature_2m_min": [10.0] * 5}})

    async def go():
        async with _transport(handler) as c:
            return await meteo.MeteoAdapter().fetch(c, PARCEL, date(2024, 6, 5))
    res = asyncio.run(go())
    assert res.data.history_source == "open_meteo"
    assert res.data.notes[0].startswith("historia z zapasowego źródła")


def test_meteo_both_sources_fail_reports_error(monkeypatch):
    def handler(req):
        return httpx.Response(503)

    async def go():
        async with _transport(handler) as c:
            return await meteo.MeteoAdapter().fetch(c, PARCEL, date(2024, 6, 5))
    res = asyncio.run(go())
    assert res.data is None and res.provenance.status == "error"
    assert "NASA POWER" in res.provenance.note and "Open-Meteo" in res.provenance.note
