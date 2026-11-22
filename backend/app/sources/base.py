"""Wspólny kontrakt adapterów źródeł danych.

Adapter nigdy nie rzuca wyjątku na zewnątrz: błąd sieci, limit czasu albo zły format
zamienia na `Provenance.status`. Awaria jednego źródła nie blokuje reszty.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Generic, TypeVar

import httpx

from app.models import Parcel, Provenance

T = TypeVar("T")

USER_AGENT = "hacknation-kowr/0.2"
MAX_BODY_BYTES = 8 * 1024 * 1024   # ULDK potrafi zwrócić >100 MB HTML zamiast odpowiedzi


class SourceError(Exception):
    """Błąd z krótkim, czytelnym dla rolnika opisem (trafia do Provenance.note)."""


class EmptyResult(SourceError):
    """Źródło odpowiedziało, ale nie ma danych dla tego miejsca."""


@dataclass
class AdapterResult(Generic[T]):
    data: T | None
    provenance: Provenance


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                             timeout=httpx.Timeout(30.0, connect=5.0))


async def fetch_bytes(client: httpx.AsyncClient, method: str, url: str, max_bytes: int = MAX_BODY_BYTES,
                      **kw: Any) -> tuple[int, str, bytes]:
    """Pobiera odpowiedź strumieniem z limitem rozmiaru. Zwraca (status, content-type, body)."""
    body = bytearray()
    async with client.stream(method, url, **kw) as r:
        async for chunk in r.aiter_bytes():
            body += chunk
            if len(body) > max_bytes:
                raise SourceError(f"odpowiedź większa niż {max_bytes // 1024} kB")
        if 300 <= r.status_code < 400:
            raise SourceError(f"usługa przekierowała zapytanie (HTTP {r.status_code}), prawdopodobnie przeciążenie")
        if r.status_code == 429:
            raise SourceError("przekroczony limit zapytań usługi (429)")
        if r.status_code >= 400:
            raise SourceError(f"błąd usługi HTTP {r.status_code}")
        return r.status_code, r.headers.get("content-type", ""), bytes(body)


async def guarded(name: str, licence: str, timeout_s: float,
                  work: Callable[[], Awaitable[tuple[T, date | None]]]) -> AdapterResult[T]:
    """Uruchamia `work()` z twardym limitem czasu. `work` zwraca (dane, data_until)."""
    t0 = time.perf_counter()
    status, note, data, until = "ok", None, None, None
    try:
        data, until = await asyncio.wait_for(work(), timeout=timeout_s)
    except asyncio.TimeoutError:
        status, note = "timeout", f"brak odpowiedzi w {timeout_s:g} s"
    except EmptyResult as exc:
        status, note = "empty", str(exc)
    except SourceError as exc:
        status, note = "error", str(exc)
    except httpx.HTTPError as exc:
        status, note = "error", f"błąd połączenia ({type(exc).__name__})"
    except Exception as exc:  # zły format itp.; nie pokazujemy stack trace w UI
        status, note = "error", f"nieoczekiwany format danych ({type(exc).__name__}: {str(exc)[:80]})"
    prov = Provenance(source=name, status=status, mode="live",
                      latency_ms=int((time.perf_counter() - t0) * 1000), retrieved_at=now_iso(),
                      licence=licence, data_until=until, note=note)
    return AdapterResult(data=data, provenance=prov)


class SourceAdapter(Generic[T]):
    name: str
    licence: str
    timeout_s: float

    async def fetch(self, client: httpx.AsyncClient, parcel: Parcel, as_of: date) -> AdapterResult[T]:
        return await guarded(self.name, self.licence, self.timeout_s, lambda: self._fetch(client, parcel, as_of))

    async def _fetch(self, client: httpx.AsyncClient, parcel: Parcel, as_of: date) -> tuple[T, date | None]:
        raise NotImplementedError
