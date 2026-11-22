"""Porównanie satelitarne (anomalia względem lat bazowych) i nowa formuła pewności całości. Bez sieci."""

import gzip
import json
from datetime import date, timedelta

import pytest

from app.engine import s2_anomaly
from app.engine.assemble import build
from app.models import ParcelContext, RecommendRequest
from app.terrain import analysis as A
from conftest import FIXTURES
from synthetic_meteo import generate

PID = "046101_1.0445.7"
D = date(2025, 7, 15)


def baseline(cur_ndvi: float, years=range(2018, 2025), ndmi_shift: float = -0.4) -> list[dict]:
    """Sezony: co 5 dni od kwietnia do września; lata bazowe ok. 0,7 NDVI, bieżący rok z `cur_ndvi` w lipcu."""
    obs = []
    for y in list(years) + [D.year]:
        d = date(y, 4, 1)
        while d <= date(y, 9, 30):
            base = 0.7 + 0.01 * ((y * 7) % 5 - 2)
            v = cur_ndvi if (y == D.year and d.month == 7) else base
            obs.append({"date": d.isoformat(), "ndvi": v, "ndmi": v + ndmi_shift, "valid_frac": 1.0})
            d += timedelta(days=5)
    return obs


def test_anomaly_deficit_and_normal():
    low = s2_anomaly.analyse(baseline(0.58), D)
    assert low["signal"] == "niedobor" and low["z"] <= -1 and low["base_years"] == 7
    ok = s2_anomaly.analyse(baseline(0.70), D)
    assert ok["signal"] == "norma"


def test_anomaly_needs_season_and_base():
    assert s2_anomaly.analyse(baseline(0.58), date(2025, 11, 20))["signal"] is None
    short = s2_anomaly.analyse(baseline(0.58, years=range(2023, 2025)), D)
    assert short["signal"] is None and "za krótka" in short["reason"]


def test_anomaly_ignores_future_observations():
    obs = baseline(0.70) + [{"date": "2025-07-25", "ndvi": 0.1, "ndmi": -0.3, "valid_frac": 1.0}]
    assert s2_anomaly.analyse(obs, date(2025, 7, 20))["signal"] == "norma"


def test_anomaly_mixed_base_is_not_drought():
    res = s2_anomaly.analyse(baseline(0.05), D)
    assert res["signal"] is None and "baza_mieszana" in res["flags"]


def test_agreement():
    assert s2_anomaly.agreement({"signal": "niedobor"}, True) == "potwierdza"
    assert s2_anomaly.agreement({"signal": "norma"}, True) == "przeczy"
    assert s2_anomaly.agreement({"signal": None}, True) == "nie_rozstrzyga"
    assert s2_anomaly.agreement({"signal": "norma"}, None) == "nie_rozstrzyga"


@pytest.fixture(scope="module")
def ctx() -> ParcelContext:
    raw = json.loads((FIXTURES / f"context_{PID}_partial.json").read_text())
    g = A.parse_aaigrid(gzip.open(FIXTURES / f"nmt_{PID}.asc.gz").read().decode())
    raw["terrain"] = A.compute(g, raw["parcel"]["rings"][0], 50)
    raw["meteo"] = {"daily": generate(date(2015, 3, 1), date(2025, 11, 1)), "forecast": [], "resolution": "SYNTETYCZNE"}
    raw["as_of"] = "2025-11-01"
    return ParcelContext(**raw)


def req(**answers) -> RecommendRequest:
    return RecommendRequest(crop="kukurydza_ziarno", range={"from": D.isoformat(), "to": "2025-08-31"}, answers=answers)


def test_confidence_is_minimum_of_inputs_causes_and_top_actions(ctx):
    res = build(ctx, req())
    levels = ["nie_oceniono", "niska", "srednia", "wysoka"]
    parts = [c.confidence for c in res.causes if c.dominant and c.confidence != "nie_oceniono"]
    parts += [r.confidence for r in res.recommendations[:3]]
    assert levels.index(res.uncertainty["overall"]) <= min([levels.index("srednia")] + [levels.index(p) for p in parts])
    assert res.satellite_check["state"] == "brak" and res.satellite_check["agreement"] == "nie_rozstrzyga"
    assert 1 <= len(res.uncertainty["reasons"]) <= 4


def test_failed_unrelated_sources_do_not_drop_confidence(ctx):
    """Dawniej ≥ 2 awarie dowolnych źródeł dawały „niską”; teraz awaria obniża tylko to, co z niej liczone."""
    broken = ctx.model_copy(update={"provenance": [p.model_copy(update={"status": "timeout"})
                                                   if p.source.startswith(("OpenStreetMap", "ISRIC")) else p
                                                   for p in ctx.provenance]})
    assert build(broken, req()).uncertainty["overall"] == build(ctx, req()).uncertainty["overall"]


def test_satellite_contradiction_lowers_and_agreement_with_answers_raises(ctx, monkeypatch):
    base = {"obs": baseline(0.58), "retrieved_at": "2025-11-01T00:00:00+00:00", "source": "test"}
    plain = build(ctx, req(drained=False))
    deficit = (plain.state.get("soil_water") or {}).get("below_raw")
    sat_res = build(ctx, req(drained=False), s2base=base, s2state={"state": "gotowe"})
    chk = sat_res.satellite_check
    assert chk["signal"] == "niedobor"
    levels = ["nie_oceniono", "niska", "srednia", "wysoka"]
    if deficit:
        assert chk["agreement"] == "potwierdza"
        assert levels.index(sat_res.uncertainty["overall"]) >= levels.index(plain.uncertainty["overall"])
    else:
        assert chk["agreement"] == "przeczy"
        assert levels.index(sat_res.uncertainty["overall"]) <= levels.index(plain.uncertainty["overall"])
        assert any("nie zgadzają się" in r for r in sat_res.uncertainty["reasons"])


def test_high_confidence_only_with_satellite_and_farmer_answer(ctx, monkeypatch):
    """„Wysoka” tylko gdy wszystkie składniki są co najmniej „średnie”, satelita potwierdza bilans (baza ≥ 5 lat)
    i rolnik odpowiedział o drenach albo rowie z zastawką."""
    import app.engine.assemble as asm
    monkeypatch.setattr(asm.s2_anomaly, "agreement", lambda sat, deficit: "potwierdza")
    base = {"obs": baseline(0.58), "retrieved_at": "x", "source": "test"}
    res_no = build(ctx, req(), s2base=base, s2state={"state": "gotowe"})
    res_yes = build(ctx, req(drained=True), s2base=base, s2state={"state": "gotowe"})
    assert res_no.uncertainty["overall"] != "wysoka"
    if res_no.uncertainty["overall"] == "srednia":
        assert res_yes.uncertainty["overall"] == "wysoka"
