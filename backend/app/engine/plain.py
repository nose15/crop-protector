"""Opisy wyniku prostym językiem dla rolnika (bez „scenariuszy”, „KBW”, „n z 10”, mm i procentów).
Liczby zostają w polach wyniku i w rozwijanych szczegółach; tutaj tylko słowa i terminy w kalendarzu."""

from __future__ import annotations

from datetime import date, timedelta

MONTH_GEN = ["", "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
             "października", "listopada", "grudnia"]
MONTH_LOC = ["", "styczniu", "lutym", "marcu", "kwietniu", "maju", "czerwcu", "lipcu", "sierpniu", "wrześniu",
             "październiku", "listopadzie", "grudniu"]


def when(d: date) -> str:
    """'na początku maja' / 'w połowie maja' / 'pod koniec maja'."""
    part = "na początku" if d.day <= 10 else "w połowie" if d.day <= 20 else "pod koniec"
    return f"{part} {MONTH_GEN[d.month]}"


def since(d: date) -> str:
    """'od początku maja' / 'od połowy maja' / 'od końca maja'."""
    part = "od początku" if d.day <= 10 else "od połowy" if d.day <= 20 else "od końca"
    return f"{part} {MONTH_GEN[d.month]}"


def chance_short(n: int) -> str:
    if n == 0:
        return "wody w glebie powinno wystarczyć"
    if n <= 3:
        return "wody raczej wystarczy, chyba że rok będzie wyjątkowo suchy"
    if n <= 6:
        return "wody może zabraknąć"
    if n <= 9:
        return "wody prawdopodobnie zabraknie"
    return "wody niemal na pewno zabraknie"


def months(codes: list[str]) -> str:
    names = [MONTH_LOC[int(m)] for m in codes]
    if not names:
        return ""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " i " + names[-1]


MONTH_NOM = ["", "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień",
             "październik", "listopad", "grudzień"]


def month_range(codes: list[str]) -> str:
    """['05','06','07'] -> 'maj–lipiec'; jeden miesiąc -> 'maj'."""
    if not codes:
        return ""
    a, b = int(codes[0]), int(codes[-1])
    return MONTH_NOM[a] if a == b else f"{MONTH_NOM[a]}–{MONTH_NOM[b]}"


def chance(n: int) -> str:
    """Szansa niedoboru w wybranym okresie (n z 10 scenariuszy) słowami."""
    if n == 0:
        return "wody w glebie powinno wystarczyć"
    if n <= 3:
        return "wody raczej wystarczy, ale w suchszym roku może jej zabraknąć"
    if n <= 6:
        return "wody może zabraknąć: w podobnych latach zdarzało się to mniej więcej co drugi raz"
    if n <= 9:
        return "wody prawdopodobnie zabraknie"
    return "wody niemal na pewno zabraknie"


def frequency(n: int, of: int) -> str:
    """Jak często zdarzały się niedobory w ostatnich latach (n z of sezonów) słowami."""
    share = n / of if of else 0
    if share <= 0.2:
        return "zdarzają się rzadko"
    if share <= 0.5:
        return "zdarzają się co kilka lat"
    if share <= 0.8:
        return "zdarzają się w większości lat"
    return "zdarzają się prawie co roku"


def rain_now(status: str | None) -> str | None:
    return {
        "zagrozenie": "W ostatnich tygodniach padało za mało jak na tę uprawę i glebę.",
        "na_granicy": "W ostatnich tygodniach padało niewiele, na granicy suszy.",
        "brak_zagrozenia": "W ostatnich tygodniach padało wystarczająco.",
        "poza_okresem": "Teraz jest poza sezonem wzrostu, susza rolnicza nie grozi.",
    }.get(status or "")


def headline(kbw: dict, fc: dict, sus: dict, d: date) -> str:
    key, more = headline_parts(kbw, fc, sus, d)
    return " ".join([key] + more) if key else "Brak oceny stanu wody."


def headline_parts(kbw: dict, fc: dict, sus: dict, d: date) -> tuple[str | None, list[str]]:
    """(zdanie główne, pozostałe zdania). Główne: prognoza na wybrany okres, a gdy jej brak – pierwsze dostępne."""
    parts = []
    r = rain_now(kbw.get("status"))
    if r:
        parts.append(r)
    if fc.get("status") == "ok":
        n = fc["stress_chance"]["n"]
        s = f"W wybranym okresie {chance_short(n)}"
        dtr = fc.get("days_to_raw") or {}
        if n >= 4 and dtr.get("median") is not None:
            s += f", najpewniej {since(d + timedelta(days=int(dtr['median'])))}"
        parts.append(s + ".")
    elif fc.get("status") == "poza_sezonem_uprawy":
        parts.append("Wybrany okres wypada poza sezonem wzrostu tej uprawy. Wydłuż zakres dat do wiosny, "
                     "żeby zobaczyć, czy na początku sezonu zabraknie wody.")
    if sus.get("n_ks") is not None:
        s = f"Na tym polu niedobory wody w czasie wzrostu {frequency(sus['n_ks'], sus['of'])}"
        if sus.get("risk_months") and sus["n_ks"] / max(sus["of"], 1) > 0.2:
            s += f", najczęściej w {months(sus['risk_months'])}"
        parts.append(s + ".")
    if not parts:
        return None, []
    key_i = next((i for i, p in enumerate(parts) if p.startswith("W wybranym okresie") or p.startswith("Wybrany okres")), 0)
    return parts[key_i], [p for i, p in enumerate(parts) if i != key_i]
