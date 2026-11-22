"""Zapis w cache bez map (np. NMT GUGiK chwilowo nie odpowiadał) jest uzupełniany przy kolejnym otwarciu działki,
nie częściej niż co RETRY_AFTER; pogoda i reszta zostają z zapisu. Bez sieci (adaptery podmienione)."""

import json
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import cache
from app.api import context as ctx_api
from app.main import app
from app.models import ParcelContext, Provenance
from app.sources.base import AdapterResult
from conftest import FIXTURES
from synthetic_meteo import generate

PID = "046101_1.0445.7"
TERRAIN = {"layers": {"flow": "data:image/png;base64,AA==", "depressions": "x", "slope": "x"},
           "bounds": [[53.1, 18.1], [53.11, 18.14]], "markers": [], "stats": {}}


class FakeAdapter:
    timeout_s = 5.0
    def __init__(self, key, calls):
        self.key, self.calls = key, calls

    async def fetch(self, client, parcel, as_of):
        self.calls.append(self.key)
        ok = self.key == "terrain"
        prov = Provenance(source="NMT GUGiK (test)" if ok else f"{self.key} (test)", status="ok" if ok else "timeout",
                          retrieved_at=datetime.now(timezone.utc).isoformat(), licence="test")
        return AdapterResult(data=TERRAIN if ok else None, provenance=prov)


def saved_context(minutes_ago: int) -> ParcelContext:
    raw = json.loads((FIXTURES / f"context_{PID}_partial.json").read_text())
    raw["terrain"] = None
    raw["meteo"] = {"daily": generate(date(2015, 3, 1), date.today()), "forecast": [], "resolution": "SYNTETYCZNE"}
    raw["as_of"] = date.today().isoformat()
    ctx = ParcelContext(**raw)
    cache.save(ctx, origin="na_zywo")
    old = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).replace(microsecond=0).isoformat()
    return ctx.model_copy(update={"cache": {"ref": PID, "saved_at": old, "origin": "na_zywo"}})


def test_missing_terrain_is_refilled_once_due(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(ctx_api, "adapters", lambda full: {k: FakeAdapter(k, calls) for k in ctx_api.RETRY_KEYS})
    saved = saved_context(minutes_ago=40)
    monkeypatch.setattr(cache, "load", lambda pid: saved)
    body = {"parcel": saved.parcel.model_dump(mode="json"), "as_of": date.today().isoformat()}
    with TestClient(app) as client:
        r = client.post("/api/context", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["terrain"]["layers"]["flow"].startswith("data:image/png")
    assert "terrain" in out["cache"]["refilled"] and "meteo" not in calls      # pogoda z zapisu
    assert any(p["source"] == "NMT GUGiK (test)" for p in out["provenance"])


def test_fresh_save_is_not_retried(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(ctx_api, "adapters", lambda full: {k: FakeAdapter(k, calls) for k in ctx_api.RETRY_KEYS})
    saved = saved_context(minutes_ago=5)
    monkeypatch.setattr(cache, "load", lambda pid: saved)
    body = {"parcel": saved.parcel.model_dump(mode="json"), "as_of": date.today().isoformat()}
    with TestClient(app) as client:
        out = client.post("/api/context", json=body).json()
    assert out["terrain"] is None and calls == [] and out["cache"]["hit"] is True
