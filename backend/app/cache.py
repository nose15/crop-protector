"""Plikowy cache kontekstów działek (jeden plik .json.gz na działkę, ostatnia wersja).

Cel: raz pobrać działkę ze wszystkich źródeł (także wolnych i limitowanych), a potem odpytywać ją
po numerze i pokazywać mentorom bez żadnych zapytań do usług zewnętrznych.
Katalog: zmienna KOWR_CACHE_DIR albo backend/cache/ (poza repozytorium, w .gitignore).
Zapis startowy: app/data/seed_cache/ (w repozytorium, tylko do odczytu) – działki przykładowe dostępne od razu
po wdrożeniu (np. Render ma ulotny dysk). Własny cache ma pierwszeństwo przed zapisem startowym.
"""

from __future__ import annotations

import gzip
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from app.models import ParcelContext

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "cache"
SEED_DIR = Path(__file__).resolve().parent / "data" / "seed_cache"


def cache_dir() -> Path:
    d = Path(os.environ.get("KOWR_CACHE_DIR", DEFAULT_DIR))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _name(parcel_id: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]", "_", parcel_id) + ".json.gz"


def _path(parcel_id: str) -> Path:
    return cache_dir() / _name(parcel_id)


def save(ctx: ParcelContext, origin: str) -> dict:
    meta = {"ref": ctx.parcel.id, "saved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "origin": origin}
    data = ctx.model_copy(update={"cache": meta}).model_dump(mode="json")
    tmp = _path(ctx.parcel.id).with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(_path(ctx.parcel.id))
    return meta


def load(parcel_id: str) -> ParcelContext | None:
    p = _path(parcel_id)
    if not p.exists():
        p = SEED_DIR / _name(parcel_id)
    if not p.exists():
        return None
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return ParcelContext(**json.load(f))


def list_all() -> list[dict]:
    out = []
    own = sorted(cache_dir().glob("*.json.gz"))
    seed = [p for p in sorted(SEED_DIR.glob("*.json.gz")) if not (cache_dir() / p.name).exists()]
    for p in own + seed:
        try:
            ctx = load_path(p)
        except Exception:
            continue
        meteo = ctx.meteo.daily if ctx.meteo else []
        out.append({
            "id": ctx.parcel.id, "gmina": ctx.parcel.gmina, "obreb": ctx.parcel.obreb, "number": ctx.parcel.number,
            "area_ha": ctx.parcel.area_ha, "as_of": ctx.as_of, "saved_at": (ctx.cache or {}).get("saved_at"),
            "origin": (ctx.cache or {}).get("origin"),
            "meteo_from": meteo[0].date if meteo else None,
            "sources_ok": sum(1 for x in ctx.provenance if x.mode in ("live", "cache") and x.status in ("ok", "partial")),
            "sources_total": sum(1 for x in ctx.provenance if x.mode in ("live", "cache")),
        })
    return out


def load_path(p: Path) -> ParcelContext:
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return ParcelContext(**json.load(f))
