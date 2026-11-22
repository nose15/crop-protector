"""Reguły terenowe (retencja i agrotechnika zależne od rzeźby): R11, R6, R3, R2, R14, R1 oraz przyczyna C3.

Wejście: ParcelContext (teren z NMT, gleba IUNG, cieki OSM) i RecommendRequest (uprawa, odpowiedzi rolnika).
Każda reguła działa tylko na policzonym wskaźniku (G1); brak danych trafia do `not_evaluated` (G3);
inwestycje dostają dopisek o konsultacji (G4). Teksty i progi: app/data/rules.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.engine.confidence import min_conf
from app.models import Cause, Evidence, NotEvaluated, ParcelContext, Recommendation, RecommendRequest

CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / "data" / "rules.yaml").read_text(encoding="utf-8"))
RULES = CFG["rules"]
CROP_NAMES = {"zboza_ozime": "zboża ozime", "zboza_jare": "zboża jare", "kukurydza_ziarno": "kukurydza na ziarno",
              "kukurydza_kiszonka": "kukurydza na kiszonkę", "rzepak": "rzepak", "ziemniak": "ziemniak",
              "burak_cukrowy": "burak cukrowy", "uzytki_zielone": "użytki zielone"}


def pl(**values) -> dict:
    """Liczby do tekstu po polsku: przecinek dziesiętny (0,98 m, 2,1 ha). Wartości w `evidence` zostają liczbami."""
    return {k: (f"{v:g}".replace(".", ",").replace("-", "−") if isinstance(v, float) else v) for k, v in values.items()}


def th(name: str) -> float:
    return float(CFG["thresholds"][name]["value"])


@dataclass
class TerrainOutcome:
    recommendations: list[Recommendation] = field(default_factory=list)
    not_evaluated: list[NotEvaluated] = field(default_factory=list)
    c3: Cause | None = None


def _rec(code: str, *, why: str, confidence: str, evidence: list[tuple[str, object]], conditional: bool = False,
         confidence_reason: str | None = None,
         marker: dict | None = None, question: bool = False, message: str | None = None) -> Recommendation:
    r = RULES[code]
    site_q = {"id": marker["id"], "text": r["question"]} if question and marker and r.get("question") else None
    return Recommendation(
        id=code.lower(), rule=code, group=r["group"], lead_time=r.get("lead_time"), when_text=r.get("when_text"),
        when_short=r.get("when_short"), title=r.get("title"),
        message=message or r["message"], why=why, effect={"text": r["effect"]}, conditional=conditional,
        confidence=confidence, confidence_reason=confidence_reason,
        evidence=[Evidence(field=f, value=v) for f, v in evidence], marker=marker,
        site_question=site_q, sources=r.get("sources", []),
        consult_note=CFG["consult_note"] if r.get("investment") else None)


def _soil_is_light(ctx: ParcelContext) -> bool | None:
    iung = ctx.soil.iung if ctx.soil else None
    if not iung or not iung.dominant:
        return None
    return iung.dominant in ("I", "II")


def evaluate(ctx: ParcelContext, req: RecommendRequest) -> TerrainOutcome:
    out = TerrainOutcome()
    sites = req.answers.sites
    t = ctx.terrain
    if t is None:
        out.c3 = Cause(code="C3", dominant=False, confidence="nie_oceniono", why="Model terenu niedostępny.")
        for code in ("R11", "R6", "R3", "R2", "R1"):
            if code == "R11" and req.answers.ditch_with_weir:
                continue                                    # R11 może wynikać z odpowiedzi rolnika
            out.not_evaluated.append(NotEvaluated(rule=code, reason="nie udało się pobrać mapy wysokości terenu"))
    else:
        _terrain_rules(ctx, req, t, sites, out)
    _r11_without_dem(ctx, req, out)
    _r14(ctx, out)
    return out


def _terrain_rules(ctx, req, t, sites, out: TerrainOutcome) -> None:
    s = t["stats"]
    p90 = s["slope_p90_deg"]
    light = _soil_is_light(ctx)
    steep_th = th("steep_p90_deg_light_soil") if light else th("steep_p90_deg_other_soil")
    soil_conf = "wysoka" if light is not None else "niska"   # bez gleby nie znamy właściwego progu stromości
    steep = p90 > steep_th
    outlets = t.get("outlets") or []
    main = outlets[0] if outlets else None
    concentrated = bool(main and main["catchment_ha"] >= th("concentrated_flow_min_ha") and not s.get("flat_terrain"))
    flow_conf = "srednia" if p90 >= th("flow_medium_conf_p90_deg") else "niska"

    # C3: spływ z pola
    if steep or concentrated:
        v = pl(p90=p90, ha=main["catchment_ha"] if main else 0.0)
        why = (f"Pole jest strome (nachylenie do {v['p90']}°), więc woda szybko z niego spływa." if steep else
               f"Woda z ok. {v['ha']} ha pola zbiera się w jeden strumień i odpływa z działki.")
        out.c3 = Cause(code="C3", dominant=True, confidence=min_conf("srednia", flow_conf if not steep else "srednia"),
                       why=why)
    else:
        out.c3 = Cause(code="C3", dominant=False, confidence="srednia",
                       why="Teren jest łagodny i woda nie spływa z pola jednym strumieniem.")

    # R11: rów wykryty w NMT
    deps = t.get("depressions") or []
    ditches = [d for d in deps if d.get("kind") == "ditch" and sites.get(d.get("id")) is not False]
    if ditches:
        d = ditches[0]
        confirmed = sites.get(d["id"]) is True or req.answers.ditch_with_weir is True
        n_out = d.get("outlets_in", 0)                      # odpływy z pola, których woda trafia do tego rowu
        r = RULES["R11"]
        why = r["why"].format(**pl(length_m=d["length_m"], max_depth_m=d["max_depth_m"],
                                   distance="częściowo na działce" if d["inside_parcel_pct"] > 0 else "przy granicy działki"))
        if n_out:
            why += r["why_outlets"].format(n_outlets=n_out)
        if req.answers.ditch_with_weir is True:
            why += " " + r["why_farmer"]
        out.recommendations.append(_rec(
            "R11", why=why, confidence="wysoka" if confirmed else "srednia", conditional=not confirmed,
            confidence_reason="Potwierdzone przez rolnika." if confirmed else
            "Rów rozpoznany po kształcie obniżenia w modelu terenu (heurystyka). Potwierdź na mapie, żeby podnieść pewność.",
            evidence=[(f"terrain.depressions[{d['id']}].kind", "ditch"),
                      (f"terrain.depressions[{d['id']}].width_m", d["width_m"]),
                      (f"terrain.depressions[{d['id']}].length_m", d["length_m"])],
            marker={"id": d["id"], "at": d["at"]}, question=not confirmed,
            message=r["message_confirmed_weir"] if req.answers.ditch_with_weir else None))

    # R6: miejsce na oczko
    ponds = [d for d in deps if d.get("kind") == "pond" and sites.get(d.get("id")) is not False]
    if ponds:
        d = ponds[0]
        confirmed = sites.get(d["id"]) is True
        out.recommendations.append(_rec(
            "R6", why=RULES["R6"]["why"].format(**pl(**d)), confidence="wysoka" if confirmed else "srednia",
            confidence_reason="Potwierdzone przez rolnika." if confirmed else
            "Zagłębienie z modelu terenu 1 m; nie wiemy, czy woda faktycznie tam stoi.",
            conditional=not confirmed, marker={"id": d["id"], "at": d["at"]}, question=not confirmed,
            evidence=[(f"terrain.depressions[{d['id']}].max_depth_m", d["max_depth_m"]),
                      (f"terrain.depressions[{d['id']}].volume_m3", d["volume_m3"])]))

    # R2: stromo
    if steep:
        out.recommendations.append(_rec(
            "R2", why=RULES["R2"]["why"].format(**pl(slope_p90_deg=p90, threshold_deg=steep_th)),
            confidence=min_conf("srednia", soil_conf), evidence=[("terrain.stats.slope_p90_deg", p90)],
            confidence_reason="Nachylenie z modelu terenu 1 m; próg stromości zależy od kategorii gleby"
                              + ("." if soil_conf != "niska" else ", której nie znamy.")))
    # R3: skupiony spływ na łagodniejszym terenie
    elif concentrated:
        out.recommendations.append(_rec(
            "R3", why=RULES["R3"]["why"].format(**pl(catchment_ha=main["catchment_ha"],
                                                       terrain_word="teren prawie płaski" if p90 < 3 else "teren nachylony")),
            confidence=flow_conf, marker={"id": "outlet0", "at": main["at"]},
            confidence_reason=(f"Teren prawie płaski (nachylenie do {pl(p=p90)['p']}°): kierunek spływu wyznacza głównie "
                               "mikrorzeźba, np. koleiny." if flow_conf == "niska" else
                               "Linia spływu z modelu terenu 1 m przy wyraźnym nachyleniu."),
            evidence=[("terrain.outlets[0].catchment_ha", main["catchment_ha"]), ("terrain.stats.slope_p90_deg", p90)]))

    # R1: siew w poprzek stoku dla upraw rzędowych
    if p90 > th("contour_sowing_p90_deg") and req.crop in CFG["row_crops"]:
        out.recommendations.append(_rec(
            "R1", why=RULES["R1"]["why"].format(**pl(slope_p90_deg=p90, crop_name=CROP_NAMES[req.crop])),
            confidence="srednia", evidence=[("terrain.stats.slope_p90_deg", p90), ("request.crop", req.crop)],
            confidence_reason="Nachylenie z modelu terenu; nie znamy kierunku obecnej uprawy."))


def _r11_without_dem(ctx: ParcelContext, req: RecommendRequest, out: TerrainOutcome) -> None:
    """R11 z OSM albo z odpowiedzi rolnika, gdy NMT nie wykrył rowu."""
    if any(r.rule == "R11" for r in out.recommendations):
        return
    r = RULES["R11"]
    w = ctx.water
    if w and w.nearest_ditch_m is not None and w.nearest_ditch_m <= th("ditch_osm_max_m"):
        confirmed = req.answers.ditch_with_weir is True
        out.recommendations.append(_rec(
            "R11", why=r["why_osm"].format(distance_m=round(w.nearest_ditch_m)),
            confidence="wysoka" if confirmed else "srednia", conditional=False,
            confidence_reason="Rów z mapy OpenStreetMap" + (" i potwierdzony przez rolnika." if confirmed else "; mapa bywa niekompletna."),
            evidence=[("water.nearest_ditch_m", w.nearest_ditch_m)],
            message=r["message_confirmed_weir"] if confirmed else None))
    elif req.answers.ditch_with_weir is True:
        out.recommendations.append(_rec(
            "R11", why=r["why_farmer"], confidence="srednia",
            confidence_reason="Tylko odpowiedź rolnika; nie widać rowu w danych.",
            evidence=[("request.answers.ditch_with_weir", True)], message=r["message_confirmed_weir"]))


def _r14(ctx: ParcelContext, out: TerrainOutcome) -> None:
    w = ctx.water
    if w is None:
        out.not_evaluated.append(NotEvaluated(rule="R14", reason="nie udało się pobrać mapy rowów i cieków"))
        return
    if w.nearest_watercourse_m is not None and w.nearest_watercourse_m <= th("watercourse_buffer_max_m"):
        out.recommendations.append(_rec(
            "R14", why=RULES["R14"]["why"].format(distance_m=round(w.nearest_watercourse_m)), confidence="srednia",
            confidence_reason="Odległość cieku z mapy OpenStreetMap.",
            evidence=[("water.nearest_watercourse_m", w.nearest_watercourse_m)]))
