"""Część pogodowa wyniku: KBW, stan wody w glebie w dniu D, prognoza na zakres dat, podatność z 10 lat,
przyczyny C1 i C4 oraz reguły R15, R16, R7, R8 i nawadnianie. Liczby tylko z silnika (FAO-56, rozporządzenie)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.engine import balance, crop as cropmod, forecast as fc, kbw, plain
from app.engine.confidence import min_conf
from app.engine.terrain_rules import RULES, _rec, pl, th
from app.engine.weather import build_series
from app.models import Cause, Evidence, NotEvaluated, ParcelContext, Recommendation, RecommendRequest

MONTHS = {"01": "styczeń", "02": "luty", "03": "marzec", "04": "kwiecień", "05": "maj", "06": "czerwiec",
          "07": "lipiec", "08": "sierpień", "09": "wrzesień", "10": "październik", "11": "listopad", "12": "grudzień"}


@dataclass
class WeatherOutcome:
    kbw: dict | None = None
    soil_water: dict | None = None
    forecast: dict | None = None
    susceptibility: dict | None = None
    causes: list[Cause] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    not_evaluated: list[NotEvaluated] = field(default_factory=list)
    uncertainty: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    taw_conf: str = "nie_oceniono"


def _months_text(codes: list[str]) -> str:
    return ", ".join(MONTHS[m] for m in codes)


def _shares(ctx: ParcelContext) -> dict | None:
    return ctx.soil.iung.shares if ctx.soil and ctx.soil.iung else None


def evaluate(ctx: ParcelContext, req: RecommendRequest, c2: Cause, c3: Cause | None) -> WeatherOutcome:
    out = WeatherOutcome()
    d, to, crop = req.range.from_, req.range.to, req.crop
    c = cropmod.CROPS[crop]
    series = build_series(ctx.meteo, d, through=to)
    if series.filled:
        out.limitations.append("W danych pogodowych brakowało kilku dni; uzupełniliśmy je wartościami z sąsiednich dni.")
    shares = _shares(ctx)

    # --- KBW
    if c.get("no_kbw"):
        out.kbw = {"status": "brak_progu", "method": kbw.METHOD, "note": "Dla użytków zielonych rozporządzenie nie podaje progów KBW."}
    else:
        out.kbw = kbw.status_at(series, d, crop, shares)

    # --- TAW i stan w dniu D
    runs = balance.taw_runs(ctx, crop)
    st = fc.state_at(series, crop, runs, d, to, req.sowing_date) if runs else None
    if not runs:
        out.not_evaluated += [NotEvaluated(rule=r, reason="brak mapy gleby") for r in ("R15", "R7", "nawadnianie")]
    elif st is None:
        out.not_evaluated += [NotEvaluated(rule=r, reason="brak pełnych danych pogodowych od 1 marca") for r in ("R15", "nawadnianie")]
    if runs and st:
        finals, seasons = st
        taws = [r.taw_mm for r in runs]
        out.taw_conf = "srednia" if max(taws) / max(min(taws), 1) <= 2.5 else "niska"
        if len(set(r.label.split(",")[0] for r in runs)) < 3:
            out.taw_conf = min_conf(out.taw_conf, "niska" if len(runs) <= 2 else "srednia")
        season_now = seasons[d.year]
        mid = sorted(range(len(runs)), key=lambda i: runs[i].taw_mm)[len(runs) // 2]
        out.soil_water = {
            "taw_mm": balance.interval(taws),
            "dr_mm": balance.interval([f.dr for f in finals]),
            "pct_of_taw": balance.interval([round(100 * (1 - f.dr / r.taw_mm)) for f, r in zip(finals, runs)]),
            "below_raw": finals[mid].dr > finals[mid].raw,
            "phase": season_now.stage(d), "phase_label": cropmod.stage_label(season_now.stage(d)),
            "kc": round(finals[mid].kc, 2), "season_start": season_now.start, "harvest": season_now.ends[-1],
            # poziom wody (% pełnego), poniżej którego roślina zaczyna cierpieć: 100·(1 − RAW/TAW), środkowy przebieg
            "safe_level_pct": round(100 * (1 - finals[mid].raw / runs[mid].taw_mm)),
            "season_start_source": season_now.start_source, "taw_runs": [r.label for r in runs],
        }
        use_fc = bool(series.forecast) and d == ctx.as_of
        out.forecast = fc.forecast(series, crop, runs, finals, seasons, d, to, ctx.parcel.area_ha, use_fc)
        out.soil_water["series"] = fc.water_series(series, crop, runs, finals, seasons, d, to, use_fc)
        out.susceptibility = fc.susceptibility(series, crop, runs, shares, d, req.sowing_date, bool(c.get("no_kbw")))
        if out.taw_conf == "niska":
            out.uncertainty.append("Mapy gleby różnią się w ocenie, ile wody gleba może zatrzymać.")
    out.uncertainty.append("Ocena suszy jest przybliżona: parowanie liczymy innym wzorem niż oficjalny system monitoringu suszy (IUNG).")

    sus, fcst = out.susceptibility, out.forecast
    # --- C1: brak opadu, upał
    c1 = Cause(code="C1", dominant=False, confidence="nie_oceniono", why="Brak oceny KBW.")
    if out.kbw and out.kbw.get("kbw_mm") is not None:
        ref_status = out.kbw.get("period_status")
        exceeded = sus and sus.get("n_kbw") is not None and sus["of_kbw"] and sus["n_kbw"] >= 3
        dominant = ref_status == "zagrozenie" or bool(exceeded)
        v = pl(k=out.kbw["kbw_mm"])
        why = f"Opady minus parowanie w ostatnim okresie ({out.kbw['period']['label']}): {v['k']} mm"
        why += (f", próg suszy {pl(t=out.kbw['threshold_mm'])['t']} mm." if out.kbw.get("threshold_mm") is not None else ".")
        if sus and sus.get("n_kbw") is not None:
            why += f" Susza z braku deszczu w {sus['n_kbw']} z {sus['of_kbw']} ostatnich lat."
        evidence = [Evidence(field="state.kbw.kbw_mm", value=out.kbw["kbw_mm"])]
        if out.kbw.get("threshold_mm") is not None:
            evidence.append(Evidence(field="state.kbw.threshold_mm", value=out.kbw["threshold_mm"]))
        if sus and sus.get("n_kbw") is not None:
            evidence.append(Evidence(field="susceptibility.n_kbw", value=sus["n_kbw"]))
            evidence.append(Evidence(field="susceptibility.of_kbw", value=sus["of_kbw"]))
        c1 = Cause(code="C1", dominant=dominant, confidence="srednia", why=why,
                   confidence_reason="KBW to przybliżenie metodyki SMSR (parowanie liczone wzorem FAO).",
                   evidence=evidence)
    # --- C4: uprawa w złym oknie
    c4 = Cause(code="C4", dominant=False, confidence="nie_oceniono", why="Brak bilansu wody z 10 lat.")
    if sus and sus.get("n_ks") is not None:
        c4 = Cause(code="C4", dominant=sus["n_ks"] >= 5, confidence="niska",
                   why=f"W {sus['n_ks']} z {sus['of']} ostatnich lat roślinom brakowało wody w czasie pełnego wzrostu"
                       + (f", najczęściej: {_months_text(sus['risk_months'])}." if sus["risk_months"] else "."),
                   confidence_reason="Daty faz uprawy i próg 10 dni niedoboru to heurystyki do weryfikacji z doradcą.",
                   evidence=[Evidence(field="susceptibility.n_ks", value=sus["n_ks"]),
                             Evidence(field="susceptibility.of", value=sus["of"])])
    out.causes = [c1, c4]

    _rules(ctx, req, out, c1, c2, c3, c4)
    return out


def _rules(ctx, req, out: WeatherOutcome, c1, c2, c3, c4) -> None:
    sus, fcst, sw = out.susceptibility, out.forecast, out.soil_water
    d = req.range.from_
    light_pct = round(100 * sum((_shares(ctx) or {}).get(k, 0) for k in ("I", "II")))

    # R15: okres największego ryzyka (prognoza albo historia)
    r = RULES["R15"]
    fc_ok = fcst and fcst.get("status") == "ok"
    if fc_ok and fcst["stress_chance"]["n"] >= th("stress_chance_r15") and fcst["days_to_raw"]["n"]:
        dtr = fcst["days_to_raw"]
        date_low = d + timedelta(days=int(dtr["low"]))
        out.recommendations.append(_rec(
            "R15", message=r["message_forecast"] + " " + r["action"],
            why=r["why_forecast"].format(chance_text=plain.chance(fcst["stress_chance"]["n"])),
            confidence=min_conf("srednia", out.taw_conf), conditional=False,
            confidence_reason="Scenariusze z pogody 10 poprzednich lat, nie prognoza na miesiące. " + ("Zapas wody w glebie z map o zbliżonych wartościach." if out.taw_conf == "srednia" else "Mapy glebowe dają rozbieżny zapas wody w glebie."),
            evidence=[("forecast.stress_chance.n", fcst["stress_chance"]["n"]), ("forecast.days_to_raw.median", dtr["median"])]))
        out.recommendations[-1].when_text = r["when_forecast"].format(when_text=plain.when(date_low))
        out.recommendations[-1].when_short = "przed " + plain.when(date_low).replace("na początku", "początkiem").replace(
            "w połowie", "połową").replace("pod koniec", "końcem")
    elif c4.dominant and sus and sus["risk_months"]:
        out.recommendations.append(_rec(
            "R15", message=r["message_history"] + " " + r["action"],
            why=r["why_history"].format(frequency_text=plain.frequency(sus["n_ks"], sus["of"])), confidence=c4.confidence,
            confidence_reason="Daty faz uprawy i próg 10 dni niedoboru to heurystyki do weryfikacji z doradcą.",
            evidence=[("susceptibility.n_ks", sus["n_ks"]), ("susceptibility.risk_months", sus["risk_months"])]))
        out.recommendations[-1].when_text = r["when_history"].format(months=plain.months(sus["risk_months"]))
        out.recommendations[-1].when_short = plain.month_range(sus["risk_months"])

    # R7, R8: gleba lekka
    if c2.dominant and sw:
        out.recommendations.append(_rec(
            "R7", why=RULES["R7"]["why"],
            confidence=min_conf("srednia", out.taw_conf), confidence_reason="Kategoria gleby z mapy IUNG (5 m). " + ("Zapas wody w glebie z map o zbliżonych wartościach." if out.taw_conf == "srednia" else "Mapy glebowe dają rozbieżny zapas wody w glebie."),
            evidence=[("soil.iung.shares.I+II", light_pct), ("state.soil_water.taw_mm", sw["taw_mm"])]))
    sg = ctx.soil.soilgrids if ctx.soil else None
    if c2.dominant and sg and sg.soc_gkg is not None and sg.soc_gkg < th("low_soc_gkg"):
        out.recommendations.append(_rec(
            "R8", why=RULES["R8"]["why"],
            confidence="niska", evidence=[("soil.soilgrids.soc_gkg", sg.soc_gkg)],
            confidence_reason="Węgiel organiczny z mapy SoilGrids (siatka 250 m) – zgrubne oszacowanie."))
    elif c2.dominant and (sg is None or sg.soc_gkg is None):
        out.not_evaluated.append(NotEvaluated(rule="R8", reason="brak danych o próchnicy w glebie"))

    # R16: retencja ma mały zasięg
    if c1.dominant and not c2.dominant and c3 is not None and not c3.dominant and sus and sus.get("n_kbw") is not None:
        out.recommendations.append(_rec(
            "R16", why=RULES["R16"]["why"], confidence="srednia",
            confidence_reason="KBW to przybliżenie metodyki SMSR (parowanie liczone wzorem FAO).",
            evidence=[("susceptibility.n_kbw", sus["n_kbw"]), ("causes.C3.dominant", False)]))

    # Nawadnianie: zawsze ostatnie (G2); tylko gdy woda nie jest wykluczona
    water = req.answers.irrigation_water
    if fc_ok and sw and (sw["below_raw"] or fcst["stress_chance"]["n"] >= th("stress_chance_irrigation")):
        dm, d3 = fcst["deficit_mm"], fcst["deficit_m3"]
        if water is False:
            out.not_evaluated.append(NotEvaluated(rule="nawadnianie", reason="nie masz wody do nawadniania"))
        elif dm["high"] and dm["high"] >= 1:
            ri = RULES["IRR"]
            rec = _rec("IRR", message=ri["message_confirmed"] if water else ri["message"],
                       why=ri["why"].format(**pl(amount=(f"do ok. {d3['high']} m³" if not d3["low"] else
                                                         f"ok. {d3['low']}–{d3['high']} m³"), area=round(ctx.parcel.area_ha, 2))),
                       confidence=min_conf("srednia", out.taw_conf), conditional=water is None,
                       confidence_reason="Niedobór z bilansu wody FAO-56; zakres zależy od zapasu wody w glebie. " + ("Zapas wody w glebie z map o zbliżonych wartościach." if out.taw_conf == "srednia" else "Mapy glebowe dają rozbieżny zapas wody w glebie."),
                       evidence=[("forecast.deficit_mm", dm), ("forecast.deficit_m3", d3)])
            rec.consult_note = (rec.consult_note or "") + " " + ri["consult_extra"]
            dtr = fcst.get("days_to_raw") or {}
            if dtr.get("median") is not None:
                rec.when_text = ri["when_text"].format(when_text=plain.when(d + timedelta(days=int(dtr["median"]))))
                rec.when_short = plain.when(d + timedelta(days=int(dtr["median"])))
            elif sw["below_raw"]:
                L = plain.day_label(d)
                rec.when_short = L
                rec.when_text = f"{L}: w glebie już brakuje wody dla roślin."
            rec.id = "nawadnianie"
            out.recommendations.append(rec)
