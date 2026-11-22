from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request

from app import cache
from app.models import Parcel
from app.sources import geocode, uldk
from app.sources.base import SourceError

router = APIRouter()

NOT_FOUND = ("Nie znaleźliśmy działki. Wpisz numer działki (np. 046101_1.0445.7), obręb i numer (np. Krzywiń 134/2) "
             "albo adres (np. Krzywiń, Rynek 1), albo kliknij działkę na mapie.")
# adres: zawiera przecinek, skrót ulicy albo słowo + numer domu (np. „Toruń, Szeroka 1”, „ul. Polna 3”)
ADDRESS_HINT = re.compile(r",|\b(ul|al|os|pl)\.\s", re.IGNORECASE)


async def by_address(client, q: str) -> Parcel | None:
    hits = await geocode.geocode(client, q)
    if not hits:
        return None
    h = hits[0]
    p = await uldk.lookup(client, lat=h["lat"], lon=h["lon"])
    return p.model_copy(update={"found_by": "adres", "address": h["label"]})


@router.get("/api/parcel", response_model=Parcel)
async def get_parcel(request: Request, q: str | None = None, lat: float | None = None, lon: float | None = None):
    """Działka po numerze ewidencyjnym, po „obręb numer”, po adresie (UUG GUGiK → punkt → ULDK) albo po punkcie z mapy."""
    q = q.strip() if q else q
    if q:                                   # działka z cache: bez zapytania do ULDK
        saved = cache.load(q)
        if saved:
            return saved.parcel.model_copy(update={"found_by": "zapis"})
    client = request.app.state.http
    try:
        if lat is not None and lon is not None:
            return (await uldk.lookup(client, lat=lat, lon=lon)).model_copy(update={"found_by": "punkt"})
        if not q:
            raise uldk.ParcelNotFound(NOT_FOUND)
        if uldk.PARCEL_ID_RE.match(q):
            return (await uldk.lookup(client, q=q)).model_copy(update={"found_by": "numer"})
        # najpierw to, na co wygląda zapytanie; drugi sposób jako zapas
        order = ("adres", "obreb_numer") if ADDRESS_HINT.search(q) else ("obreb_numer", "adres")
        for how in order:
            try:
                if how == "adres":
                    p = await by_address(client, q)
                    if p:
                        return p
                else:
                    return (await uldk.lookup(client, q=q)).model_copy(update={"found_by": "obreb_numer"})
            except uldk.ParcelNotFound:
                continue
            except SourceError:
                continue                    # wyszukiwarka adresów nie odpowiada: próbujemy drugiego sposobu
        raise uldk.ParcelNotFound(NOT_FOUND)
    except uldk.ParcelNotFound as exc:
        raise HTTPException(404, {"error": "parcel_not_found", "message": str(exc) if str(exc) != "" else NOT_FOUND})
    except uldk.UldkUnavailable as exc:
        raise HTTPException(502, {"error": "uldk_unavailable", "message": str(exc)})
