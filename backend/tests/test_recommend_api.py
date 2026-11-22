"""/api/recommend: walidacja, 409 bez pogody, kolejność grup, niezmienniki wyniku."""

import gzip
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.engine.terrain_rules import RULES
from app.engine.weather import shift_year
from app.main import app
from app.terrain import analysis as A
from conftest import FIXTURES
from synthetic_meteo import generate

PID = "046101_1.0445.7"


@pytest.fixture(scope="module")
def context() -> dict:
    raw = json.loads((FIXTURES / f"context_{PID}_partial.json").read_text())
    g = A.parse_aaigrid(gzip.open(FIXTURES / f"nmt_{PID}.asc.gz").read().decode())
    raw["terrain"] = A.compute(g, raw["parcel"]["rings"][0], 50)
    # SYNTETYCZNA pogoda (tests/synthetic_meteo.py) od 2015 r., żeby objąć 10 lat przed D = 2025-06-01
    raw["meteo"] = {"daily": generate(date(2015, 3, 1), date.today()), "forecast": [], "resolution": "SYNTETYCZNE"}
    raw["as_of"] = date.today().isoformat()
    return raw


def body(ctx, frm=None, to=None, **answers):
    frm = frm or date.today()
    to = to or frm + timedelta(days=30)
    return {"context": ctx, "request": {"crop": "zboza_ozime", "range": {"from": frm.isoformat(), "to": to.isoformat()},
                                        "answers": answers}}


client = TestClient(app)


def test_ok_and_invariants(context):
    r = client.post("/api/recommend", json=body(context))
    assert r.status_code == 200, r.text
    res = r.json()
    groups = [x["group"] for x in res["recommendations"]]
    order = {"retencja": 0, "agrotechnika": 1, "nawadnianie": 2}
    assert groups == sorted(groups, key=order.get)                  # retencja → agrotechnika → nawadnianie
    assert len(res["recommendations"]) <= 5                                # rada poza zakresem nie zajmuje karty
    assert all(x["evidence"] for x in res["recommendations"])
    assert all(x["confidence_reason"] for x in res["recommendations"])      # każda pewność ma wyjaśnienie
    assert all(x["title"] for x in res["recommendations"])                  # każda rada ma krótki tytuł
    assert {c["code"] for c in res["causes"]} == {"C1", "C2", "C3", "C4"}
    assert 1 <= len(res["uncertainty"]["reasons"]) <= 4
    assert any(n["rule"] == "R14" for n in res["not_evaluated"])


def test_site_answer_roundtrip(context):
    res = client.post("/api/recommend", json=body(
        context, date(2026, 2, 1), date(2026, 4, 30), sites={"ditch0": True})).json()
    r11 = next(x for x in res["recommendations"] if x["rule"] == "R11")
    assert r11["conditional"] is False and r11["confidence"] == "wysoka"
    assert r11["when_short"] == RULES["R11"]["when_short"]


def test_may_range_hides_weir(context):
    """Maj–maj jednego roku nie zawiera lutego–marca."""
    res = client.post("/api/recommend", json=body(context, date(2026, 5, 1), date(2026, 5, 31))).json()
    banned = RULES["R11"]["when_short"]
    assert "R11" not in [x["rule"] for x in res["recommendations"]]
    assert all(banned not in (x.get("when_short") or "") and banned not in (x.get("when_text") or "")
               for x in res["recommendations"])
    assert all(n["rule"] != "R11" for n in res["not_evaluated"])
    groups = [x["group"] for x in res["recommendations"]]
    order = {"retencja": 0, "agrotechnika": 1, "nawadnianie": 2}
    assert groups == sorted(groups, key=order.get)
    sw = res["state"]["soil_water"]
    if sw:
        for key in ("taw_mm", "dr_mm", "pct_of_taw", "below_raw", "safe_level_pct"):
            assert key in sw


def test_february_april_keeps_weir_chip(context):
    res = client.post("/api/recommend", json=body(context, date(2026, 2, 1), date(2026, 4, 30))).json()
    assert res["recommendations"][0]["rule"] == "R11"
    assert res["recommendations"][0]["when_short"] == RULES["R11"]["when_short"]


def test_two_year_may_range_keeps_weir_chip(context):
    """Koniec równy shift_year(from, 2) jest legalny i obejmuje luty–marzec lat pomiędzy."""
    r = client.post("/api/recommend", json=body(context, date(2026, 5, 1), date(2028, 5, 1)))
    assert r.status_code == 200, r.text
    r11 = next(x for x in r.json()["recommendations"] if x["rule"] == "R11")
    assert r11["when_short"] == RULES["R11"]["when_short"]


def test_november_analysis(context):
    """D w listopadzie: KBW poza okresem, prognoza poza sezonem dla zbóż jarych, podatność z 10 lat policzona."""
    b = body(context)
    b["request"]["crop"] = "zboza_jare"
    res = client.post("/api/recommend", json=b).json()
    if date.today().month in (11, 12, 1, 2):
        assert res["state"]["kbw"]["status"] == "poza_okresem"
        assert res["forecast"]["status"] == "poza_sezonem_uprawy"
        assert "poza sezonem wzrostu" in res["state"]["headline"]
        assert "scenariusz" not in res["state"]["headline"] and " z 10" not in res["state"]["headline"]
        assert "poza sezonem monitoringu" in res["state"]["headline_technical"]
    assert res["susceptibility"]["of"] == 10
    assert {c["code"]: c["confidence"] for c in res["causes"]}["C4"] == "niska"


def test_in_season_forecast_and_irrigation_last(context):
    frm = date(2025, 6, 1)
    res = client.post("/api/recommend", json=body(context, frm, frm + timedelta(days=60))).json()
    f = res["forecast"]
    assert f["status"] == "ok" and f["stress_chance"]["of"] == 10 and 0 <= f["stress_chance"]["n"] <= 10
    assert f["deficit_mm"]["low"] <= f["deficit_mm"]["median"] <= f["deficit_mm"]["high"]
    assert res["state"]["soil_water"]["taw_mm"]["low"] < res["state"]["soil_water"]["taw_mm"]["high"]
    groups = [r["group"] for r in res["recommendations"]]
    if "nawadnianie" in groups:
        assert groups[-1] == "nawadnianie"                          # G2: nawadnianie zawsze ostatnie
        irr = res["recommendations"][-1]
        assert irr["conditional"] and "zgody wodnoprawnej" in irr["consult_note"]
    no_water = client.post("/api/recommend", json=body(context, frm, frm + timedelta(days=60),
                                                       irrigation_water=False)).json()
    assert "nawadnianie" not in [r["group"] for r in no_water["recommendations"]]


def test_meteo_range_409(context):
    ctx = dict(context, meteo={"daily": generate(date(2020, 3, 1), date.today()), "forecast": [], "resolution": "S"})
    r = client.post("/api/recommend", json=body(ctx, date(2025, 6, 1)))
    assert r.status_code == 409 and r.json()["detail"]["error"] == "meteo_range"


def test_meteo_missing_409(context):
    ctx = dict(context, meteo=None)
    r = client.post("/api/recommend", json=body(ctx))
    assert r.status_code == 409 and r.json()["detail"]["error"] == "meteo_missing"


@pytest.mark.parametrize("frm,to", [
    (date.today() + timedelta(days=1), None),                       # przyszłość
    (date.today() - timedelta(days=366 * 11), None),                # > 10 lat wstecz
    (date.today(), shift_year(date.today(), 2) + timedelta(days=1)),  # dzień po dwóch latach
    (date(2024, 2, 29), date(2026, 3, 1)),                          # 29 II + 2 lata = 28 II
    (date.today(), date.today() - timedelta(days=1)),               # koniec przed początkiem
])
def test_invalid_range_422(context, frm, to):
    r = client.post("/api/recommend", json=body(context, frm, to))
    assert r.status_code == 422 and r.json()["detail"]["error"] == "invalid_request"


def test_range_longer_than_half_year(context):
    """Zakres ponad pół roku, koniec w roku D+2: wynik obejmuje całe żądanie."""
    frm, to = date(2025, 6, 1), date(2027, 5, 22)
    b = body(context, frm, to)
    b["request"]["crop"] = "zboza_jare"
    r = client.post("/api/recommend", json=b)
    assert r.status_code == 200, r.text
    res = r.json()
    f = res["forecast"]
    assert f["status"] == "ok"
    assert f["range"] == {"from": frm.isoformat(), "to": to.isoformat()}
    assert f["stress_chance"]["of"] == 10
    short = body(context, frm, frm + timedelta(days=184))
    short["request"]["crop"] = "zboza_jare"
    short_res = client.post("/api/recommend", json=short).json()
    assert f["in_season_days"] > short_res["forecast"]["in_season_days"]
    assert "6 miesięcy" not in res["state"]["headline"]
    assert "6 miesięcy" not in res["state"]["headline_technical"]


def test_out_of_season_headline_without_six_months(context):
    """Zboża jare w listopadzie–grudniu: komunikat sezonu bez limitu pół roku."""
    b = body(context, date(2025, 11, 1), date(2025, 12, 15))
    b["request"]["crop"] = "zboza_jare"
    r = client.post("/api/recommend", json=b)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["forecast"]["status"] == "poza_sezonem_uprawy"
    tech = res["state"]["headline_technical"]
    assert "Wydłuż zakres dat do wiosny, żeby zobaczyć ryzyko na początku sezonu." in tech
    assert "6 miesięcy" not in tech
    assert ("Wybrany okres wypada poza sezonem wzrostu tej uprawy. Wydłuż zakres dat do wiosny, "
            "żeby zobaczyć, czy na początku sezonu zabraknie wody.") in res["state"]["headline"]


def test_unknown_crop_422(context):
    b = body(context)
    b["request"]["crop"] = "banan"
    assert client.post("/api/recommend", json=b).status_code == 422
