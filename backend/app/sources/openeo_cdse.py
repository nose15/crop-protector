"""openEO w Copernicus Data Space Ecosystem (CDSE): wieloletni szereg NDVI/NDMI działki zadaniem wsadowym.

Metodyka (sprawdzona 21.11.2026, KOWR/metodyka-openeo.md): jedna kostka SENTINEL2_L2A, maska SCL ∈ {4, 5},
NDVI (B08, B04), NDMI (B8A, B11), pasmo VALID (0/1), mediana w obrysie działki pomniejszonym o 10 m.
Mediana VALID = 1 ⇔ ≥ 50% pikseli ważnych (ten sam próg validFrac ≥ 0,5). Wszystkie lata JEDNYM zadaniem
(narzut kolejki CDSE płacony raz; 7 sezonów ≈ 277 s). CDSE SENTINEL2_L2A jest zharmonizowane – bez korekty
−1000 DN (sprawdzone z MPC: różnica NDVI średnio −0,0002 na 128 wspólnych datach).

Bez pakietu `openeo` (zależności uzgodnione w CLAUDE.md): graf procesów leży w app/data/openeo_s2_graph.json
(wygenerowany offline narzędziem tools/gen_openeo_graph.py), a REST API openEO 1.2 wołamy przez httpx.

Logowanie (sekrety tylko w środowisku backendu, nigdy w repo ani we frontendzie), pierwsze dostępne:
1. CDSE_CLIENT_ID + CDSE_CLIENT_SECRET – klient OIDC „client credentials” (serwer, np. Render),
2. CDSE_REFRESH_TOKEN (+ opcjonalnie CDSE_CLIENT_ID; domyślnie publiczny klient openEO CDSE),
3. token zapisany przez backend po poprzednim odświeżeniu (KOWR_CACHE_DIR/.cdse_token.json),
4. token zapisany lokalnie przez klienta `openeo` po jednorazowym logowaniu device flow
   (%APPDATA%/openeo-python-client/refresh-tokens.json albo ~/.local/share/openeo-python-client/…).
Bez żadnego z nich adapter zgłasza „nieskonfigurowane”, a aplikacja działa bez bazy satelitarnej.
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
import os
import time
from datetime import date
from pathlib import Path

import httpx

from app.geo import to_2180
from app.sources.base import SourceError

OPENEO_URL = os.environ.get("KOWR_OPENEO_URL", "https://openeo.dataspace.copernicus.eu/openeo/1.2").rstrip("/")
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
ISSUER = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
PROVIDER = "CDSE"
PUBLIC_CLIENT = "sh-b1c3a958-52d4-40fe-a333-153595d1c71e"   # domyślny klient openEO CDSE (/credentials/oidc)
GRAPH_FILE = Path(__file__).resolve().parents[1] / "data" / "openeo_s2_graph.json"
NAME = "Sentinel-2 L2A przez CDSE openEO (zadanie wsadowe)"
LICENCE = "Copernicus Sentinel data, bezpłatnie (dane zmodyfikowane); konto CDSE, limity darmowego planu"
BUFFER_M = -10.0
MAX_CLOUD = 80
POLL_S = 10
JOB_LIMIT_S = 1800


# --------------------------------------------------------------------------- logowanie

def _cache_dir() -> Path:
    from app.cache import cache_dir
    return cache_dir()


def _token_files() -> list[Path]:
    out = [_cache_dir() / ".cdse_token.json"]
    if os.environ.get("APPDATA"):
        out.append(Path(os.environ["APPDATA"]) / "openeo-python-client" / "refresh-tokens.json")
    out.append(Path.home() / ".local" / "share" / "openeo-python-client" / "refresh-tokens.json")
    return out


def _stored_refresh() -> tuple[str, str] | None:
    """(client_id, refresh_token) z zapisu backendu albo klienta openeo; None, gdy nie ma."""
    for f in _token_files():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if "refresh_token" in data:                                   # zapis backendu
            return data.get("client_id", PUBLIC_CLIENT), data["refresh_token"]
        for client_id, entry in (data.get(ISSUER) or {}).items():     # zapis klienta openeo
            if isinstance(entry, dict) and entry.get("refresh_token"):
                return client_id, entry["refresh_token"]
    return None


def configured() -> bool:
    if os.environ.get("KOWR_OPENEO_DISABLED"):                     # testy i wdrożenia bez bazy satelitarnej
        return False
    return bool((os.environ.get("CDSE_CLIENT_ID") and os.environ.get("CDSE_CLIENT_SECRET"))
                or os.environ.get("CDSE_REFRESH_TOKEN") or _stored_refresh())


async def access_token(client: httpx.AsyncClient) -> str:
    """Token dostępu OIDC CDSE. Odświeżony refresh token (rotacja) zapisujemy w katalogu cache backendu."""
    cid, secret = os.environ.get("CDSE_CLIENT_ID"), os.environ.get("CDSE_CLIENT_SECRET")
    if cid and secret:
        data = {"grant_type": "client_credentials", "client_id": cid, "client_secret": secret}
    else:
        if os.environ.get("CDSE_REFRESH_TOKEN"):
            cid, rt = os.environ.get("CDSE_CLIENT_ID") or PUBLIC_CLIENT, os.environ["CDSE_REFRESH_TOKEN"]
        else:
            stored = _stored_refresh()
            if not stored:
                raise SourceError("brak konta CDSE (CDSE_CLIENT_ID/SECRET albo zapisany token logowania)")
            cid, rt = stored
        data = {"grant_type": "refresh_token", "client_id": cid, "refresh_token": rt}
    r = await client.post(TOKEN_URL, data=data, timeout=20)
    if r.status_code != 200:
        raise SourceError(f"logowanie do CDSE nie powiodło się (HTTP {r.status_code}); zaloguj się ponownie")
    tok = r.json()
    if tok.get("refresh_token") and data["grant_type"] == "refresh_token":
        try:
            f = _cache_dir() / ".cdse_token.json"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"client_id": cid, "refresh_token": tok["refresh_token"]}), encoding="utf-8")
        except OSError:
            pass
    return tok["access_token"]


# --------------------------------------------------------------------------- graf procesów

def _shrink(ring: list[list[float]], meters: float) -> list[list[float]]:
    """Obrys pomniejszony o |meters| (przybliżenie: skalowanie względem środka w EPSG:2180, bez shapely/GEOS).
    Mała działka (< 600 m² po pomniejszeniu) zostaje bez bufora, jak w metodyce."""
    xy = [to_2180(lon, lat) for lon, lat in ring]
    area = abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(xy, xy[1:] + xy[:1]))) / 2
    perim = sum(math.dist(a, b) for a, b in zip(xy, xy[1:] + xy[:1]))
    if area <= 0 or perim <= 0:
        return ring
    new_area = area + meters * perim                                 # A(d) ≈ A + d·P dla małego d (d < 0)
    if new_area < 600:
        return ring
    k = math.sqrt(new_area / area)
    cx = sum(lon for lon, _ in ring[:-1]) / (len(ring) - 1)
    cy = sum(lat for _, lat in ring[:-1]) / (len(ring) - 1)
    return [[cx + (lon - cx) * k, cy + (lat - cy) * k] for lon, lat in ring]


def build_graph(ring: list[list[float]], start: date, end: date) -> dict:
    """Szablon grafu z app/data/openeo_s2_graph.json z podstawionym obrysem i zakresem dat."""
    g = copy.deepcopy(json.loads(GRAPH_FILE.read_text(encoding="utf-8")))
    lons, lats = [p[0] for p in ring], [p[1] for p in ring]
    lc = next(n for n in g.values() if n["process_id"] == "load_collection")["arguments"]
    lc["spatial_extent"] = {"west": min(lons), "south": min(lats), "east": max(lons), "north": max(lats)}
    lc["temporal_extent"] = [start.isoformat(), end.isoformat()]
    lc["properties"]["eo:cloud_cover"]["process_graph"]["lte1"]["arguments"]["y"] = MAX_CLOUD
    agg = next(n for n in g.values() if n["process_id"] == "aggregate_spatial")["arguments"]
    agg["geometries"] = {"type": "Polygon", "coordinates": [_shrink(ring, BUFFER_M)]}
    return g


def parse_timeseries(res: dict) -> list[dict]:
    """{"2022-06-19T00:00:00Z": [[ndvi, ndmi, valid]], …} → obserwacje {date, ndvi, ndmi, valid_frac} (rosnąco).
    Dni bez wartości (wszystko zamaskowane) pomijamy; validFrac = mediana maski (1 ⇔ ≥ 50% pikseli ważnych)."""
    out = []
    for k, v in (res or {}).items():
        vals = v[0] if v and isinstance(v[0], list) else (v or [])
        ndvi = vals[0] if len(vals) > 0 else None
        ndmi = vals[1] if len(vals) > 1 else None
        vf = vals[2] if len(vals) > 2 else None
        if ndvi is None or (isinstance(ndvi, float) and math.isnan(ndvi)):
            continue
        out.append({"date": str(k)[:10], "ndvi": round(float(ndvi), 4),
                    "ndmi": None if ndmi is None else round(float(ndmi), 4),
                    "valid_frac": 0.0 if vf is None else float(vf)})
    return sorted(out, key=lambda o: o["date"])


# --------------------------------------------------------------------------- zadanie wsadowe

async def run_job(client: httpx.AsyncClient, ring: list[list[float]], start: date, end: date, title: str) -> tuple[list[dict], float]:
    """Tworzy, uruchamia i czeka na zadanie wsadowe; zwraca (obserwacje, czas w s). Błędy → SourceError."""
    t0 = time.perf_counter()
    token = await access_token(client)
    h = {"Authorization": f"Bearer oidc/{PROVIDER}/{token}"}
    body = {"title": title, "process": {"process_graph": build_graph(ring, start, end)}}
    r = await client.post(f"{OPENEO_URL}/jobs", json=body, headers=h, timeout=60)
    if r.status_code not in (200, 201):
        raise SourceError(f"openEO: nie utworzono zadania (HTTP {r.status_code}: {r.text[:160]})")
    job_id = r.headers.get("OpenEO-Identifier") or r.headers.get("Location", "").rstrip("/").split("/")[-1]
    r = await client.post(f"{OPENEO_URL}/jobs/{job_id}/results", headers=h, timeout=60)
    if r.status_code not in (200, 202):
        raise SourceError(f"openEO: nie uruchomiono zadania (HTTP {r.status_code})")
    status = "queued"
    while time.perf_counter() - t0 < JOB_LIMIT_S:
        await asyncio.sleep(POLL_S)
        if time.perf_counter() - t0 > 240:                           # token żyje kilka minut – odśwież
            h = {"Authorization": f"Bearer oidc/{PROVIDER}/{await access_token(client)}"}
        r = await client.get(f"{OPENEO_URL}/jobs/{job_id}", headers=h, timeout=60)
        status = r.json().get("status", "unknown") if r.status_code == 200 else "unknown"
        if status in ("finished", "error", "canceled"):
            break
    if status != "finished":
        raise SourceError(f"openEO: zadanie {job_id} zakończone stanem „{status}”")
    r = await client.get(f"{OPENEO_URL}/jobs/{job_id}/results", headers=h, timeout=60)
    assets = (r.json().get("assets") or {}) if r.status_code == 200 else {}
    href = next((a["href"] for name, a in assets.items() if name.endswith(".json") and not name.startswith("job-results")
                 or a.get("type") == "application/json"), None)
    if not href:
        raise SourceError("openEO: zadanie nie zwróciło pliku JSON")
    hd = h if href.startswith(OPENEO_URL) else {}
    r = await client.get(href, headers=hd, timeout=120)
    if r.status_code != 200:
        raise SourceError(f"openEO: nie pobrano wyniku (HTTP {r.status_code})")
    return parse_timeseries(r.json()), time.perf_counter() - t0
