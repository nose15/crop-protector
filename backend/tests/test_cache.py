"""Cache kontekstów: zapis/odczyt, trafienie bez sieci, odwołanie w /api/recommend, scalanie z zapisem."""

import asyncio
import gzip
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import cache
from app.api import context as ctx_api
from app.main import app
from app.models import ParcelContext, Provenance
from app.sources.base import AdapterResult
from conftest import FIXTURES

PID = "046101_1.0445.7"


@pytest.fixture()
def saved(tmp_path, monkeypatch) -> ParcelContext:
    monkeypatch.setenv("KOWR_CACHE_DIR", str(tmp_path))
    raw = json.load(gzip.open(FIXTURES / f"context_{PID}_full.json.gz", "rt", encoding="utf-8"))
    ctx = ParcelContext(**raw)
    cache.save(ctx, origin="test")
    return ctx


def test_save_load_list(saved):
    back = cache.load(PID)
    assert back.parcel.id == PID and back.cache["origin"] == "test"
    assert len(back.meteo.daily) == len(saved.meteo.daily)
    lst = cache.list_all()
    assert lst[0]["id"] == PID and lst[0]["sources_ok"] >= 4


def test_context_hit_makes_no_requests(saved, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("trafienie w cache nie może odpytywać usług")
    monkeypatch.setattr(ctx_api, "gather", boom)
    c = TestClient(app)
    r = c.post("/api/context", json={"parcel": saved.parcel.model_dump(mode="json"), "as_of": saved.as_of.isoformat()})
    assert r.status_code == 200 and r.json()["cache"]["hit"] is True
    assert c.get(f"/api/parcel?q={PID}").json()["id"] == PID          # numer z cache: bez ULDK
    assert c.get("/api/cache").json()[0]["id"] == PID
    assert c.get(f"/api/cache/{PID}").status_code == 200
    assert c.get("/api/cache/000000_0.0000.1").status_code == 404


def test_recommend_by_reference(saved):
    d = saved.as_of
    r = TestClient(app).post("/api/recommend", json={
        "context_ref": PID, "request": {"crop": "zboza_ozime", "range": {"from": d.isoformat(), "to": (d + timedelta(days=60)).isoformat()}}})
    assert r.status_code == 200, r.text
    assert r.json()["parcel"]["id"] == PID
    bad = TestClient(app).post("/api/recommend", json={"request": {"crop": "zboza_ozime", "range": {"from": d.isoformat(), "to": d.isoformat()}}})
    assert bad.status_code == 422


def test_failed_source_falls_back_to_saved(saved, monkeypatch):
    """Odświeżenie: źródło, które teraz zawiodło, bierze dane z zapisu (mode = cache); bez sieci (podmienione adaptery)."""
    class Failing:
        def __init__(self, name):
            self.name = name

        async def fetch(self, client, parcel, as_of):
            return AdapterResult(data=None, provenance=Provenance(source=self.name, status="timeout", retrieved_at="t",
                                                                   licence="-", note="test"))
    names = {p.source for p in saved.provenance}
    pick = lambda prefix: next(n for n in names if n.startswith(prefix))  # noqa: E731
    fake = {"meteo": Failing(pick("Open-Meteo")), "iung": Failing(pick("IUNG")), "soilgrids": Failing(pick("ISRIC")),
            "terrain": Failing(pick("NMT")), "water": Failing(pick("OpenStreetMap")), "satellite": Failing(pick("Sentinel"))}
    monkeypatch.setattr(ctx_api, "adapters", lambda full: fake)
    out = asyncio.run(ctx_api.gather(None, saved.parcel, saved.as_of, previous=cache.load(PID)))
    assert out.meteo is not None and out.terrain is not None and out.satellite is not None
    modes = {p.source.split(" ")[0]: p.mode for p in out.provenance}
    assert modes["Open-Meteo"] == "cache" and modes["NMT"] == "cache"
    assert out.soil.soilgrids is None                                 # w zapisie też nie było SoilGrids


def test_covers_requires_ten_years_of_weather(saved):
    assert ctx_api.covers(saved, saved.as_of)
    assert not ctx_api.covers(saved, date(saved.as_of.year - 3, 6, 1))   # zapis ma pogodę tylko od 2016


def test_cors_allows_any_origin():
    """Wdrożenie z frontendem na innej domenie (Render): preflight i odpowiedź z nagłówkiem CORS."""
    c = TestClient(app)
    pre = c.options("/api/recommend", headers={"Origin": "https://zatrzymaj-wode.onrender.com",
                                                "Access-Control-Request-Method": "POST",
                                                "Access-Control-Request-Headers": "content-type"})
    assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == "*"
    r = c.get("/api/health", headers={"Origin": "https://example.org"})
    assert r.headers["access-control-allow-origin"] == "*"


def test_seed_cache_available_without_own_cache(tmp_path, monkeypatch):
    """Zapis startowy w repozytorium: działka przykładowa dostępna od razu po wdrożeniu (pusty katalog cache)."""
    monkeypatch.setenv("KOWR_CACHE_DIR", str(tmp_path))
    assert cache.load(PID) is not None
    assert any(x["id"] == PID for x in cache.list_all())
