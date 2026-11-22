"""Pełne pobranie działki do cache (do testów i prezentacji dla mentorów).

    cd backend && python -m app.prefetch 046101_1.0445.7 [kolejne numery…]

Długie limity czasu (Overpass do 90 s, pozostałe do 60 s), 20 lat pogody, do 20 scen Sentinel-2 z NDVI.
Źródła, które znów zawiodą, a były w poprzednim zapisie, zostają z zapisu. Uwaga: zużywa limit Open-Meteo
(20 lat ≈ 560 „wywołań” z dziennej puli 10 000 na adres IP) – uruchamiać z sieci, gdzie Open-Meteo odpowiada.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date

from app import cache
from app.api.context import gather
from app.sources import uldk
from app.sources.base import make_client


async def prefetch(parcel_id: str) -> None:
    async with make_client() as client:
        saved = cache.load(parcel_id)
        parcel = saved.parcel if saved else await uldk.lookup(client, q=parcel_id)
        print(f"== {parcel.id}: {parcel.gmina}, obręb {parcel.obreb}, {parcel.area_ha} ha")
        ctx = await gather(client, parcel, date.today(), full=True, previous=saved)
        for p in ctx.provenance:
            print(f"   {p.status:8s} {p.mode:8s} {p.latency_ms:7d} ms  {p.source[:45]:45s} {p.note or ''}")
        if ctx.meteo is None:
            print("   BRAK POGODY – nie zapisuję (bez pogody nie ma oceny).")
            return
        meta = cache.save(ctx, origin="pelne_pobranie")
        print(f"   zapisano {meta['saved_at']}; pogoda od {ctx.meteo.daily[0].date}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Podaj numer działki, np. python -m app.prefetch 046101_1.0445.7")
    for pid in sys.argv[1:]:
        asyncio.run(prefetch(pid))
