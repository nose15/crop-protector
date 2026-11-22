"""Teren: algorytmy na sztucznym terenie o znanym wyniku + regresja na NMT działki testowej."""

import gzip
import json

import numpy as np
import pytest

from app.terrain import analysis as A
from conftest import FIXTURES

CELL = 2.0
AREA = CELL * CELL


def test_plane_accumulation():
    z = np.tile(np.linspace(10, 5, 50)[:, None], (1, 40))     # spadek na południe
    f = A.priority_flood(z)
    acc = A.accumulate(f, A.d8_receivers(f, CELL), AREA)
    assert np.allclose(f, z)                                    # nic się nie wypełnia
    assert np.all(np.round(acc[-1] / AREA) == 50)               # dolny wiersz zbiera całą kolumnę


def test_bowl_volume_without_epsilon():
    y, x = np.mgrid[0:50, 0:40]
    r2 = ((x - 20) * CELL) ** 2 + ((y - 25) * CELL) ** 2
    dip = 0.5 * np.clip(1 - r2 / 20**2, 0, None)
    bowl = 10 - dip
    depth = A.priority_flood(bowl, eps=0.0) - bowl
    assert depth.sum() * AREA == pytest.approx(dip.sum() * AREA, rel=1e-6)
    assert depth.max() == pytest.approx(0.5, abs=1e-6)


def _field_with(feature: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    z = np.tile(np.linspace(31, 30, 100)[:, None], (1, 100)) - feature
    mask = np.zeros(z.shape, bool)
    mask[20:80, 20:80] = True                                   # działka 120 × 120 m
    return z, mask


def _classify_one(z, mask):
    f = A.priority_flood(z)
    rec = A.d8_receivers(f, CELL)
    depth = A.priority_flood(z, eps=0.0) - z
    deps = A.find_depressions(depth, rec, mask, CELL)
    assert len(deps) == 1, deps
    return deps[0]


def test_ditch_is_not_a_pond():
    feat = np.zeros((100, 100))
    feat[30:80, 50] = 0.8                                       # rów 2 m × 100 m, głęboki na 0,8 m
    d = _classify_one(*_field_with(feat))
    assert d["kind"] == "ditch" and d["width_m"] <= 3


def test_compact_deep_basin_is_pond():
    y, x = np.mgrid[0:100, 0:100]
    r2 = ((x - 50) * CELL) ** 2 + ((y - 50) * CELL) ** 2
    d = _classify_one(*_field_with(0.6 * np.clip(1 - r2 / 15**2, 0, None)))   # niecka r = 15 m, 0,6 m
    assert d["kind"] == "pond" and d["inside_parcel_pct"] == 100


def test_shallow_basin_is_wet_spot():
    y, x = np.mgrid[0:100, 0:100]
    r2 = ((x - 50) * CELL) ** 2 + ((y - 50) * CELL) ** 2
    d = _classify_one(*_field_with(0.2 * np.clip(1 - r2 / 15**2, 0, None)))   # 0,2 m: za płytko na oczko
    assert d["kind"] == "wet_spot"


def test_parcel_fixture_regression():
    """NMT działki testowej (pobrany 21.11.2026). Dwa głębokie obniżenia przy drodze to rowy,
    co potwierdza ortofotomapa; wcześniej (bez klasyfikacji kształtu) były pokazywane jako miejsca na oczko."""
    ring = json.loads((FIXTURES / "context_046101_1.0445.7_partial.json").read_text())["parcel"]["rings"][0]
    g = A.parse_aaigrid(gzip.open(FIXTURES / "nmt_046101_1.0445.7.asc.gz").read().decode())
    r = A.compute(g, ring, 50)
    s = r["stats"]
    assert s["n_ditches"] >= 2 and s["ditch_near_parcel"]
    assert s["n_ponds"] == 0                                     # żadnego rowu jako oczka
    assert all(m["kind"] != "pond" for m in r["markers"])
    assert len(r["outlets"]) == 3 and r["outlets"][0]["catchment_ha"] == pytest.approx(2.1, abs=0.05)
    assert s["inflow_is_lower_bound"] is True
    json.dumps(r)                                                # wynik musi dać się zserializować
