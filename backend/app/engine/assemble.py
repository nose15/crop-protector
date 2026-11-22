"""Składanie AnalysisResult: przyczyny, reguły, kolejność grup, limit kart, niepewność, ograniczenia, nagłówek.

Kolejność grup jest wiążąca: retencja → agrotechnika → nawadnianie (nawadnianie zawsze ostatnie, G2).
Każda liczba w tekstach pochodzi z silnika; brak danych to „nie oceniono” (G1, G3).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.engine import plain, terrain_rules, weather_rules, when_window
from app.engine.confidence import min_conf
from app.models import AnalysisResult, Answers, Cause, Evidence, NotEvaluated, ParcelContext, RecommendRequest

GROUP_ORDER = {"retencja": 0, "agrotechnika": 1, "nawadnianie": 2}
MAX_CARDS = 5

BASE_LIMITATIONS = [
    "Dalej niż 16 dni naprzód nie ma prognozy pogody: pokazujemy, jak było w tych samych dniach w ostatnich 10 latach.",
    "Mapa terenu nie pokazuje przepustów pod drogami, więc rowy rozpoznajemy po kształcie.",
    "Daty siewu przyjmujemy typowe, chyba że podasz własną.",
]


def weather_limitation(ctx: ParcelContext) -> str:
    if ctx.meteo is not None and ctx.meteo.history_source == "nasa_power":
        return "Pogodę bierzemy z siatki o oczku ok. 50 km (NASA POWER), więc lokalnych burz możemy nie widzieć."
    return "Pogodę bierzemy z siatki o oczku ok. 10 km, więc lokalnych burz możemy nie widzieć."


def water_limitation(answers: Answers) -> str:
    """Jedno zdanie wody: gruntowej nie liczymy; drenowanie i nawadnianie tylko przy braku odpowiedzi."""
    missing: list[str] = []
    if answers.drained is None:
        missing.append("drenowanie")
    if answers.irrigation_water is None:
        missing.append("nawadnianie")
    if len(missing) == 2:
        return "Nie liczymy wody gruntowej, a drenowania ani nawadniania nie uwzględniamy, dopóki ich nie potwierdzisz."
    if missing == ["drenowanie"]:
        return "Nie liczymy wody gruntowej, a drenowania nie uwzględniamy, dopóki go nie potwierdzisz."
    if missing == ["nawadnianie"]:
        return "Nie liczymy wody gruntowej, a nawadniania nie uwzględniamy, dopóki go nie potwierdzisz."
    return "Nie liczymy wody gruntowej."


SOIL_WORD = {"I": "bardzo lekka", "II": "lekka", "III": "średnia", "IV": "ciężka", "organic": "organiczna"}

# przyjazne nazwy źródeł i stanów do komunikatów dla rolnika (techniczne nazwy zostają w provenance)
SOURCE_PLAIN = {"Pogoda": "Pogoda", "Open-Meteo": "Pogoda", "IUNG": "Mapa gleby", "ISRIC": "Mapa właściwości gleby",
                "NMT": "Mapa wysokości terenu", "OpenStreetMap": "Mapa rowów i cieków"}
STATUS_PLAIN = {"timeout": "nie odpowiedziała na czas", "error": "była niedostępna",
                "empty": "nie miała danych dla tej działki", "partial": "odpowiedziała tylko częściowo"}


def failed_sources(ctx: ParcelContext) -> list:
    return [p for p in ctx.provenance if p.mode == "live" and p.status != "ok" and "Sentinel" not in p.source]


def titled(items: list[NotEvaluated]) -> list[NotEvaluated]:
    """Uzupełnia krótką nazwę rady (rules.yaml) w pozycjach „nie sprawdziliśmy”."""
    out = []
    for n in items:
        code = "IRR" if n.rule == "nawadnianie" else n.rule
        out.append(n.model_copy(update={"title": terrain_rules.RULES.get(code, {}).get("title")}))
    return out


def cause_c2(ctx: ParcelContext) -> Cause:
    iung = ctx.soil.iung if ctx.soil else None
    if not iung:
        return Cause(code="C2", dominant=False, confidence="nie_oceniono", why="Brak mapy kategorii gleb IUNG.")
    light = iung.shares.get("I", 0) + iung.shares.get("II", 0)
    pct = round(light * 100)
    evidence = [Evidence(field="soil.iung.shares.I+II", value=pct)]
    reason = "Kategoria gleby z mapy IUNG (5 m)."
    if light >= 0.5:
        return Cause(code="C2", dominant=True, confidence="srednia",
                     why=f"Lekka, piaszczysta gleba zajmuje {pct}% działki i szybko traci wodę.",
                     confidence_reason=reason, evidence=evidence)
    return Cause(code="C2", dominant=False, confidence="srednia",
                 why=f"Przeważa gleba {SOIL_WORD.get(iung.dominant, 'nierolnicza')}, która "
                     f"{'dobrze' if iung.dominant in ('III', 'IV', 'organic') else 'słabo'} zatrzymuje wodę.",
                 confidence_reason=reason, evidence=evidence)


def _plural(n: int) -> str:
    return "działanie" if n == 1 else "działania" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "działań"


def headline_technical(w: weather_rules.WeatherOutcome) -> str:
    """Wersja z liczbami (dla doradcy/mentora i jako wejście dla opisu LLM). Rolnik widzi plain.headline()."""
    parts = []
    k, f, s = w.kbw or {}, w.forecast or {}, w.susceptibility or {}
    if k.get("status") == "poza_okresem":
        parts.append("Teraz jest poza sezonem monitoringu suszy (21 III–30 IX).")
    elif k.get("status") == "zagrozenie":
        parts.append("Bilans opadu i parowania jest teraz poniżej progu suszy dla tej uprawy i gleby.")
    elif k.get("status") == "na_granicy":
        parts.append("Bilans opadu i parowania jest teraz blisko progu suszy.")
    elif k.get("status") == "brak_zagrozenia":
        parts.append("Bilans opadu i parowania jest teraz powyżej progu suszy.")
    if f.get("status") == "ok":
        parts.append(f"W wybranym okresie zapas wody w glebie spadnie poniżej bezpiecznego poziomu "
                     f"w {f['stress_chance']['n']} z 10 scenariuszy pogody.")
    elif f.get("status") == "poza_sezonem_uprawy":
        parts.append("Wybrany okres jest poza sezonem wzrostu tej uprawy. Wydłuż zakres dat do wiosny, "
                     "żeby zobaczyć, czy na początku sezonu zabraknie wody.")
    if s.get("n_ks") is not None:
        parts.append(f"W ostatnich latach niedobór wody w pełni wzrostu wystąpił w {s['n_ks']} z {s['of']} sezonów.")
    return " ".join(parts) or "Brak oceny stanu wody."


def build(ctx: ParcelContext, req: RecommendRequest) -> AnalysisResult:
    terr = terrain_rules.evaluate(ctx, req)
    c2 = cause_c2(ctx)
    w = weather_rules.evaluate(ctx, req, c2, terr.c3)
    c1, c4 = w.causes
    causes = [c1, c2, terr.c3, c4]

    recs = sorted(when_window.apply(terr.recommendations + w.recommendations, ctx, req),
                  key=lambda r: (GROUP_ORDER[r.group], terrain_rules.RULES[r.rule]["priority"]))
    shown, hidden = recs[:MAX_CARDS], recs[MAX_CARDS:]
    if any(r.group == "nawadnianie" for r in hidden):          # nawadnianie zawsze widoczne, ale ostatnie
        irr = next(r for r in hidden if r.group == "nawadnianie")
        hidden = [r for r in hidden if r is not irr] + [shown[-1]]
        shown = shown[:-1] + [irr]

    reasons = list(w.uncertainty)
    for p in failed_sources(ctx):
        name = next((v for k, v in SOURCE_PLAIN.items() if p.source.startswith(k)), None)
        if name:
            reasons.append(f"{name} {STATUS_PLAIN.get(p.status, 'była niedostępna')}.")
    # pewność całości z danych, nie z pojedynczych kart: KBW to przybliżenie SMSR (najwyżej „średnia”),
    # zapas wody w glebie z rozbieżnych map obniża ją do „niskiej”, podobnie brak ≥ 2 źródeł danych
    failed = failed_sources(ctx)
    overall = min_conf("srednia", w.taw_conf, "niska" if len(failed) >= 2 else "srednia")
    if len(reasons) < 2:
        reasons.append("Ocena opiera się na mapach i danych pogodowych, bez obserwacji z pola.")

    limitations = w.limitations + [water_limitation(req.answers), weather_limitation(ctx)] + BASE_LIMITATIONS
    for r in hidden:
        limitations.append(f"Pokazujemy najważniejsze działania; pominęliśmy: {r.title or r.message}.")

    return AnalysisResult(
        request=req, parcel={"id": ctx.parcel.id, "area_ha": ctx.parcel.area_ha},
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        partial=ctx.partial,
        state={"kbw": w.kbw, "soil_water": w.soil_water,
               "headline": plain.headline(w.kbw or {}, w.forecast or {}, w.susceptibility or {}, req.range.from_),
               "headline_key": plain.headline_parts(w.kbw or {}, w.forecast or {}, w.susceptibility or {}, req.range.from_)[0],
               "headline_more": plain.headline_parts(w.kbw or {}, w.forecast or {}, w.susceptibility or {}, req.range.from_)[1],
               "headline_technical": headline_technical(w)},
        forecast=w.forecast, susceptibility=w.susceptibility, causes=causes, recommendations=shown,
        not_evaluated=titled(terr.not_evaluated + w.not_evaluated),
        uncertainty={"overall": overall, "reasons": reasons[:4]}, provenance=ctx.provenance, limitations=limitations)
