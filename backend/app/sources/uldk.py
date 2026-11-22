"""ULDK GUGiK: identyfikacja działki i geometria (EPSG:4326)."""

from __future__ import annotations

import asyncio
import re

import httpx

from app.geo import ring_area_m2
from app.models import Parcel
from app.sources.base import SourceError, fetch_bytes

URL = "https://uldk.gugik.gov.pl/"
TIMEOUT_S = 3.0
LICENCE = "GUGiK, ULDK – bezpłatnie"
MAX_BYTES = 1024 * 1024
FIELDS = ["geom_wkt", "teryt", "voivodeship", "county", "commune", "region", "parcel"]
PARCEL_ID_RE = re.compile(r"^\d{6}_\d\.\d{4}(\.AR_\d+)?\.\S+$")


class ParcelNotFound(Exception):
    pass


class UldkUnavailable(Exception):
    pass


def parse_wkt(wkt: str) -> list[list[list[float]]]:
    """POLYGON/MULTIPOLYGON WKT (lon lat) → lista pierścieni [[lon, lat], ...]."""
    wkt = wkt.split(";", 1)[1] if wkt.upper().startswith("SRID=") else wkt
    rings = []
    for ring in re.findall(r"\(([^()]+)\)", wkt):
        rings.append([[float(v) for v in pair.split()[:2]] for pair in ring.split(",")])
    return rings


def centroid(ring: list[list[float]]) -> list[float]:
    """Środek ciężkości wielokąta (wzór z polem), w stopniach; dla działek wystarczający."""
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        cr = x1 * y2 - x2 * y1
        a += cr
        cx += (x1 + x2) * cr
        cy += (y1 + y2) * cr
    if abs(a) < 1e-15:
        return [sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)]
    return [round(cx / (3 * a), 7), round(cy / (3 * a), 7)]


def parcel_from_row(row: list[str]) -> Parcel:
    d = dict(zip(FIELDS, row))
    rings = parse_wkt(d.get("geom_wkt", ""))
    if not rings:
        raise ParcelNotFound("ULDK zwrócił działkę bez geometrii.")
    area = ring_area_m2(rings[0]) - sum(ring_area_m2(r) for r in rings[1:])
    pid = d.get("teryt", "")
    m = re.match(r"^(\d{6})_(\d)\.(\d{4})", pid)
    return Parcel(id=pid, teryt7=(m.group(1) + m.group(2)) if m else None,
                  voivodeship=d.get("voivodeship"), county=d.get("county"), gmina=d.get("commune"),
                  obreb=d.get("region"), number=d.get("parcel"), rings=rings,
                  centroid=centroid(rings[0]), area_ha=round(area / 10000, 4))


async def _get_text(client: httpx.AsyncClient, params: dict) -> str:
    """ULDK przy przeciążeniu odpowiada 302 na integracja01.gugik.gov.pl/resp/uldk.php (bez parametrów),
    a tamten adres zwraca niekończący się strumień gzip (zmierzone 21.11). Dlatego: bez śledzenia
    przekierowań, limit rozmiaru i jedna powtórka po krótkiej przerwie. Poprawna odpowiedź trwa ok. 0,2 s,
    więc powtórka mieści się w limicie 3 s (wyjątek od zasady „bez ponowień”)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + TIMEOUT_S
    last_exc: Exception | None = None
    for attempt in range(2):
        if attempt:
            await asyncio.sleep(0.4)
        remaining = deadline - loop.time()
        if remaining <= 0.2:
            break
        try:
            _, ctype, body = await asyncio.wait_for(
                fetch_bytes(client, "GET", URL, max_bytes=MAX_BYTES, params=params, follow_redirects=False),
                remaining)
        except (asyncio.TimeoutError, httpx.HTTPError, SourceError) as exc:
            last_exc = exc
            continue
        if "html" in ctype.lower():
            last_exc = SourceError("ULDK zwrócił HTML zamiast danych")
            continue
        return body.decode("utf-8", "replace").strip()
    raise UldkUnavailable("ULDK chwilowo nie odpowiada poprawnie, spróbuj za chwilę.") from last_exc


async def lookup(client: httpx.AsyncClient, q: str | None = None,
                 lat: float | None = None, lon: float | None = None) -> Parcel:
    if lat is not None and lon is not None:
        params = {"request": "GetParcelByXY", "xy": f"{lon},{lat},4326"}
    elif q and PARCEL_ID_RE.match(q.strip()):
        params = {"request": "GetParcelById", "id": q.strip()}
    elif q:
        params = {"request": "GetParcelByIdOrNr", "id": q.strip()}
    else:
        raise ParcelNotFound("Podaj numer działki albo kliknij na mapie.")
    params |= {"result": ",".join(FIELDS), "srid": "4326"}
    text = await _get_text(client, params)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or not lines[0].strip().startswith("0"):
        raise ParcelNotFound("Nie znaleziono działki. Sprawdź numer albo kliknij działkę na mapie.")
    rows = [ln.split("|") for ln in lines[1:]]
    if not rows:
        raise ParcelNotFound("Nie znaleziono działki. Sprawdź numer albo kliknij działkę na mapie.")
    return parcel_from_row(rows[0])
