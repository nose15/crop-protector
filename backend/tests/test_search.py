"""Wyszukiwanie działki: numer, obręb + numer, adres (UUG GUGiK → punkt → ULDK). Bez sieci (usługi podmienione)."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.api import parcel as parcel_api
from app.main import app
from app.models import Parcel
from app.sources import geocode, uldk
from conftest import FIXTURES

P = Parcel(id="301104_2.0012.34", teryt7="3011042", gmina="Krzywiń", obreb="0012", number="34",
           rings=[[[16.81, 51.96], [16.82, 51.96], [16.82, 51.97], [16.81, 51.96]]], centroid=[16.815, 51.965], area_ha=1.2)


def test_parse_uug_fixture():
    hits = geocode.parse((FIXTURES / "uug_krzywin_rynek_1.json").read_bytes())
    assert hits[0]["label"] == "Krzywiń, Rynek 1"
    assert hits[0]["lat"] == pytest.approx(51.9617, abs=1e-3) and hits[0]["lon"] == pytest.approx(16.8194, abs=1e-3)


def test_variants_add_comma_after_city():
    assert geocode.variants("Toruń Szeroka 1") == ["Toruń Szeroka 1", "Toruń, Szeroka 1"]
    assert geocode.variants("Toruń, Szeroka 1") == ["Toruń, Szeroka 1"]


@pytest.fixture()
def fake(monkeypatch):
    calls = []

    async def fake_geocode(client, q):
        calls.append(("adres", q))
        return [{"label": "Krzywiń, Rynek 1", "lat": 51.9617, "lon": 16.8194}] if "Rynek" in q else []

    async def fake_lookup(client, q=None, lat=None, lon=None):
        calls.append(("uldk", q, lat, lon))
        if q and q.startswith("Krzywiń 134"):
            return P
        if lat is not None:
            return P
        raise uldk.ParcelNotFound("brak")

    monkeypatch.setattr(geocode, "geocode", fake_geocode)
    monkeypatch.setattr(uldk, "lookup", fake_lookup)
    return calls


def test_address_search(fake):
    with TestClient(app) as c:
        r = c.get("/api/parcel", params={"q": "Krzywiń, Rynek 1"})
    assert r.status_code == 200
    body = r.json()
    assert body["found_by"] == "adres" and body["address"] == "Krzywiń, Rynek 1"
    assert fake[0][0] == "adres"                                       # przecinek → najpierw adres


def test_precinct_and_number_search(fake):
    with TestClient(app) as c:
        r = c.get("/api/parcel", params={"q": "Krzywiń 134/2"})
    assert r.status_code == 200 and r.json()["found_by"] == "obreb_numer"
    assert fake[0][0] == "uldk"                                        # bez przecinka → najpierw obręb + numer


def test_not_found_message_lists_formats(fake):
    with TestClient(app) as c:
        r = c.get("/api/parcel", params={"q": "Nieistniejące 999"})
    assert r.status_code == 404
    msg = r.json()["detail"]["message"]
    assert "046101_1.0445.7" in msg and "Rynek 1" in msg


def test_fuzzy_street_match_is_rejected():
    """UUG zwraca „Szewska 1” dla „Szeroka 1” (dokładność 0,6): takie dopasowanie odrzucamy."""
    body = b'{"results":{"1":{"city":"Toru\\u0144","street":"Szewska","number":"1","x":"18.6","y":"53.0","accuracy":"0.6"}}}'
    assert geocode.parse(body) == []
