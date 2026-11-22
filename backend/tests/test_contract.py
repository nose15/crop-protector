"""Wspólny kontrakt: pliki są aktualne, a prawdziwy JSON mieści się w kształtach z contract_views."""

import gzip
import json
from datetime import date, timedelta

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.contract_export import OPENAPI_PATH, SHAPES_PATH, contract_document, render_shapes
from app.contract_views import (
    AnalysisState, CacheMeta, Effect, ForecastView, MapPoint, ParcelBrief, Satellite,
    SiteQuestion, Susceptibility, Terrain, Uncertainty,
)
from app.main import app
from app.terrain import analysis as A
from conftest import FIXTURES
from synthetic_meteo import generate

PID = "046101_1.0445.7"


def _show(exc: ValidationError) -> str:
    return "\n".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in exc.errors())


def test_shared_files_match_the_app():
    doc = contract_document()
    assert json.loads(OPENAPI_PATH.read_text(encoding="utf-8")) == doc
    assert SHAPES_PATH.read_text(encoding="utf-8") == render_shapes(doc)


def test_live_payloads_match_the_contract():
    raw = json.loads((FIXTURES / f"context_{PID}_partial.json").read_text())
    grid = A.parse_aaigrid(gzip.open(FIXTURES / f"nmt_{PID}.asc.gz").read().decode())
    terrain = A.compute(grid, raw["parcel"]["rings"][0], 50)
    try:
        Terrain.model_validate(terrain)
    except ValidationError as exc:
        raise AssertionError(_show(exc)) from exc

    raw["terrain"] = terrain
    full = json.loads(gzip.open(FIXTURES / f"context_{PID}_full.json.gz", "rt", encoding="utf-8").read())
    if full.get("satellite"):
        try:
            Satellite.model_validate(full["satellite"])
        except ValidationError as exc:
            raise AssertionError(_show(exc)) from exc

    raw["meteo"] = {"daily": generate(date(2015, 3, 1), date.today()), "forecast": [], "resolution": "SYNTETYCZNE"}
    raw["as_of"] = date.today().isoformat()
    today = date.today()
    response = TestClient(app).post("/api/recommend", json={
        "context": raw,
        "request": {"crop": "zboza_ozime", "range": {"from": today.isoformat(), "to": (today + timedelta(days=30)).isoformat()}},
    })
    assert response.status_code == 200, response.text
    body = response.json()
    checks = [
        (AnalysisState, body["state"]),
        (ParcelBrief, body["parcel"]),
        (Uncertainty, body["uncertainty"]),
    ]
    if body["forecast"] is not None:
        checks.append((ForecastView, body["forecast"]))
    if body["susceptibility"] is not None:
        checks.append((Susceptibility, body["susceptibility"]))
    for rec in body["recommendations"]:
        if rec.get("effect") is not None:
            checks.append((Effect, rec["effect"]))
        if rec.get("marker") is not None:
            checks.append((MapPoint, rec["marker"]))
        if rec.get("site_question") is not None:
            checks.append((SiteQuestion, rec["site_question"]))
    errors = []
    for model, payload in checks:
        try:
            model.model_validate(payload)
        except ValidationError as exc:
            errors.append(f"{model.__name__}\n{_show(exc)}")
    assert not errors, "\n\n".join(errors)
    CacheMeta.model_validate({"ref": PID, "saved_at": "2026-11-21T12:00:00+00:00", "origin": "test", "hit": True})
