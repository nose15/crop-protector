"""Testy adapterów na zapisanych odpowiedziach (bez sieci)."""

import asyncio

import httpx
import pytest
import yaml

from app.geo import ring_area_m2, to_2180
from app.sources import iung, uldk
from app.sources.base import SourceError, fetch_bytes, guarded
from conftest import FIXTURES

PID = "046101_1.0445.7"


def test_to_2180_matches_uldk():
    # pierwszy wierzchołek działki testowej: ULDK srid=4326 vs srid=2180 (pobrane 21.11.2026)
    x, y = to_2180(18.1349827330418, 53.1050815239618)
    assert abs(x - 442107.40) < 0.05 and abs(y - 582543.70) < 0.05


def test_uldk_parse_fixture():
    lines = (FIXTURES / f"uldk_{PID}.txt").read_text().strip().splitlines()
    assert lines[0] == "0"
    row = lines[1].split("|")
    p = uldk.parcel_from_row(row + [""] * (len(uldk.FIELDS) - len(row)))
    assert p.id == PID and p.teryt7 == "0461011"
    assert 2.5 < p.area_ha < 2.8
    lon, lat = p.centroid
    assert 18.13 < lon < 18.14 and 53.10 < lat < 53.11


def test_iung_text_grid_and_shares():
    # fixture pobrana z poprawną kolejnością osi (x = northing, y = easting), bufor 10 m wokół działki
    text = (FIXTURES / f"iung_{PID}.txt").read_text()
    grid, (minx, miny, maxx, maxy) = iung.parse_text_grid(text)
    assert grid.shape == (round((maxy - miny) / 5), round((maxx - minx) / 5))   # wiersze = northing
    lines = (FIXTURES / f"uldk_{PID}.txt").read_text().strip().splitlines()
    ring = uldk.parse_wkt(lines[1].split("|")[0])[0]
    xy = [to_2180(*p) for p in ring]
    assert minx <= min(p[0] for p in xy) and max(p[0] for p in xy) <= maxx     # działka w całości w siatce
    assert miny <= min(p[1] for p in xy) and max(p[1] for p in xy) <= maxy
    res = iung.shares_on_parcel(grid, (minx, miny, maxx, maxy), xy)
    # wynik zweryfikowany z obrazem WMS IUNG (21.11.2026): dolina Wisły, gleby ciężkie
    assert res.dominant == "IV"
    assert res.shares["IV"] == pytest.approx(0.827, abs=0.01) and res.shares["III"] == pytest.approx(0.173, abs=0.01)
    assert res.n_cells == pytest.approx(ring_area_m2(ring) / 25, rel=0.03)


def test_iung_rejects_swapped_axes():
    # siatka 2×4 przy zasięgu 20 m (E) × 10 m (N) jest spójna; transponowana 4×2 – nie
    head = "Grid bounds: GeneralBounds[(0.0, 0.0), (20.0, 10.0)]\nBand 0:\n"
    iung.parse_text_grid(head + "1 1 1 1\n2 2 2 2\n")
    with pytest.raises(ValueError):
        iung.parse_text_grid(head + "1 1\n1 1\n2 2\n2 2\n")


def test_kbw_thresholds_yaml():
    d = yaml.safe_load(open("app/data/kbw_thresholds.yaml", encoding="utf-8"))
    assert len(d["periods"]) == 14 and d["periods"][0]["start"] == "03-21" and d["periods"][-1]["end"] == "09-30"
    for code in ["zboza_ozime", "zboza_jare", "kukurydza_ziarno", "kukurydza_kiszonka", "rzepak", "ziemniak", "burak_cukrowy"]:
        for cat in ["I", "II", "III", "IV"]:
            vals = d["crops"][code][cat]
            assert len(vals) == 14 and all(v in ("x", "-") or isinstance(v, int) for v in vals)
    assert d["crops"]["zboza_ozime"]["I"][:3] == [-129, -132, -137]     # wiersz z załącznika
    assert d["crops"]["burak_cukrowy"]["I"] == ["-"] * 14                # niewskazana na kat. I


def _mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_fetch_bytes_rejects_redirect_and_huge_body():
    async def run():
        async with _mock_client(lambda r: httpx.Response(302, headers={"location": "https://x/resp"})) as c:
            with pytest.raises(SourceError):
                await fetch_bytes(c, "GET", "https://uldk.test/", follow_redirects=False)
        async with _mock_client(lambda r: httpx.Response(200, content=b"\0" * 3000)) as c:
            with pytest.raises(SourceError):
                await fetch_bytes(c, "GET", "https://uldk.test/", max_bytes=1000)
    asyncio.run(run())


def test_guarded_never_raises():
    async def boom():
        raise RuntimeError("x")

    async def slow():
        await asyncio.sleep(1)

    r1 = asyncio.run(guarded("A", "l", 1, boom))
    r2 = asyncio.run(guarded("B", "l", 0.05, slow))
    assert r1.data is None and r1.provenance.status == "error"
    assert r2.data is None and r2.provenance.status == "timeout"
