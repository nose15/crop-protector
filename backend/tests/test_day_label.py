"""Etykieta dnia range.from: „Dzisiaj” albo długa data. Bez HTTP i bez Open-Meteo."""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.engine.plain import day_label, warsaw_today

ENGINE = Path(__file__).resolve().parents[1] / "app" / "engine"
TODAY = date(2026, 11, 22)


def test_today_when_range_from_is_the_frozen_warsaw_day():
    # range.from równe as_of, a as_of jest dniem zamrożonym jako dzisiejszy w Europe/Warsaw.
    assert day_label(date(2026, 11, 22), today=TODAY) == "Dzisiaj"


def test_other_day_is_the_long_polish_date():
    assert day_label(date(2024, 3, 21), today=TODAY) == "21 marca 2024"
    assert day_label(date(2024, 9, 1), today=TODAY) == "1 września 2024"


def test_historical_as_of_equal_to_range_from_is_not_today():
    # Historyczne as_of równe range.from nie jest argumentem today.
    assert day_label(date(2024, 3, 21), today=TODAY) != "Dzisiaj"


def test_warsaw_today_uses_europe_warsaw():
    assert warsaw_today() == datetime.now(ZoneInfo("Europe/Warsaw")).date()


def test_sources_keep_kbw_now_and_use_day_label():
    rules = (ENGINE / "weather_rules.py").read_text(encoding="utf-8")
    assert "plain.day_label" in rules
    assert 'when_short = "teraz"' not in rules
    assert "Teraz: w glebie" not in rules

    plain = (ENGINE / "plain.py").read_text(encoding="utf-8")
    assert "Teraz jest poza sezonem wzrostu, susza rolnicza nie grozi." in plain

    assemble = (ENGINE / "assemble.py").read_text(encoding="utf-8")
    assert "Teraz jest poza sezonem monitoringu suszy (21 III–30 IX)." in assemble
    assert "Bilans opadu i parowania jest teraz poniżej progu suszy dla tej uprawy i gleby." in assemble
    assert "Bilans opadu i parowania jest teraz blisko progu suszy." in assemble
    assert "Bilans opadu i parowania jest teraz powyżej progu suszy." in assemble
