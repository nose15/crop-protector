"""/api/report.pdf: PDF z gotowego wyniku /api/recommend (bez sieci, pogoda syntetyczna jak w test_recommend_api)."""

import gzip
import json
import zlib
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import AnalysisResult
from app.report_pdf import interval, next_days, num, render, top_actions, verdict_level
from app.terrain import analysis as A
from conftest import FIXTURES
from synthetic_meteo import generate

PID = "046101_1.0445.7"
client = TestClient(app)


@pytest.fixture(scope="module")
def result() -> dict:
    raw = json.loads((FIXTURES / f"context_{PID}_partial.json").read_text())
    g = A.parse_aaigrid(gzip.open(FIXTURES / f"nmt_{PID}.asc.gz").read().decode())
    raw["terrain"] = A.compute(g, raw["parcel"]["rings"][0], 50)
    raw["meteo"] = {"daily": generate(date(2015, 3, 1), date.today()), "forecast": [], "resolution": "SYNTETYCZNE"}
    raw["as_of"] = date.today().isoformat()
    frm = date.today() - timedelta(days=200)
    req = {"crop": "kukurydza_ziarno", "range": {"from": frm.isoformat(), "to": (frm + timedelta(days=60)).isoformat()},
           "answers": {"irrigation_water": True}}
    r = client.post("/api/recommend", json={"context": raw, "request": req})
    assert r.status_code == 200, r.text
    return r.json()


def _text(pdf: bytes) -> bytes:
    """Rozpakowane strumienie treści (żeby sprawdzić, że PDF niesie dane, a nie pustą stronę)."""
    out, i = b"", 0
    while (i := pdf.find(b"stream\n", i)) != -1:
        j = pdf.find(b"endstream", i)
        try:
            out += zlib.decompressobj().decompress(pdf[i + 7:j])   # nadmiar po strumieniu ignorowany
        except zlib.error:
            pass
        i = j
    return out


def test_pdf_download(result):
    r = client.post("/api/report.pdf", json={"result": result, "parcel": {"gmina": "Bydgoszcz (miasto)", "obreb": "0445"}})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == f'attachment; filename="raport-{PID}-{result["request"]["range"]["from"]}.pdf"'
    pdf = r.content
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    assert b"/Lang (pl)" in pdf                      # język dokumentu dla czytników ekranu
    assert b"AtkinsonHyperlegible" in pdf          # osadzona czcionka (polskie znaki)
    assert len(_text(pdf)) > 2000


def test_pdf_without_parcel_and_recommendations(result):
    bare = dict(result, recommendations=[], causes=[], not_evaluated=[], forecast=None, susceptibility=None)
    r = client.post("/api/report.pdf", json={"result": bare})
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF-")


def test_pdf_rejects_invalid_result():
    r = client.post("/api/report.pdf", json={"result": {"parcel": {"id": PID}}})
    assert r.status_code == 422


def test_summary_logic_mirrors_frontend(result):
    """Werdykt, „najbliższe dni” i pierwsze działania jak verdict / nextDays / topActions w present.js."""
    res = AnalysisResult.model_validate(result)
    assert verdict_level(res) in {"alarm", "uwaga", "ok", "info"}
    off = res.model_copy(update={"forecast": {"status": "poza_sezonem_uprawy"},
                                 "state": {**res.state, "kbw": {"status": "poza_okresem"},
                                           "soil_water": {**(res.state.get("soil_water") or {}), "below_raw": False}}})
    assert verdict_level(off) == "info"
    assert next_days(off) == "Wybrany okres jest poza sezonem wzrostu tej uprawy."
    recs = res.recommendations
    top = top_actions(recs)
    assert top[:3] == recs[:3]
    irr = [r for r in recs if r.group == "nawadnianie"]
    assert len(top) == min(3, len(recs)) + (1 if irr and irr[0] not in recs[:3] else 0)


def test_pdf_with_charts_and_no_series(result):
    """Wykresy: bez przebiegu wody, bez lat i bez sezonu KBW raport nadal powstaje."""
    res = AnalysisResult.model_validate(result)
    st = {**res.state, "soil_water": {}, "kbw": {"status": "brak_danych"}}
    pdf = render(res.model_copy(update={"state": st, "susceptibility": {}}))
    assert pdf.startswith(b"%PDF-")


def test_number_format_matches_frontend():
    assert num(-117.84, 1) == "−117,8"
    assert num(1153) == "1153"                     # pl-PL grupuje dopiero od 10 000
    assert num(12500) == "12 500"
    assert interval({"median": 43.4, "low": 6.8, "high": 79.6}, 0, "mm") == "43 mm (od 7 do 80)"
    assert interval({"median": 15, "low": 15, "high": 15}, 0, "dni") == "15 dni"
    assert interval(None) == "—"
