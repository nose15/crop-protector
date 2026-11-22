"""/api/context: wszystkie źródła równolegle, z plikowym cache (app/cache.py).

- Trafienie w cache (ta sama działka, cache obejmuje dzień analizy): zwracamy zapis bez żadnych zapytań.
- `refresh=true` albo brak w cache: pobieramy na żywo. Źródła, które teraz zawiodły, a w zapisie mają dane,
  bierzemy z zapisu (provenance.mode = "cache", z datą). Wynik zapisujemy, jeśli jest pogoda.
- Tryb pełny (`gather(full=True)`, używany przez app/prefetch.py): długie limity, 20 lat pogody, więcej scen.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx
from fastapi import APIRouter, HTTPException, Request

from app import baseline, cache
from app.models import ContextRequest, Parcel, ParcelContext, Provenance, Soil
from app.sources.base import now_iso
from app.sources.iung import IungSoilAdapter
from app.sources.meteo import MeteoAdapter, primary
from app.sources.satellite import SatelliteAdapter
from app.sources.soilgrids import SoilGridsAdapter
from app.sources.terrain import TerrainAdapter
from app.sources.water import WaterAdapter

router = APIRouter()
CONTEXT_LIMIT_S = 28.0
FULL_LIMIT_S = 180.0
MAX_YEARS_BACK = 10
FULL_YEARS_BACK = 20         # w cache 20 lat pogody: dzień analizy może być do 10 lat wstecz
FIELDS = ("meteo", "iung", "soilgrids", "terrain", "water", "satellite")


def constants_provenance() -> list[Provenance]:
    return [Provenance(source="Progi KBW – Dz.U. 2019 poz. 739 (załącznik)", status="ok", mode="constant",
                       retrieved_at=now_iso(), licence="akt prawny, domena publiczna")]


def adapters(full: bool) -> dict:
    a = {"meteo": MeteoAdapter(years_back=FULL_YEARS_BACK if full else MAX_YEARS_BACK), "iung": IungSoilAdapter(),
         "soilgrids": SoilGridsAdapter(), "terrain": TerrainAdapter(), "water": WaterAdapter(),
         "satellite": SatelliteAdapter(full=full)}
    if full:
        for k in ("meteo", "iung", "soilgrids", "terrain"):
            a[k].timeout_s = 60.0
        a["water"].timeout_s, a["water"].query_timeout_s = 90.0, 80
    return a


def _get(ctx: ParcelContext, key: str):
    return ctx.soil.iung if key == "iung" else ctx.soil.soilgrids if key == "soilgrids" else getattr(ctx, key)


async def gather(client: httpx.AsyncClient, parcel: Parcel, as_of: date, full: bool = False,
                 previous: ParcelContext | None = None) -> ParcelContext:
    ads = adapters(full)
    tasks = {k: asyncio.create_task(a.fetch(client, parcel, as_of)) for k, a in ads.items()}
    done, pending = await asyncio.wait(tasks.values(), timeout=FULL_LIMIT_S if full else CONTEXT_LIMIT_S)
    for t in pending:                       # każdy adapter ma własny, krótszy limit; to tylko bezpiecznik
        t.cancel()
    res = {k: (t.result() if t in done else None) for k, t in tasks.items()}
    data = {k: (r.data if r else None) for k, r in res.items()}
    prov = {k: r.provenance for k, r in res.items() if r}
    met = res.get("meteo")
    if met and met.data:                        # skąd historia i czego brakuje (np. prognoza przy HTTP 429)
        if met.data.notes:
            met.provenance.note = "; ".join(met.data.notes)
        if not met.data.complete or met.data.history_source != primary():
            met.provenance.status = "partial"
    sat = res.get("satellite")
    if sat and sat.data and sat.data.get("partial"):
        sat.provenance.status = "partial"
        sat.provenance.note = "nie wszystkie sceny zdążyły się pobrać w limicie czasu"

    # źródła, które teraz zawiodły, a w poprzednim zapisie mają dane: bierzemy z zapisu
    if previous is not None:
        saved_at = (previous.cache or {}).get("saved_at", "")[:16].replace("T", " ")
        old_prov = {p.source: p for p in previous.provenance}
        for k in FIELDS:
            old = _get(previous, k)
            if data[k] is None and old is not None and k in prov:
                data[k] = old
                p = old_prov.get(prov[k].source) or prov[k]
                prov[k] = p.model_copy(update={"mode": "cache", "note": f"z zapisu ({saved_at}); teraz: {prov[k].note or prov[k].status}"})

    provenance = list(prov.values()) + constants_provenance()
    partial = any(p.status != "ok" for p in provenance if p.mode == "live" and "Sentinel" not in p.source)
    return ParcelContext(as_of=as_of, partial=partial, parcel=parcel, meteo=data["meteo"],
                         soil=Soil(iung=data["iung"], soilgrids=data["soilgrids"]), terrain=data["terrain"],
                         water=data["water"], satellite=data["satellite"], provenance=provenance)


def covers(ctx: ParcelContext, as_of: date) -> bool:
    """Czy zapis wystarcza dla dnia analizy: zapis nie starszy niż D i pogoda od 1 marca sprzed 10 lat."""
    if ctx.meteo is None or not ctx.meteo.daily or as_of > ctx.as_of:
        return False
    return min(d.date for d in ctx.meteo.daily) <= date(as_of.year - MAX_YEARS_BACK, 3, 1)


@router.post("/api/context", response_model=ParcelContext)
async def post_context(body: ContextRequest, request: Request, refresh: bool = False):
    as_of = body.as_of or date.today()
    if as_of > date.today() or as_of < date.today() - timedelta(days=366 * MAX_YEARS_BACK + 3):
        raise HTTPException(422, {"error": "invalid_request",
                                  "message": "Data analizy musi być z ostatnich 10 lat i nie z przyszłości."})
    # baza satelitarna z lat ubiegłych (openEO, kilka minut): startuje już teraz, w tle, żeby była gotowa,
    # zanim rolnik obejrzy wynik; frontend sam przeliczy wynik, gdy baza się pojawi (GET /api/baseline/{numer})
    baseline.ensure(body.parcel, as_of)
    saved = cache.load(body.parcel.id)
    if saved and not refresh and covers(saved, as_of):
        return saved.model_copy(update={"cache": {**(saved.cache or {}), "hit": True}})

    ctx = await gather(request.app.state.http, body.parcel, as_of, previous=saved)
    if ctx.meteo is not None and as_of == date.today():
        ctx = ctx.model_copy(update={"cache": {**cache.save(ctx, origin="na_zywo"), "hit": False}})
    return ctx
