"""Silnik pogodowy: KBW (ręczne sumy, listopad = poza_okresem), bilans FAO-56, fazy, prognoza, podatność."""

from datetime import date, timedelta

import pytest

from app.engine import balance, crop as cropmod, forecast as fc, kbw
from app.engine.weather import build_series
from app.models import Meteo
from synthetic_meteo import generate


def const_meteo(start, end, p, et0, t=15.0) -> Meteo:
    days, d = [], start
    while d <= end:
        days.append({"date": d, "p_mm": p, "et0_mm": et0, "tmax": t + 5, "tmin": t - 5})
        d += timedelta(days=1)
    return Meteo(daily=days, forecast=[], resolution="TEST")


SHARES_IV = {"I": 0, "II": 0, "III": 0, "IV": 1.0}


def test_kbw_period_sum_and_threshold():
    s = build_series(const_meteo(date(2025, 3, 1), date(2025, 9, 30), p=1.0, et0=3.0), date(2025, 9, 30))
    p0 = kbw.periods_of(2025)[0]                                    # 21 III – 20 V = 61 dni
    assert (p0["end"] - p0["start"]).days + 1 == 61
    assert kbw.kbw_mm(s, p0["start"], p0["end"]) == pytest.approx(-122.0)
    thr, code = kbw.threshold("zboza_ozime", SHARES_IV, 0)
    assert (thr, code) == (-215, "ok")                              # załącznik: zboża ozime, kat. IV, 21 III–20 V
    assert kbw.status_of(-122.0, thr, code) == ("brak_zagrozenia", 93.0)
    assert kbw.status_of(-244.0, thr, code)[0] == "zagrozenie"
    assert kbw.status_of(-205.0, thr, code)[0] == "na_granicy"     # |margines| < 15 mm


def test_kbw_weighted_threshold_and_not_indicated():
    thr, _ = kbw.threshold("zboza_ozime", {"III": 0.173, "IV": 0.827}, 0)
    assert thr == pytest.approx(0.173 * -188 + 0.827 * -215, abs=0.1)
    assert kbw.threshold("zboza_ozime", SHARES_IV, 9) == (None, "brak_progu")         # „x” w tabeli
    assert kbw.threshold("burak_cukrowy", {"I": 1.0}, 0) == (None, "niewskazana")       # „-” w tabeli


def test_november_is_outside_period():
    """Obowiązkowy: jury ocenia 21–22 listopada, poza okresem 21 III–30 IX."""
    d = date(2026, 11, 21)
    s = build_series(const_meteo(date(2016, 3, 1), d, p=1.0, et0=3.0), d)
    res = kbw.status_at(s, d, "zboza_ozime", SHARES_IV)
    assert res["status"] == "poza_okresem"
    assert res["period"]["label"].startswith("1 VIII")             # ostatni okres sezonu
    assert res["kbw_mm"] is not None and "poza okresem" in res["note"]


def test_balance_step_matches_fao56():
    # TAW 100, p 0,5: Dr ≤ RAW -> Ks = 1; Dr > RAW -> Ks = (TAW − Dr)/((1 − p)·TAW)
    dr, raw, ks, etc, adj = balance.step(dr=40, p_mm=0, et0=5, kc=1.0, taw=100, p_tab=0.5)
    assert (raw, ks, etc, adj, dr) == (50.0, 1.0, 5.0, 5.0, 45.0)
    dr, raw, ks, etc, adj = balance.step(dr=70, p_mm=0, et0=5, kc=1.0, taw=100, p_tab=0.5)
    assert ks == pytest.approx(0.6) and dr == pytest.approx(73.0)
    dr, *_ = balance.step(dr=10, p_mm=30, et0=2, kc=1.0, taw=100, p_tab=0.5)
    assert dr == 0.0                                                # nadmiar opadu odpływa w głąb


def test_vegetation_start_and_kc_curve():
    d = date(2026, 11, 21)
    meteo = Meteo(daily=generate(date(2016, 3, 1), d), forecast=[], resolution="SYNTETYCZNE")
    s = build_series(meteo, d)
    vs = cropmod.vegetation_start(s, 2025)
    assert date(2025, 3, 1) <= vs <= date(2025, 4, 30)
    season = cropmod.season("kukurydza_ziarno", 2025, s)
    assert season.start == date(2025, 5, 1) and season.start_source == "heurystyka_siewu"
    assert cropmod.kc("kukurydza_ziarno", season, date(2025, 5, 10)) == 0.3
    assert cropmod.kc("kukurydza_ziarno", season, date(2025, 7, 20)) == 1.20
    assert cropmod.kc("kukurydza_ziarno", season, date(2025, 12, 1)) == cropmod.KC_OFF


@pytest.fixture(scope="module")
def synth():
    d = date(2026, 11, 21)
    return d, build_series(Meteo(daily=generate(date(2016, 3, 1), d), forecast=[], resolution="SYNTETYCZNE"), d)


def test_balance_on_fixture_is_stable(synth):
    """Obowiązkowy: bilans na stałych danych daje stały wynik (regresja)."""
    _, s = synth
    days = balance.history_days(s, date(2025, 3, 1), date(2025, 10, 31))
    seasons = {2025: cropmod.season("zboza_jare", 2025, s)}
    sim = balance.simulate(days, "zboza_jare", seasons, taw=150.0)
    assert len(sim) == 245
    stress = sum(1 for x in sim if x.ks < 1)
    snapshot = (round(max(x.dr for x in sim), 1), stress, round(sum(x.etc_adj for x in sim), 1))
    assert snapshot == SNAPSHOT_BALANCE, snapshot


def test_susceptibility_counts_dry_years(synth):
    d, s = synth
    runs = [balance.TawRun("t", 120.0)]
    sus = fc.susceptibility(s, "kukurydza_ziarno", runs, SHARES_IV, d, None, False)
    assert sus["years"] == [2017, 2026] and sus["of"] == 10
    assert 0 <= sus["n_ks"] <= 10 and sus["of_kbw"] == 10
    dry = {y["year"]: y["stress_days_critical"] for y in sus["per_year"]}
    assert dry[2019] > dry[2020]                                    # rok suchy ma więcej dni stresu niż mokry


SNAPSHOT_BALANCE = (141.0, 74, 326.1)   # (max Dr mm, dni stresu, ΣETc,adj mm) dla syntetycznego 2025, TAW 150 mm


def test_real_fixture_regression():
    """Prawdziwy kontekst działki testowej (Open-Meteo pobrane 21.11.2026). Stały wynik = regresja silnika.
    Sprawdzenie sensu: lata suche w Polsce (2018, 2019, 2022, 2023) mają więcej dni stresu niż mokry 2017."""
    import gzip
    import json

    from app.engine.assemble import build
    from app.models import ParcelContext, RecommendRequest
    from conftest import FIXTURES

    raw = json.load(gzip.open(FIXTURES / "context_046101_1.0445.7_real.json.gz", "rt", encoding="utf-8"))
    ctx = ParcelContext(**raw)
    req = RecommendRequest(crop="zboza_ozime", range={"from": "2026-11-21", "to": "2027-05-22"})
    res = build(ctx, req)
    assert res.state["kbw"]["status"] == "poza_okresem"
    per_year = {y["year"]: y["stress_days_critical"] for y in res.susceptibility["per_year"]}
    assert per_year[2017] < min(per_year[y] for y in (2018, 2019, 2022, 2023))
    assert (res.susceptibility["n_ks"], res.susceptibility["n_kbw"]) == (7, 0)
    assert res.forecast["status"] == "ok" and res.forecast["stress_chance"]["n"] == 3
    assert res.forecast["forecast_days_used"] == 15
