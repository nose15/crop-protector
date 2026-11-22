"""Baza wieloletnia Sentinel-2 działki (openEO CDSE): plik w cache + zadanie w tle.

Zasada (metodyka-openeo.md §1): openEO nigdy nie stoi na ścieżce odpowiedzi (/api/context ma 28 s, zadanie
wsadowe trwa minuty). Gdy bazy brak, raport powstaje od razu bez porównania satelitarnego („baza w przygotowaniu”),
a w tle startuje JEDNO zadanie na działkę; kolejna analiza już z niej korzysta. openEO dostarcza surowy szereg
(NDVI, NDMI, udział ważnych pikseli) – anomalię i jej wpływ na pewność liczy silnik przy każdym żądaniu
(app/engine/s2_anomaly.py).

Zakres zadania: od 1 marca BASE_FIRST_YEAR do dziś (jedno zadanie obsługuje każdy dzień analizy od 2019 r.);
zapis odświeżamy, gdy dzień analizy wypada po końcu zapisu, a zapis ma ponad STALE_DAYS dni.
Plik: KOWR_CACHE_DIR/s2base_<numer>.json.gz (poza repozytorium); `python -m app.prefetch` liczy bazę od razu.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import re
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.cache import SEED_DIR, cache_dir
from app.models import Parcel
from app.sources import openeo_cdse
from app.sources.base import make_client

BASE_FIRST_YEAR = 2018      # K2 metodyki: od 2018 (zharmonizowany L2A w CDSE, 8–9 sezonów bazy)
STALE_DAYS = 10
SEASON = ("03-01", "11-30")  # sceny zimowe odrzucamy (śnieg, goła gleba)

_tasks: dict[str, asyncio.Task] = {}
_state: dict[str, dict] = {}


def _name(parcel_id: str) -> str:
    return "s2base_" + re.sub(r"[^0-9A-Za-z._-]", "_", parcel_id) + ".json.gz"


def _path(parcel_id: str) -> Path:
    return cache_dir() / _name(parcel_id)


def load(parcel_id: str) -> dict | None:
    for p in (_path(parcel_id), SEED_DIR / _name(parcel_id)):
        if p.exists():
            with gzip.open(p, "rt", encoding="utf-8") as f:
                return json.load(f)
    return None


def save(parcel_id: str, data: dict) -> None:
    tmp = _path(parcel_id).with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(_path(parcel_id))


def covers(base: dict | None, d: date) -> bool:
    """Czy zapis obejmuje lata bazowe i dzień analizy d (bez sięgania po dane z przyszłości)."""
    if not base:
        return False
    until = date.fromisoformat(base["until"])
    return until >= d or (date.today() - until).days <= STALE_DAYS and d > until and d <= date.today()


def status(parcel_id: str) -> dict:
    st = dict(_state.get(parcel_id, {}))
    t = _tasks.get(parcel_id)
    if t and not t.done():
        st["state"] = "liczenie"
    return st or {"state": "brak"}


def running() -> int:
    return sum(1 for t in _tasks.values() if not t.done())


async def compute(client: httpx.AsyncClient, parcel: Parcel) -> dict:
    """Jedno zadanie wsadowe openEO dla działki; zapisuje i zwraca bazę."""
    start, end = date(BASE_FIRST_YEAR, 3, 1), date.today()
    obs, secs = await openeo_cdse.run_job(client, parcel.rings[0], start, end, f"KOWR baza S2 {parcel.id}")
    obs = [o for o in obs if SEASON[0] <= o["date"][5:] <= SEASON[1]]
    data = {"parcel_id": parcel.id, "from": start.isoformat(), "until": end.isoformat(), "obs": obs,
            "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "job_seconds": round(secs), "source": openeo_cdse.NAME, "licence": openeo_cdse.LICENCE}
    save(parcel.id, data)
    return data


async def _run(parcel: Parcel) -> None:
    _state[parcel.id] = {"state": "liczenie", "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        async with make_client() as client:
            data = await compute(client, parcel)
        _state[parcel.id] = {"state": "gotowe", "obs": len(data["obs"]), "job_seconds": data["job_seconds"]}
    except Exception as exc:  # noqa: BLE001 – błąd zadania nie może zatrzymać aplikacji
        traceback.print_exc()
        _state[parcel.id] = {"state": "blad", "error": str(exc)[:200]}


def ensure(parcel: Parcel, d: date) -> dict:
    """Zwraca stan bazy dla dnia d; gdy jej brak lub jest nieaktualna, uruchamia zadanie w tle (jedno na działkę)."""
    base = load(parcel.id)
    if covers(base, d):
        return {"state": "gotowe"}
    if not openeo_cdse.configured():
        return {"state": "nieskonfigurowane"}
    t = _tasks.get(parcel.id)
    if t and not t.done():
        return {"state": "liczenie"}
    if _state.get(parcel.id, {}).get("state") == "blad" and base is None:
        return status(parcel.id)                    # nie ponawiamy w kółko zadania, które właśnie padło
    try:
        _tasks[parcel.id] = asyncio.get_running_loop().create_task(_run(parcel))
    except RuntimeError:                            # brak pętli zdarzeń (np. wywołanie synchroniczne w testach)
        return {"state": "brak"}
    return {"state": "liczenie"}
