"""Raport działki jako plik PDF (fpdf2), złożony z gotowego wyniku silnika (`AnalysisResult`).

Układ (decyzje 22.11): strona 1 to proste dane i opisy, bez wykresów – werdykt, 3 liczby, „Co się dzieje”,
„Dlaczego” (główne przyczyny) i „Co zrobić” (kiedy i jak, w kolejności retencja → agrotechnika → nawadnianie).
Od strony 2 szczegóły z wykresami (woda w glebie, brak wody w 10 latach, bilans opadu i parowania w sezonie)
i rozwinięciem problemów, pełny opis działań, odpowiedzi i ograniczenia. Źródeł danych w PDF nie ma – są na ekranie
i w eksporcie „Dane”.

Moduł niczego nie liczy od nowa: pokazuje teksty i liczby z `/api/recommend` („nigdy nie pokazujemy liczby, której
nie policzył silnik”). Werdykt, kafelki i „pierwsze działania” są lustrem `frontend/src/lib/present.js`
(`verdict`, `nextDays`, `topActions`) i `components/ResultView.jsx` (`WaterChart`, `sortedCauses`), żeby PDF mówił
tym samym językiem co ekran.

Czcionka: Atkinson Hyperlegible Next (SIL OFL 1.1, `app/data/fonts/`), ta sama co w interfejsie; plik zmienny
(oś wght), z którego fpdf2 wycina odmianę zwykłą (400) i pogrubioną (700). Osadzany jest tylko podzbiór znaków.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.models import AnalysisResult

FONT_FILE = Path(__file__).resolve().parent / "data" / "fonts" / "AtkinsonHyperlegibleNext-wght.ttf"
FONT = "Atkinson"

# --- etykiety: lustro frontend/src/lib/present.js i ResultView.jsx
CROP_NAME = {
    "zboza_ozime": "Zboża ozime", "zboza_jare": "Zboża jare", "kukurydza_ziarno": "Kukurydza na ziarno",
    "kukurydza_kiszonka": "Kukurydza na kiszonkę", "rzepak": "Rzepak", "ziemniak": "Ziemniaki",
    "burak_cukrowy": "Burak cukrowy", "uzytki_zielone": "Łąki i pastwiska",
}
GROUPS = [("retencja", "Zatrzymanie wody"), ("agrotechnika", "Zabieg w uprawie"), ("nawadnianie", "Nawadnianie")]
GROUP_NAME = dict(GROUPS)
CAUSE = {
    "C1": ("Mało deszczu, duże parowanie", "Deficyt opadów i wysokie parowanie"),
    "C2": ("Lekka gleba nie trzyma wody", "Mała pojemność wodna gleby"),
    "C3": ("Woda spływa z pola", "Nadmierny spływ (woda nie zostaje na polu)"),
    "C4": ("Uprawa jest wrażliwa", "Wrażliwość uprawy w okresie niedoboru"),
}
KBW_STATUS = {
    "zagrozenie": "zagrożenie suszą", "brak_zagrozenia": "brak zagrożenia", "na_granicy": "na granicy progu",
    "poza_okresem": "poza okresem monitoringu", "brak_progu": "brak progu", "brak_danych": "brak danych",
}
CONF = {"wysoka": "wysoka", "srednia": "średnia", "niska": "niska", "nie_oceniono": "nie oceniono"}
QUESTIONS = [
    ("ditch_with_weir", "Rów z zastawką przy działce"),
    ("drained", "Działka drenowana"),
    ("irrigation_water", "Woda do nawadniania"),
]
MONTHS = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień",
          "październik", "listopad", "grudzień"]
MONTHS_SHORT = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]

# kolory: tokens.css (--ink, --muted, --line, --water, --amber-mid, --red, --green) i LEVEL z present.js
INK, MUTED, LINE, GRID = (26, 31, 28), (86, 97, 90), (198, 207, 199), (227, 232, 227)
WATER, RED, GREEN, TILE = (31, 111, 168), (180, 46, 26), (47, 107, 59), (244, 246, 244)
# Wykresy (skill dataviz, walidator palety 22.11): woda #1F6FA8 i czerwień #B42E1A przechodzą wszystkie testy
# (CVD ΔE 21,4, kontrast ≥ 3:1). Szary „pozostałe lata” #808B83 ma kontrast ≥ 3:1 i ΔE 15,6 od wody; nie stoi z nią
# na jednym wykresie. Progi to linia odniesienia, nie seria: ciemny tusz #3A433D, przerywana, z podpisem przy linii
# (wcześniejszy bursztyn miał kontrast 2,3:1 – za mało dla grafiki wg WCAG 1.4.11).
GRAY, REF = (128, 139, 131), (58, 67, 61)
BAND_OPACITY = 0.12
# Etykiety werdyktu: tekst na tle ≥ 4,5:1 (wcześniej biały na zielonym 3,2:1 i na czerwonym 4,4:1)
LEVEL = {"alarm": ("Susza", RED, (255, 255, 255)), "uwaga": ("Uwaga", (227, 165, 28), INK),
         "ok": ("Bez suszy", GREEN, (255, 255, 255)), "info": ("Poza sezonem", (232, 197, 71), INK)}
# Skala pisma (pt): mniej rozmiarów, nic ważnego poniżej 9,5 pt – raport czytają też starsi rolnicy, często z wydruku
T_TICK, T_SMALL, T_BODY, T_H3, T_H2, T_TITLE = 8.5, 9.5, 10.5, 11.5, 14, 18


# --- formatowanie (jak fmt/formatDate we frontendzie: przecinek dziesiętny, data DD.MM.RRRR)

def num(v: Any, digits: int = 0) -> str:
    if v is None:
        return "—"
    s = f"{float(v):.{digits}f}"
    whole, _, frac = s.partition(".")
    sign = "−" if whole.startswith("-") and float(v) != 0 else ""
    whole = whole.lstrip("-")
    if len(whole) > 4:                                  # pl-PL grupuje dopiero od 10 000
        whole = f"{int(whole):,}".replace(",", " ")
    return sign + whole + ("," + frac if frac else "")


def interval(iv: dict | None, digits: int = 0, unit: str = "") -> str:
    """Mediana i przedział z silnika: „43 mm (7–80)”; bez przedziału, gdy granice są równe."""
    if not iv or iv.get("median") is None:
        return "—"
    u = f" {unit}" if unit else ""
    lo, hi = iv.get("low"), iv.get("high")
    rng = f" (od {num(lo, digits)} do {num(hi, digits)})" if lo is not None and hi is not None and lo != hi else ""
    return f"{num(iv['median'], digits)}{u}{rng}"


def _md(text: str) -> str:
    """Tekst bezpieczny dla markdownu fpdf2: rozbija znaczniki (**, __, --, ~~), żeby nie zmieniły kroju."""
    return (str(text).replace("**", "* *").replace("__", "_ _").replace("--", "–").replace("~~", "~ ~"))


def ddmmyyyy(v: Any) -> str:
    if not v:
        return "—"
    d = v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
    return d.strftime("%d.%m.%Y")


def local_time(iso: str | None) -> str:
    """Czas w strefie Europe/Warsaw; bez bazy stref czasowych (Windows bez tzdata) zostaje UTC z dopiskiem."""
    if not iso:
        return "—"
    t = datetime.fromisoformat(iso)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return t.astimezone(ZoneInfo("Europe/Warsaw")).strftime("%d.%m.%Y %H:%M")
    except Exception:  # noqa: BLE001 - brak bazy stref czasowych
        return t.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def sorted_causes(causes: list) -> list:
    """Jak sortedCauses w ResultView.jsx: najpierw główne, potem pewność, potem kod."""
    conf = {"wysoka": 0, "srednia": 1, "niska": 2, "nie_oceniono": 3}
    return sorted(causes, key=lambda c: (not c.dominant, conf.get(c.confidence, 9), c.code))


# --- logika prezentacji: lustro present.js

def verdict_level(res: AnalysisResult) -> str:
    st, f = res.state or {}, res.forecast or {}
    kbw, sw = (st.get("kbw") or {}).get("status"), st.get("soil_water") or {}
    stressed = bool(sw.get("below_raw"))
    pct, safe = (sw.get("pct_of_taw") or {}).get("median"), sw.get("safe_level_pct")
    severe = stressed and pct is not None and safe is not None and pct < safe / 2
    fc_risk = f.get("status") == "ok" and ((f.get("stress_chance") or {}).get("n") or 0) >= 5
    if kbw == "zagrozenie" or severe:
        return "alarm"
    if stressed or kbw == "na_granicy" or fc_risk:
        return "uwaga"
    if kbw == "poza_okresem" or f.get("status") == "poza_sezonem_uprawy":
        return "info"
    return "ok"


def next_days(res: AnalysisResult) -> str | None:
    sw, f = (res.state or {}).get("soil_water") or {}, res.forecast or {}
    if sw.get("below_raw"):
        return "Łatwo dostępna woda już się skończyła."
    if f.get("status") == "poza_sezonem_uprawy":
        return "Wybrany okres jest poza sezonem wzrostu tej uprawy."
    if f.get("status") == "ok" and (f.get("days_to_raw") or {}).get("median") is not None:
        return (f"Zapas może się skończyć za ok. {num(f['days_to_raw']['median'])} dni "
                f"(w {(f.get('stress_chance') or {}).get('n')} z 10 podobnych lat).")
    if f.get("status") == "ok":
        return "W wybranym okresie zapas wody powinien wystarczyć."
    return None


def top_actions(recs: list) -> list:
    """Pierwsze 3 działania; nawadnianie dopisane jako 4., jeśli nie zmieściło się w 3."""
    shown = list(recs[:3])
    irr = next((r for r in recs if r.group == "nawadnianie"), None)
    if irr is not None and irr not in shown:
        shown.append(irr)
    return shown


# --- dokument

class _Doc(FPDF):
    footer_text = ""

    def footer(self):
        self.set_y(-12)
        self.set_font(FONT, size=8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, self.footer_text, align="L")
        self.set_x(self.l_margin)
        self.cell(0, 5, f"strona {self.page_no()} z {{nb}}", align="R")


class _Writer:
    def __init__(self, title: str, footer: str):
        pdf = _Doc(format="A4")
        pdf.footer_text = footer
        pdf.set_margins(16, 14, 16)
        pdf.set_auto_page_break(True, margin=18)
        pdf.add_font(FONT, "", FONT_FILE, variations={"wght": 400})
        pdf.add_font(FONT, "B", FONT_FILE, variations={"wght": 700})
        pdf.set_title(title)
        pdf.set_author("Zatrzymaj wodę, chroń plony (prototyp KOWR, HackNation 2026)")
        pdf.set_creator("crop-protector")
        pdf.set_lang("pl")
        pdf.add_page()
        self.pdf = pdf
        self.cw = pdf.w - pdf.l_margin - pdf.r_margin      # szerokość treści

    def need(self, h: float):
        """Nowa strona, jeśli blok o wysokości h się nie zmieści."""
        if self.pdf.get_y() + h > self.pdf.h - self.pdf.b_margin:
            self.pdf.add_page()

    def h2(self, text: str, room: float = 30):
        p = self.pdf
        self.need(room)
        p.ln(3)
        p.set_font(FONT, "B", T_H2)
        p.set_text_color(*GREEN)
        p.multi_cell(0, 7.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
        p.set_draw_color(*LINE)
        p.set_line_width(0.2)
        p.line(p.l_margin, p.get_y(), p.w - p.r_margin, p.get_y())
        p.ln(2)

    def h3(self, text: str):
        p = self.pdf
        self.need(18)
        p.ln(1.2)
        p.set_font(FONT, "B", T_H3)
        p.set_text_color(*INK)
        p.multi_cell(0, 5.8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")

    def para(self, text: str | None, size: float = T_BODY, muted: bool = False, bold: bool = False):
        if not text:
            return
        p = self.pdf
        p.set_font(FONT, "B" if bold else "", size)
        p.set_text_color(*(MUTED if muted else INK))
        p.multi_cell(0, size * 0.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
        p.ln(0.8)

    def label_value(self, label: str, value: str | None, size: float = T_BODY - 0.5):
        """„Etykieta: wartość” w jednym akapicie: pogrubiona etykieta, kolejne wiersze wracają do marginesu
        (bez wcięcia wiszącego na szerokość etykiety, które przy długich tekstach dawało poszarpany prawy blok)."""
        if not value:
            return
        p = self.pdf
        p.set_text_color(*INK)
        p.set_font(FONT, "", size)
        p.multi_cell(0, size * 0.5, f"**{_md(label)}:** {_md(value)}", markdown=True,
                     new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
        p.ln(0.8)

    def note(self, text: str | None, size: float = T_SMALL):
        """Uwaga w jasnym polu (np. konsultacja, częściowe dane) – czytelna, ale nie konkuruje z treścią."""
        if not text:
            return
        p = self.pdf
        p.set_font(FONT, "", size)
        p.set_text_color(*INK)
        p.set_fill_color(*TILE)
        p.multi_cell(0, size * 0.5, text, fill=True, padding=(2, 3), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
        p.ln(1.5)

    def bullets(self, items: list[str], size: float = T_SMALL):
        p = self.pdf
        p.set_font(FONT, "", size)
        p.set_text_color(*INK)
        for it in items:
            p.cell(5, size * 0.5, "•")
            p.multi_cell(0, size * 0.5, it, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
            p.ln(0.3)

    def badge(self, text: str, fill, color):
        p = self.pdf
        p.set_font(FONT, "B", 10.5)
        w, h = p.get_string_width(text) + 8, 7
        x, y = p.l_margin, p.get_y()
        p.set_fill_color(*fill)
        p.rect(x, y, w, h, style="F", round_corners=True, corner_radius=1.8)
        p.set_text_color(*color)
        p.set_xy(x, y)
        p.cell(w, h, text, align="C")
        p.set_xy(p.l_margin, y + h + 2)

    def tiles(self, items: list[tuple[str, str, str]]):
        """Kafelki: (etykieta, duża wartość, dopisek)."""
        p = self.pdf
        gap, h = 4, 25
        w = (self.cw - gap * (len(items) - 1)) / len(items)
        y0 = p.get_y()
        for i, (label, value, sub) in enumerate(items):
            x = p.l_margin + i * (w + gap)
            p.set_fill_color(*TILE)
            p.rect(x, y0, w, h, style="F", round_corners=True, corner_radius=2)
            p.set_xy(x + 3.5, y0 + 3)
            p.set_font(FONT, "", T_SMALL)
            p.set_text_color(*MUTED)
            p.cell(w - 7, 4, label)
            p.set_xy(x + 3.5, y0 + 8.5)
            p.set_font(FONT, "B", 18 if len(value) <= 10 else 14)
            p.set_text_color(*INK)
            p.cell(w - 7, 8, value)
            p.set_xy(x + 3.5, y0 + 18)
            p.set_font(FONT, "", T_SMALL)
            p.set_text_color(*MUTED)
            p.multi_cell(w - 7, 4.2, sub, new_x=XPos.RIGHT, new_y=YPos.TOP, align="L")
        p.set_xy(p.l_margin, y0 + h + 3)

    def legend(self, items: list[tuple[str, tuple, str]], x: float, y: float):
        """Legenda w jednym wierszu: (rodzaj „line”|„dash”|„box”|„band”, kolor, opis). Tekst w kolorze tuszu,
        nigdy w kolorze serii (dataviz: „text never wears the data color”)."""
        p = self.pdf
        p.set_font(FONT, "", T_TICK)
        for kind, color, text in items:
            p.set_draw_color(*color)
            p.set_fill_color(*color)
            if kind == "box":
                p.rect(x, y - 1.6, 3.4, 3.2, style="F", round_corners=True, corner_radius=0.6)
            elif kind == "band":
                with p.local_context(fill_opacity=BAND_OPACITY * 2):
                    p.rect(x, y - 1.6, 6, 3.2, style="F")
            else:
                p.set_line_width(0.5 if kind == "line" else 0.4)
                if kind == "dash":
                    p.set_dash_pattern(dash=1.2, gap=0.8)
                p.line(x, y, x + 6, y)
                p.set_dash_pattern()
            p.set_text_color(*MUTED)
            p.text(x + 7.5, y + 1.1, text)
            x += 7.5 + p.get_string_width(text) + 6

    def output(self) -> bytes:
        return bytes(self.pdf.output())


# --- wykresy (wektorowo; zasady skilla dataviz: cienkie znaczniki, słupki ≤ 6,3 mm z zaokrąglonym końcem danych,
# linie 0,55 mm, siatka jako cienka ciągła linia, „okrągłe” wartości osi, podpisy oszczędnie, tekst w kolorze tuszu)

LINE_W, HAIR, BAR_MAX, BAR_R = 0.55, 0.2, 6.3, 1.0
GUTTER = 14            # prawy margines wykresu na podpis końca linii / progu – ten sam we wszystkich wykresach
DASH_EST, DASH_REF = (0.9, 0.9), (2.0, 1.1)   # estymacja (gęsta kreska) i próg (długa kreska) – różny wzór


def nice_step(span: float, target: int = 4) -> float:
    """Krok osi z ciągu 1, 2, 2,5, 5 × 10^k, tak żeby wyszło ok. `target` przedziałów."""
    import math
    raw = max(span, 1e-9) / target
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def _frame(w: _Writer, h: float, unit: str):
    """Rezerwuje miejsce na wykres i zwraca (x0, x1, y0, y1)."""
    p = w.pdf
    w.need(h + 9)
    x0, x1 = p.l_margin + 12, p.w - p.r_margin - GUTTER
    y0 = p.get_y() + 7.5
    y1 = y0 + h - 14
    p.set_font(FONT, "", T_TICK)
    p.set_text_color(*MUTED)
    p.text(p.l_margin, y0 - 3.4, unit)
    return x0, x1, y0, y1


def _axis_y(p: FPDF, x0, x1, ticks: list[tuple[float, str]], base_y: float | None = None):
    p.set_font(FONT, "", T_TICK)
    p.set_line_width(HAIR)
    for y, lab in ticks:
        p.set_draw_color(*GRID)
        p.line(x0, y, x1, y)
        p.set_text_color(*MUTED)
        p.text(x0 - 1.5 - p.get_string_width(lab), y + 1.1, lab)
    if base_y is not None:                                        # linia bazowa (zero) o stopień mocniejsza
        p.set_draw_color(*LINE)
        p.set_line_width(0.3)
        p.line(x0, base_y, x1, base_y)


def _bar(p: FPDF, x: float, y_val: float, y_base: float, width: float, color):
    """Słupek od linii bazowej: zaokrąglony koniec danych, prosty przy bazie (w górę albo w dół)."""
    top, bot = sorted((y_val, y_base))
    hgt = bot - top
    if hgt <= 0.05:
        return
    p.set_fill_color(*color)
    corners = ("TOP_LEFT", "TOP_RIGHT") if y_val < y_base else ("BOTTOM_LEFT", "BOTTOM_RIGHT")
    p.rect(x, top, width, hgt, style="F", round_corners=corners if hgt > BAR_R * 2 else False,
           corner_radius=min(BAR_R, hgt / 2))


def _dashed(p: FPDF, pattern, x_a, y_a, x_b, y_b, color, width=0.4):
    p.set_draw_color(*color)
    p.set_line_width(width)
    p.set_dash_pattern(dash=pattern[0], gap=pattern[1])
    p.line(x_a, y_a, x_b, y_b)
    p.set_dash_pattern()


def water_chart(w: _Writer, sw: dict, h: float = 64) -> bool:
    """Poziom wody w glebie (mediana i przedział przebiegów), część estymowana przerywana, próg RAW."""
    series, taw = sw.get("series") or [], (sw.get("taw_mm") or {}).get("high")
    if not series or not taw:
        return False
    p = w.pdf
    x0, x1, y0, y1 = _frame(w, h, "mm")
    step = nice_step(taw)
    top = -(-taw // step) * step
    n = len(series)
    X = lambda i: x0 + (0.5 if n == 1 else i / (n - 1)) * (x1 - x0)  # noqa: E731
    Y = lambda v: y1 - max(0.0, min(float(v), top)) / top * (y1 - y0)  # noqa: E731
    _axis_y(p, x0, x1, [(Y(v), num(v)) for v in _range(0, top, step)], base_y=Y(0))
    lv = [s["level_mm"]["median"] for s in series]
    if n > 1:
        band = [(X(i), Y(s["level_mm"]["low"])) for i, s in enumerate(series)]
        band += [(X(i), Y(series[i]["level_mm"]["high"])) for i in range(n - 1, -1, -1)]
        with p.local_context(fill_opacity=BAND_OPACITY):
            p.set_fill_color(*WATER)
            p.polygon(band, style="F")
        p.set_draw_color(*REF)
        p.set_line_width(0.4)
        p.set_dash_pattern(dash=DASH_REF[0], gap=DASH_REF[1])
        p.polyline([(X(i), Y(s["raw_mm"]["median"])) for i, s in enumerate(series)])
        p.set_dash_pattern()
        p.set_draw_color(*WATER)
        p.set_line_width(LINE_W)
        with p.local_context(stroke_cap_style="ROUND", stroke_join_style="ROUND"):
            for i in range(n - 1):
                if series[i].get("estimated") and series[i + 1].get("estimated"):
                    p.set_dash_pattern(dash=DASH_EST[0], gap=DASH_EST[1])
                p.line(X(i), Y(lv[i]), X(i + 1), Y(lv[i + 1]))
                p.set_dash_pattern()
    # punkt i wartość na końcu linii (jedyna liczba na wykresie; resztę niosą oś i tekst pod wykresem)
    ex, ey = X(n - 1), Y(lv[-1])
    p.set_fill_color(255, 255, 255)
    p.circle(ex, ey, 1.6, style="F")
    p.set_fill_color(*WATER)
    p.circle(ex, ey, 1.1, style="F")
    p.set_font(FONT, "B", T_TICK)
    p.set_text_color(*INK)
    p.text(ex + 2.2, ey + 1.1, f"{num(lv[-1])} mm")
    long = n - 1 > 120
    ticks = sorted({round(k * (n - 1) / (min(n, 5) - 1)) for k in range(min(n, 5))}) if n > 1 else [0]
    p.set_font(FONT, "", T_TICK)
    p.set_text_color(*MUTED)
    for k, i in enumerate(ticks):
        d = date.fromisoformat(series[i]["date"][:10])
        lab = f"{MONTHS_SHORT[d.month - 1]} {d.year}" if long else f"{d.day} {MONTHS_SHORT[d.month - 1]}"
        tw = p.get_string_width(lab)
        p.text(X(i) - (0 if k == 0 else tw if k == len(ticks) - 1 else tw / 2), y1 + 4.5, lab)
    est = [("dash", WATER, "estymacja z lat ubiegłych")] if any(s.get("estimated") for s in series) else []
    w.legend([("line", WATER, "woda w glebie"), *est, ("band", WATER, "przedział (zależy od gleby)"),
              ("dash", REF, "próg stresu (RAW)")], x0, y1 + 10)
    p.set_xy(p.l_margin, y1 + 13)
    return True


def years_chart(w: _Writer, sus: dict, h: float = 54) -> bool:
    """Dni stresu w kluczowym okresie w każdym z 10 lat; próg 10 dni (jak podatność w silniku).
    Wyróżnienie zamiast kolorów: lata z niedoborem czerwone z wartością, pozostałe szare bez liczby."""
    rows = [y for y in sus.get("per_year") or [] if y.get("year") is not None]
    if not rows:
        return False
    p = w.pdf
    x0, x1, y0, y1 = _frame(w, h, "dni")
    vmax = max([10, *[(y.get("stress_days_critical") or 0) for y in rows]])
    step = max(5, nice_step(vmax))
    top = -(-vmax // step) * step
    Y = lambda v: y1 - v / top * (y1 - y0)  # noqa: E731
    _axis_y(p, x0, x1, [(Y(v), num(v)) for v in _range(0, top, step)], base_y=Y(0))
    slot = (x1 - x0) / len(rows)
    bw = min(slot * 0.55, BAR_MAX)
    for i, y in enumerate(rows):
        v = y.get("stress_days_critical") or 0
        cx = x0 + (i + 0.5) * slot
        bad = v >= 10
        _bar(p, cx - bw / 2, Y(v), Y(0), bw, RED if bad else GRAY)
        if bad or v == 0:                                       # wartość nad latami z niedoborem; „0” odróżnia zero od braku danych
            p.set_font(FONT, "B" if bad else "", T_TICK)
            p.set_text_color(*(INK if bad else MUTED))
            p.text(cx - p.get_string_width(str(v)) / 2, Y(v) - 1.2, str(v))
        lab = str(y["year"])
        p.set_font(FONT, "B" if bad else "", T_TICK)
        p.set_text_color(*(INK if bad else MUTED))
        p.text(cx - p.get_string_width(lab) / 2, y1 + 4.5, lab)
    _dashed(p, DASH_REF, x0, Y(10), x1, Y(10), REF)
    p.set_font(FONT, "", T_TICK)
    p.set_text_color(*INK)
    p.text(x1 + 1.5, Y(10) + 1.1, "próg 10 dni")
    w.legend([("box", RED, "rok z niedoborem (co najmniej 10 dni)"), ("box", GRAY, "pozostałe lata")], x0, y1 + 10)
    p.set_xy(p.l_margin, y1 + 13)
    return True


def kbw_chart(w: _Writer, kbw: dict, h: float = 58) -> bool:
    """Bilans opadu i parowania w okresach 60-dniowych sezonu; próg suszy z rozporządzenia jako kreska nad słupkiem."""
    rows = [s for s in kbw.get("season") or [] if s.get("kbw_mm") is not None]
    if not rows:
        return False
    p = w.pdf
    x0, x1, y0, y1 = _frame(w, h, "mm")
    vals = [s["kbw_mm"] for s in rows] + [s["threshold_mm"] for s in rows if s.get("threshold_mm") is not None]
    step = nice_step(max(vals + [0.0]) - min(vals + [0.0]))
    lo = (min(vals + [0.0]) // step) * step
    hi = -(-max(vals + [0.0]) // step) * step
    if hi <= 0:
        hi = 0.0
    Y = lambda v: y0 + (hi - v) / (hi - lo) * (y1 - y0)  # noqa: E731
    _axis_y(p, x0, x1, [(Y(v), num(v)) for v in _range(lo, hi, step)], base_y=Y(0))
    slot = (x1 - x0) / len(rows)
    bw = min(slot * 0.6, BAR_MAX)
    any_bad = False
    for i, s in enumerate(rows):
        v, t = s["kbw_mm"], s.get("threshold_mm")
        cx = x0 + (i + 0.5) * slot
        bad = t is not None and v < t
        any_bad |= bad
        _bar(p, cx - bw / 2, Y(v), Y(0), bw, RED if bad else WATER)
        if t is not None:
            p.set_draw_color(*REF)                                # próg okresu: krótka pełna kreska nad słupkiem
            p.set_line_width(0.6)
            p.line(cx - slot * 0.4, Y(t), cx + slot * 0.4, Y(t))
        lab = str(s.get("label", "")).split("–")[0].strip()       # początek okresu: „21 III”
        p.set_font(FONT, "", T_TICK)
        p.set_text_color(*MUTED)
        p.text(cx - p.get_string_width(lab) / 2, y1 + 4.5, lab)
    w.legend([("box", WATER, "bilans w okresie"), *([("box", RED, "poniżej progu suszy")] if any_bad else []),
              ("line", REF, "próg suszy (Dz.U. 2019 poz. 739)")], x0, y1 + 10)
    p.set_xy(p.l_margin, y1 + 13)
    return True


def _range(lo: float, hi: float, step: float) -> list[float]:
    out, v = [], lo
    while v <= hi + step * 1e-6:
        out.append(round(v, 6))
        v += step
    return out


# --- treść

def _section(w: _Writer, text: str, room: float = 22):
    """Nagłówek sekcji na stronie 1 (mniejszy niż h2, bez linii)."""
    p = w.pdf
    w.need(room)
    p.ln(3)
    p.set_font(FONT, "B", T_H3 + 1)
    p.set_text_color(*GREEN)
    p.multi_cell(0, 6.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
    p.ln(0.5)


def _tiles(res: AnalysisResult) -> list[tuple[str, str, str]]:
    st, f, sus = res.state or {}, res.forecast or {}, res.susceptibility or {}
    series = (st.get("soil_water") or {}).get("series") or []
    if series:
        lv, rw = series[0]["level_mm"]["median"], series[0]["raw_mm"]["median"]
        rel = "poniżej progu stresu" if lv < rw else "powyżej progu stresu" if lv > rw else "na progu stresu"
        t1 = ("Woda w glebie na początku", f"{num(lv)} mm", f"{rel} ({num(rw)} mm)")
    else:
        t1 = ("Woda w glebie na początku", "—", "nie oceniono")
    if f.get("status") == "ok":
        t2 = ("W wybranym okresie", f"{(f.get('stress_chance') or {}).get('n')} z 10", "podobnych lat z brakiem wody")
    elif f.get("status") == "poza_sezonem_uprawy":
        t2 = ("W wybranym okresie", "poza sezonem", "uprawa nie rośnie w tym czasie")
    else:
        t2 = ("W wybranym okresie", "—", "nie oceniono")
    t3 = (("Ostatnie 10 lat", f"{sus.get('n_ks')} z {sus.get('of')}", "lat z niedoborem wody")
          if sus.get("of") else ("Ostatnie 10 lat", "—", "nie oceniono"))
    return [t1, t2, t3]


def _summary_page(w: _Writer, res: AnalysisResult, par: dict, crop: str, period: str):
    """Strona 1: proste dane i opisy, bez wykresów – co się dzieje, dlaczego i co zrobić."""
    p, st = w.pdf, res.state or {}

    p.set_font(FONT, "B", T_SMALL)
    p.set_text_color(*GREEN)
    p.cell(0, 5, "Zatrzymaj wodę – raport działki", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
    place = ", ".join(x for x in [par.get("gmina"), f"obręb {par['obreb']}" if par.get("obreb") else None] if x)
    area = f"{num(par.get('area_ha'), 2)} ha" if par.get("area_ha") else ""
    w.para(" · ".join(x for x in [f"Działka {par.get('id', '')}", place, area] if x), size=T_H2 - 1, bold=True)
    w.para(f"{crop} · {period} · raport z {local_time(res.generated_at)}", size=T_SMALL, muted=True)
    p.ln(1.5)

    label, fill, color = LEVEL[verdict_level(res)]
    w.badge(label, fill, color)
    title = st.get("headline_key") or st.get("headline") or "Brak oceny dla tego okresu."
    w.para(title, size=T_TITLE - 2, bold=True)
    p.ln(1)
    w.tiles(_tiles(res))

    # co się dzieje: zdania silnika (headline_more) i „najbliższe dni”, bez powtórzeń werdyktu
    _section(w, "Co się dzieje")
    lines = [x for x in (st.get("headline_more") or []) if x and x not in title]
    nd = next_days(res)
    if nd and nd != title and nd not in lines:
        lines.insert(0, nd)
    w.para(" ".join(lines) or title)
    if res.partial:
        w.note("Część danych była niedostępna, więc wynik ma niższą pewność.")

    dom = [c for c in sorted_causes(res.causes) if c.dominant]
    if dom:
        _section(w, "Dlaczego")
        for c in dom:
            w.label_value(CAUSE.get(c.code, (c.code,))[0], c.why)

    _section(w, "Co zrobić – w tej kolejności", room=30)
    top = top_actions(res.recommendations)
    if not top:
        w.para("Na tej działce nie znaleźliśmy działań do polecenia.")
    for i, r in enumerate(top, 1):
        w.need(20)
        y = p.get_y()
        p.set_fill_color(*GREEN)
        p.circle(p.l_margin + 2.6, y + 2.8, 2.6, style="F")
        p.set_font(FONT, "B", 9)
        p.set_text_color(255, 255, 255)
        p.set_xy(p.l_margin, y + 0.3)
        p.cell(5.2, 5, str(i), align="C")
        p.set_xy(p.l_margin + 8, y)
        p.set_font(FONT, "B", T_H3)
        p.set_text_color(*INK)
        p.multi_cell(0, 5.6, r.title or r.message, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
        for lab, val in (("Kiedy", r.when_text or r.when_short), ("Jak", r.message if r.title else None)):
            if val:
                p.set_x(p.l_margin + 8)
                p.set_text_color(*INK)
                p.set_font(FONT, "", T_BODY - 0.5)
                p.multi_cell(0, 5, f"**{lab}:** {_md(val)}", markdown=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT,
                             align="L")
        if r.conditional:
            p.set_x(p.l_margin + 8)
            p.set_font(FONT, "", T_SMALL)
            p.set_text_color(*MUTED)
            p.multi_cell(0, 4.8, "Rada warunkowa: zależy od odpowiedzi, której jeszcze nie znamy.",
                         new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
        p.ln(2.5)
    more = len(res.recommendations) - len(top)
    if more > 0:
        w.para(f"Kolejne działania ({more}) są w szczegółach.", size=T_SMALL, muted=True)
    if any(r.consult_note for r in top):
        w.note("Przed budową urządzeń wodnych albo poborem wody skonsultuj się z doradcą ODR, spółką wodną "
               "albo Wodami Polskimi.")

    p.ln(1)
    unc = (res.uncertainty or {}).get("overall")
    tail = f"Pewność wyniku: {CONF.get(unc, unc)}. " if unc else ""
    w.para(tail + "Wykresy i wyjaśnienie każdego problemu są na kolejnych stronach.", size=T_SMALL, muted=True)


def _details(w: _Writer, res: AnalysisResult):
    """Od strony 2: wykresy i rozwinięcie problemów, działań i liczb."""
    p, st, f, sus = w.pdf, res.state or {}, res.forecast or {}, res.susceptibility or {}
    sw, k = st.get("soil_water") or {}, st.get("kbw") or {}
    p.add_page()
    p.set_font(FONT, "B", T_TITLE)
    p.set_text_color(*GREEN)
    p.cell(0, 9, "Szczegóły", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")

    # 1. woda w glebie
    if sw.get("series"):
        w.h2("Woda w glebie w wybranym okresie", room=96)
        w.para("Ile wody jest w strefie korzeni dzień po dniu. Gdy niebieska linia zejdzie poniżej przerywanej "
               "linii progu, roślinom zaczyna brakować wody.", size=T_SMALL, muted=True)
        water_chart(w, sw)
    rows = []
    if sw.get("phase_label"):
        rows.append(("Etap uprawy", sw["phase_label"]))
    if sw.get("taw_mm"):
        rows.append(("Ile wody gleba może zatrzymać dla korzeni", interval(sw["taw_mm"], 0, "mm")))
    if f.get("status") == "ok":
        if (f.get("days_to_raw") or {}).get("n"):
            rows.append(("Zapas wody może się skończyć za", interval(f["days_to_raw"], 0, "dni")))
        if (f.get("deficit_mm") or {}).get("high"):
            rows.append(("Ile wody może zabraknąć", interval(f["deficit_mm"], 0, "mm")))
        if (f.get("deficit_m3") or {}).get("high"):
            rows.append(("Na całą działkę", interval(f["deficit_m3"], 0, "m³")))
    for label, value in rows:
        w.label_value(label, value)

    # 2. ostatnie 10 lat
    if sus.get("per_year"):
        w.h2("Brak wody w ostatnich 10 latach", room=84)
        w.para("Dni, w których roślinom brakowało wody w kluczowym okresie wzrostu, w każdym roku.", size=T_SMALL, muted=True)
        years_chart(w, sus)
        months = [MONTHS[int(m) - 1] for m in sus.get("risk_months") or [] if str(m).isdigit() and 1 <= int(m) <= 12]
        if months:
            w.label_value("Miesiące największego ryzyka", ", ".join(months))

    # 3. bilans opadu i parowania
    if k.get("season"):
        start = ((k.get("period") or {}).get("start") or "")[:4]
        w.h2(f"Bilans opadu i parowania w sezonie {start}".strip(), room=90)
        w.para("Opad minus parowanie w okresach 60-dniowych przesuwanych co 10 dni (od 21 marca do 30 września); pod "
               "słupkiem data początku okresu. Słupek poniżej ciemnej kreski oznacza suszę według progu z rozporządzenia.", size=T_SMALL, muted=True)
        kbw_chart(w, k)
    if k.get("kbw_mm") is not None:
        lab = f" ({k['period']['label']})" if (k.get("period") or {}).get("label") else ""
        thr = f", próg suszy {num(k['threshold_mm'], 1)} mm" if k.get("threshold_mm") is not None else ""
        stat = KBW_STATUS.get(k.get("period_status") or k.get("status"), "")
        w.label_value(f"Ostatni okres{lab}", f"{num(k['kbw_mm'], 1)} mm{thr}" + (f" – {stat}" if stat else ""))
    if k.get("note"):
        w.para(k["note"], size=T_SMALL, muted=True)

    # 4. problemy – rozwinięcie przyczyn
    if res.causes:
        w.h2("Problemy na tej działce")
        for c in sorted_causes(res.causes):
            w.h3(f"{CAUSE.get(c.code, ('', c.code))[1]}{' (główna przyczyna)' if c.dominant else ''}")
            w.para(c.why)
            w.label_value("Pewność", CONF.get(c.confidence, c.confidence)
                          + (f" – {c.confidence_reason}" if c.confidence_reason else ""))

    # 5. działania – pełny opis
    w.h2("Działania – pełny opis")
    if not res.recommendations:
        w.para("Na tej działce nie znaleźliśmy działań do polecenia.")
    no = 0
    for key, name in GROUPS:
        recs = [r for r in res.recommendations if r.group == key]
        if not recs:
            continue
        w.need(25)
        w.para(name, size=T_H3 + 1, bold=True)
        for r in recs:
            no += 1
            w.h3(f"{no}. {r.title or r.message}")
            w.label_value("Kiedy", r.when_text or r.when_short)
            w.label_value("Co zrobić", r.message if r.title else None)
            w.label_value("Dlaczego tu", r.why)
            w.label_value("Efekt", (r.effect or {}).get("text"))
            w.label_value("Pewność", CONF.get(r.confidence, r.confidence) + (" (rada warunkowa)" if r.conditional else "")
                          + (f" – {r.confidence_reason}" if r.confidence_reason else ""))
            w.label_value("Uwaga", (r.consult_note or "").strip() or None)
    if res.not_evaluated:
        w.para("Nie oceniono:", bold=True)
        w.bullets([f"{n.title or n.rule} – {n.reason}" for n in res.not_evaluated])

    w.h2("Twoje odpowiedzi", room=25)
    ans = res.request.answers.model_dump()
    w.para(" · ".join(f"{t}: {'tak' if ans.get(q) is True else 'nie' if ans.get(q) is False else 'nie wiem'}"
                      for q, t in QUESTIONS))
    if res.request.sowing_date:
        w.label_value("Data siewu", ddmmyyyy(res.request.sowing_date))

    if res.limitations:
        w.h2("Ograniczenia", room=25)
        w.bullets(res.limitations)


def render(result: AnalysisResult, parcel: dict | None = None) -> bytes:
    """Zwraca bajty pliku PDF z raportem działki."""
    req, par = result.request, {**(result.parcel or {}), **(parcel or {})}
    pid = par.get("id", "")
    crop = CROP_NAME.get(req.crop, req.crop)
    period = f"{ddmmyyyy(req.range.from_)} – {ddmmyyyy(req.range.to)}"
    w = _Writer(title=f"Raport działki {pid}: {crop}, {period}",
                footer=f"Zatrzymaj wodę – działka {pid}, raport z {local_time(result.generated_at)}")
    _summary_page(w, result, par, crop, period)
    _details(w, result)
    return w.output()
