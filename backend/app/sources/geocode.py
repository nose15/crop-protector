"""Wyszukiwanie adresu: Usługa Geokodowania GUGiK (UUG), wynik w WGS84.

https://services.gugik.gov.pl/uug/?request=GetAddress&address=<miejscowość, ulica numer>&srid=4326
UUG wymaga przecinka między miejscowością a ulicą („Toruń Szeroka 1” nic nie znajduje, „Toruń, Szeroka 1” – tak),
więc przy braku wyników próbujemy też wariantu z przecinkiem po pierwszym wyrazie.
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx

from app.sources.base import SourceError, fetch_bytes

URL = "https://services.gugik.gov.pl/uug/"
TIMEOUT_S = 3.0
MIN_ACCURACY = 0.9      # UUG dopasowuje nazwy przybliżenie („Szeroka” → „Szewska” z dokładnością 0,6); bierzemy tylko pewne
MAX_BYTES = 256 * 1024


def parse(body: bytes) -> list[dict]:
    data = json.loads(body)
    out = []
    for r in (data.get("results") or {}).values():
        try:
            lon, lat = float(r["x"]), float(r["y"])
            accuracy = float(r.get("accuracy", 1))
        except (KeyError, TypeError, ValueError):
            continue
        if accuracy < MIN_ACCURACY:
            continue
        street = r.get("street") or ""
        label = ", ".join(x for x in (r.get("city"), f"{street} {r.get('number') or ''}".strip()) if x)
        out.append({"label": label, "lat": lat, "lon": lon, "teryt": r.get("teryt")})
    return out


def variants(address: str) -> list[str]:
    a = re.sub(r"\s+", " ", address.strip())
    out = [a]
    if "," not in a and " " in a:
        city, rest = a.split(" ", 1)
        out.append(f"{city}, {rest}")
    return out


async def geocode(client: httpx.AsyncClient, address: str) -> list[dict]:
    """Lista dopasowań (najlepsze pierwsze). Pusta, gdy adres nie istnieje. SourceError przy awarii usługi."""
    for a in variants(address):
        params = {"request": "GetAddress", "address": a, "srid": "4326"}
        try:
            _, _, body = await asyncio.wait_for(fetch_bytes(client, "GET", URL, max_bytes=MAX_BYTES, params=params), TIMEOUT_S)
        except asyncio.TimeoutError as exc:
            raise SourceError("wyszukiwarka adresów nie odpowiedziała") from exc
        found = parse(body)
        if found:
            return found
    return []
