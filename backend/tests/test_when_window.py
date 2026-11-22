"""Pętla miesięcy zakresu i etykieta części wspólnej. Bez HTTP."""

from datetime import date

from app.engine import crop as cropmod
from app.engine.plain import month_range, months
from app.engine.terrain_rules import RULES
from app.engine.weather import Series
from app.engine.when_window import apply, clip, months_label, months_touched
from app.models import Evidence, Meteo, Parcel, ParcelContext, Recommendation, RecommendRequest


def _card(code, **kw):
    rule = RULES[code]
    data = dict(
        id=code.lower(), rule=code, group=rule["group"],
        when_short=rule.get("when_short"), when_text=rule.get("when_text"),
        title=rule.get("title"), message=kw.pop("message", rule.get("message") or "m"),
        why="w", confidence="srednia", evidence=kw.pop("evidence", []),
    )
    data.update(kw)
    return Recommendation(**data)


def _around(frm, to, crop="zboza_jare"):
    ctx = ParcelContext(
        as_of=frm,
        parcel=Parcel(id="x", rings=[[[16, 52], [16.1, 52], [16.1, 52.1], [16, 52]]],
                      centroid=[16.05, 52.05], area_ha=1.0),
        meteo=Meteo(daily=[], resolution="SYNTETYCZNE"),
    )
    req = RecommendRequest(crop=crop, range={"from": frm.isoformat(), "to": to.isoformat()})
    return ctx, req


def test_may_touches_only_may():
    pairs = months_touched(date(2026, 5, 1), date(2026, 5, 31))
    assert pairs == [(2026, 5)]
    assert (2026, 2) not in pairs and (2026, 3) not in pairs


def test_february_april_touches_february_and_march():
    pairs = months_touched(date(2026, 2, 1), date(2026, 4, 30))
    assert (2026, 2) in pairs and (2026, 3) in pairs


def test_two_year_may_touches_later_winters():
    pairs = set(months_touched(date(2026, 5, 1), date(2028, 5, 1)))
    for pair in ((2027, 2), (2027, 3), (2028, 2), (2028, 3)):
        assert pair in pairs
    assert (2026, 2) not in pairs and (2026, 3) not in pairs


def test_november_may_touches_one_winter():
    pairs = set(months_touched(date(2025, 11, 1), date(2026, 5, 22)))
    assert (2026, 2) in pairs and (2026, 3) in pairs
    assert (2025, 2) not in pairs and (2025, 3) not in pairs


def test_one_day_of_a_month_counts():
    assert months_touched(date(2026, 5, 31), date(2026, 6, 1)) == [(2026, 5), (2026, 6)]


def test_label_wraps_across_new_year():
    wrapped = months_label({11, 12, 1, 2, 3})
    assert wrapped == month_range(["11", "12", "01", "02", "03"])
    assert wrapped != month_range(["01", "02", "03", "11", "12"])
    assert months_label({5, 8, 9}) == f"{month_range(['05'])} lub {month_range(['08', '09'])}"


def test_r11_march_chip_is_only_march():
    out = clip(_card("R11"), date(2026, 3, 1), date(2026, 3, 31))
    label = month_range(["03"])
    assert out is not None
    assert out.when_short == label
    assert out.when_text == RULES["R11"]["when_text"].replace(RULES["R11"]["when_short"], label, 1)
    assert clip(_card("R11"), date(2026, 3, 15), date(2026, 3, 15)).when_short == label


def test_r11_full_window_keeps_the_yaml_phrase():
    for frm, to in ((date(2026, 2, 1), date(2026, 4, 30)),
                    (date(2025, 11, 1), date(2026, 5, 22)),
                    (date(2026, 5, 1), date(2028, 5, 1))):
        out = clip(_card("R11"), frm, to)
        assert out.when_short == RULES["R11"]["when_short"]
        assert out.when_text == RULES["R11"]["when_text"]


def test_r11_may_is_removed():
    assert clip(_card("R11"), date(2026, 5, 1), date(2026, 5, 31)) is None


def test_r3_and_r14_clauses_follow_the_overlap():
    may = clip(_card("R3"), date(2026, 5, 1), date(2026, 5, 31))
    assert may.when_short == month_range(["05"])
    assert may.when_text == "Wysiej trawę w pasie wiosną (maj)."
    september = clip(_card("R3"), date(2026, 9, 1), date(2026, 9, 30))
    assert september.when_short == month_range(["09"])
    assert september.when_text == "Wysiej trawę w pasie pod koniec lata lub wczesną jesienią (wrzesień)."
    both = clip(_card("R3"), date(2026, 5, 1), date(2026, 9, 30))
    assert both.when_short == f"{month_range(['05'])} lub {month_range(['08', '09'])}"
    assert both.when_text == (
        f"Wysiej trawę w pasie pod koniec lata lub wczesną jesienią ({month_range(['08', '09'])}) "
        f"albo wiosną ({month_range(['05'])}).")
    year = clip(_card("R3"), date(2026, 1, 1), date(2026, 12, 31))
    assert year.when_short == RULES["R3"]["when_short"] and year.when_text == RULES["R3"]["when_text"]

    assert clip(_card("R14"), date(2026, 5, 1), date(2026, 5, 31)).when_text == "Pas zakładaj wiosną (maj)."
    august = clip(_card("R14"), date(2026, 8, 1), date(2026, 8, 31))
    assert august.when_short == month_range(["08"])
    assert august.when_text == "Pas zakładaj pod koniec lata (sierpień)."
    span = clip(_card("R14"), date(2026, 5, 1), date(2026, 8, 31))
    assert span.when_short == f"{month_range(['05'])} lub {month_range(['08'])}"
    assert span.when_text == "Pas zakładaj wiosną (maj) lub pod koniec lata (sierpień)."


def test_post_harvest_february_keeps_partial_gap():
    """Zboża jare: luka od zbioru w sierpniu do siewu 1 kwietnia. Kwiecień już poza luką."""
    frm, to = date(2026, 2, 1), date(2026, 4, 30)
    ctx, req = _around(frm, to)
    label = month_range(["02", "03"])
    out = {r.rule: r for r in apply([_card("R2"), _card("R7"), _card("R8")], ctx, req)}
    assert set(out) == {"R2", "R7", "R8"}
    assert out["R2"].when_short == label
    assert out["R2"].when_text == RULES["R2"]["when_text"].replace("(po zbiorze)", f"({label})")
    for code in ("R7", "R8"):
        tail = RULES[code]["when_text"].split(":", 1)[1].lstrip()
        assert out[code].when_short == label
        assert out[code].when_text == f"W terminie {label}: {tail}"
    may_ctx, may_req = _around(date(2026, 5, 1), date(2026, 5, 31))
    assert apply([_card("R2"), _card("R7"), _card("R8")], may_ctx, may_req) == []


def test_sowing_month_stays_przy_siewie():
    ctx, req = _around(date(2026, 5, 1), date(2026, 5, 31), crop="kukurydza_ziarno")
    out = apply([_card("R1")], ctx, req)
    assert len(out) == 1 and out[0].when_short == RULES["R1"]["when_short"]
    assert out[0].when_text == RULES["R1"]["when_text"]
    april_ctx, april_req = _around(date(2026, 4, 1), date(2026, 4, 30), crop="kukurydza_ziarno")
    assert apply([_card("R1")], april_ctx, april_req) == []
    # siew 1 kwietnia; sam kwiecień jest całym oknem R1
    series = Series(days={}, first=date(2026, 1, 1), last=date(2026, 1, 1))
    assert cropmod.season("zboza_jare", 2026, series).start == date(2026, 4, 1)


def test_r15_history_keeps_only_months_inside_the_range():
    codes = ["05", "06", "07", "08"]
    card = _card(
        "R15", message="zostaje", why="też",
        when_short=month_range(codes),
        when_text=RULES["R15"]["when_history"].format(months=months(codes)),
        evidence=[Evidence(field="susceptibility.risk_months", value=codes)])
    may = clip(card, date(2026, 5, 1), date(2026, 5, 31))
    assert may.when_short == month_range(["05"])
    assert may.when_text == RULES["R15"]["when_history"].format(months=months(["05"]))
    assert may.message == "zostaje" and may.why == "też"
    assert clip(card, date(2026, 2, 1), date(2026, 4, 30)) is None
    full = clip(card, date(2026, 5, 1), date(2026, 8, 31))
    assert full.when_short == card.when_short and full.when_text == card.when_text


def test_forecast_now_and_r16_keep_their_wording():
    forecast = _card(
        "R15", message="m", when_short="przed końcem czerwca",
        when_text="Zanim zacznie brakować wody w glebie, najpewniej pod koniec czerwca.",
        evidence=[Evidence(field="forecast.days_to_raw.median", value=20)])
    kept = clip(forecast, date(2026, 11, 1), date(2026, 12, 1))
    assert kept.when_short == "przed końcem czerwca" and kept.when_text == forecast.when_text
    now = _card("IRR", when_short="teraz", when_text="Teraz: w glebie już brakuje wody dla roślin.")
    kept_now = clip(now, date(2026, 1, 1), date(2026, 1, 31))
    assert kept_now.when_short == "teraz"
    assert kept_now.when_text == "Teraz: w glebie już brakuje wody dla roślin."
    assert clip(_card("R16"), date(2026, 5, 1), date(2026, 5, 31)).rule == "R16"
