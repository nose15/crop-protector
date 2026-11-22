"""Reguły terenowe: działka testowa + przypadki brzegowe + niezmienniki (evidence, G4, kolejność grup)."""

import copy
import gzip
import json

import pytest

from app.engine.terrain_rules import evaluate
from app.models import ParcelContext, RecommendRequest, Water
from app.terrain import analysis as A
from conftest import FIXTURES

PID = "046101_1.0445.7"


@pytest.fixture(scope="module")
def ctx() -> ParcelContext:
    raw = json.loads((FIXTURES / f"context_{PID}_partial.json").read_text())
    g = A.parse_aaigrid(gzip.open(FIXTURES / f"nmt_{PID}.asc.gz").read().decode())
    raw["terrain"] = A.compute(g, raw["parcel"]["rings"][0], 50)      # teren liczony aktualnym kodem
    return ParcelContext(**raw)


def req(crop="zboza_ozime", **answers) -> RecommendRequest:
    return RecommendRequest(crop=crop, range={"from": "2026-11-21", "to": "2026-12-21"}, answers=answers)


def codes(out):
    return [r.rule for r in out.recommendations]


def test_parcel_recommends_weir_not_pond(ctx):
    out = evaluate(ctx, req())
    assert "R11" in codes(out) and "R6" not in codes(out)
    r11 = next(r for r in out.recommendations if r.rule == "R11")
    assert r11.conditional and r11.confidence == "srednia"
    assert r11.site_question == {"id": "ditch0", "text": "Czy w tym miejscu jest rów?"}
    assert r11.consult_note                                           # G4
    assert "trafia do niego w 2 miejscach" in r11.why
    assert "częściowo na działce" in r11.why                         # rów przy SW krawędzi, nie ten przy skrzyżowaniu
    assert "0,98 m" in r11.why and "najpewniej rów" in r11.why       # przecinek dziesiętny, prosty język


def test_flat_parcel_flow_strip_has_low_confidence(ctx):
    out = evaluate(ctx, req())
    r3 = next(r for r in out.recommendations if r.rule == "R3")
    assert r3.confidence == "niska"                                   # P90 2,64° < 3°
    assert out.c3.dominant


def test_farmer_confirms_or_rejects_ditch(ctx):
    yes = next(r for r in evaluate(ctx, req(sites={"ditch0": True})).recommendations if r.rule == "R11")
    assert not yes.conditional and yes.confidence == "wysoka" and yes.site_question is None
    other = next(r for r in evaluate(ctx, req(sites={"ditch0": False})).recommendations if r.rule == "R11")
    assert other.marker["id"] == "ditch1"                             # pierwszy odrzucony -> następny rów
    none = evaluate(ctx, req(sites={"ditch0": False, "ditch1": False, "ditch2": False}))
    assert "R11" not in codes(none)


def test_existing_weir_answer_changes_message(ctx):
    r11 = next(r for r in evaluate(ctx, req(ditch_with_weir=True)).recommendations if r.rule == "R11")
    assert "Steruj nią" in r11.message and r11.confidence == "wysoka"


def test_missing_sources_are_not_evaluated(ctx):
    out = evaluate(ctx, req())
    assert any(n.rule == "R14" for n in out.not_evaluated)            # Overpass nie odpowiedział
    no_dem = ctx.model_copy(update={"terrain": None})
    out2 = evaluate(no_dem, req())
    assert codes(out2) == [] and out2.c3.confidence == "nie_oceniono"
    assert {n.rule for n in out2.not_evaluated} >= {"R11", "R6", "R3", "R2", "R1", "R14"}


def test_osm_watercourse_and_ditch(ctx):
    c = ctx.model_copy(update={"terrain": None, "water": Water(nearest_ditch_m=40, nearest_watercourse_m=30)})
    out = evaluate(c, req())
    assert codes(out) == ["R11", "R14"]


def _with_stats(ctx, **stats):
    t = copy.deepcopy(ctx.terrain)
    t["stats"].update(stats)
    return ctx.model_copy(update={"terrain": t})


def test_steep_gives_strips_and_contour_sowing_for_row_crop(ctx):
    steep = _with_stats(ctx, slope_p90_deg=8.0, flat_terrain=False)
    out = evaluate(steep, req(crop="kukurydza_ziarno"))
    assert "R2" in codes(out) and "R3" not in codes(out) and "R1" in codes(out)
    assert "R1" not in codes(evaluate(steep, req(crop="zboza_ozime")))  # zboża nie są uprawą rzędową


def test_invariants(ctx):
    for answers in ({}, {"ditch_with_weir": True}, {"sites": {"ditch0": True}}):
        for crop in ("zboza_ozime", "ziemniak"):
            out = evaluate(_with_stats(ctx, slope_p90_deg=4.0), req(crop=crop, **answers))
            for r in out.recommendations:
                assert r.evidence, r.rule                             # każda karta ma dowód z danych
                assert (r.consult_note is not None) == (r.rule in ("R11", "R6")), r.rule
                assert r.confidence in ("wysoka", "srednia", "niska")
