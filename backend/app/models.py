"""Kontrakty API (lustro: frontend/src/api/shapes.js). Zgodne z silnik.md, wersja 2.

Zasada: każde pole danych może być None; powód braku jest wtedy w `provenance`.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["ok", "partial", "timeout", "error", "empty"]
Confidence = Literal["wysoka", "srednia", "niska", "nie_oceniono"]
CropCode = Literal["zboza_ozime", "zboza_jare", "kukurydza_ziarno", "kukurydza_kiszonka",
                   "rzepak", "ziemniak", "burak_cukrowy", "uzytki_zielone"]


class Provenance(BaseModel):
    source: str
    status: Status
    mode: Literal["live", "constant", "fallback", "cache"] = "live"
    latency_ms: int = 0
    retrieved_at: str
    licence: str
    data_until: date | None = None
    note: str | None = None


# ------------------------------------------------------------------ krok 1

class Parcel(BaseModel):
    id: str
    teryt7: str | None = None
    voivodeship: str | None = None
    county: str | None = None
    gmina: str | None = None
    obreb: str | None = None
    number: str | None = None
    rings: list[list[list[float]]]          # [[[lon, lat], ...], ...], EPSG:4326
    centroid: list[float]                   # [lon, lat]
    area_ha: float
    found_by: str | None = None             # "numer" | "obreb_numer" | "adres" | "punkt" | "zapis"
    address: str | None = None              # adres, po którym znaleziono działkę (gdy found_by = "adres")


# ------------------------------------------------------------------ krok 3

class MeteoDay(BaseModel):
    date: date
    p_mm: float | None
    et0_mm: float | None
    tmax: float | None
    tmin: float | None


class Meteo(BaseModel):
    daily: list[MeteoDay]                   # archiwum (+ dni dociągnięte z prognozy do as_of)
    forecast: list[MeteoDay] = []           # dni po as_of (do 16)
    resolution: str
    history_source: str | None = None       # "nasa_power" | "open_meteo" – skąd historia (decyzja 22.11.2026)
    notes: list[str] = []                   # co wzięto z zapasu, czego brakuje (trafia do provenance.note)
    complete: bool = True                   # False: potrzebna prognoza/ostatnie dni, ale Open-Meteo nie odpowiedziało


class Quantiles(BaseModel):
    q05: float | None = None
    mean: float | None = None
    q95: float | None = None


class IungSoil(BaseModel):
    shares: dict[str, float]                # I, II, III, IV, organic, non_agri, unclassified
    dominant: str | None
    n_cells: int


class SoilGrids(BaseModel):
    wv0033: Quantiles | None = None         # obj. % wody przy -33 kPa (pojemność polowa), 0–100 cm
    wv1500: Quantiles | None = None         # obj. % wody przy -1500 kPa (punkt więdnięcia)
    sand_pct: float | None = None
    clay_pct: float | None = None
    soc_gkg: float | None = None


class Soil(BaseModel):
    iung: IungSoil | None = None
    soilgrids: SoilGrids | None = None


class Water(BaseModel):
    nearest_watercourse_m: float | None = None
    nearest_ditch_m: float | None = None
    geojson: dict[str, Any] | None = None


class ParcelContext(BaseModel):
    schema_version: int = 2
    as_of: date
    partial: bool = False
    parcel: Parcel
    meteo: Meteo | None = None
    soil: Soil = Field(default_factory=Soil)
    terrain: dict[str, Any] | None = None   # wynik terrain.analyze(): stats, depressions, markers, layers, bounds
    water: Water | None = None
    satellite: dict[str, Any] | None = None
    provenance: list[Provenance] = []
    cache: dict[str, Any] | None = None     # {"ref", "saved_at", "origin", "hit"} gdy kontekst jest w cache


class ContextRequest(BaseModel):
    parcel: Parcel
    as_of: date | None = None


# ------------------------------------------------------------------ krok 4

class DateRange(BaseModel):
    from_: date = Field(alias="from")
    to: date

    model_config = {"populate_by_name": True}


class Answers(BaseModel):
    irrigation_water: bool | None = None
    drained: bool | None = None
    ditch_with_weir: bool | None = None
    # potwierdzenia rolnika przy znacznikach terenu: {"ditch0": true, "pond0": false, ...}
    # true = „tak, to rów / stoi tu woda”, false = „nie”, brak klucza albo null = „nie wiem”
    sites: dict[str, bool | None] = Field(default_factory=dict)


class RecommendRequest(BaseModel):
    crop: CropCode
    range: DateRange
    sowing_date: date | None = None
    answers: Answers = Field(default_factory=Answers)


class RecommendBody(BaseModel):
    context: ParcelContext | None = None
    context_ref: str | None = None          # numer działki z cache zamiast całego kontekstu
    request: RecommendRequest


class Interval(BaseModel):
    median: float | None
    low: float | None
    high: float | None


class Evidence(BaseModel):
    field: str
    value: Any


class Recommendation(BaseModel):
    id: str
    rule: str
    group: Literal["retencja", "agrotechnika", "nawadnianie"]
    lead_time: str | None = None
    when: dict[str, date | None] | None = None
    when_text: str | None = None
    when_short: str | None = None           # krótki termin do zwiniętej karty, np. „luty–marzec”
    title: str | None = None                # krótka rada w trybie rozkazującym (lista rad bez szczegółów)
    message: str
    why: str
    effect: dict[str, Any] | None = None
    conditional: bool = False
    confidence: Confidence
    confidence_reason: str | None = None    # skąd taka pewność (wyjaśnienie dla rolnika i mentora)
    evidence: list[Evidence]
    marker: dict[str, Any] | None = None
    site_question: dict[str, str] | None = None   # {"id": "ditch0", "text": "Czy to rów?"} – pytanie przy znaczniku
    sources: list[str] = []
    consult_note: str | None = None         # bramka G4 dla inwestycji


class NotEvaluated(BaseModel):
    rule: str
    reason: str
    title: str | None = None                # krótka nazwa rady (z rules.yaml), do pokazania rolnikowi


class Cause(BaseModel):
    code: Literal["C1", "C2", "C3", "C4"]
    dominant: bool
    confidence: Confidence
    why: str
    evidence: list[Evidence] = []
    confidence_reason: str | None = None


class AnalysisResult(BaseModel):
    request: RecommendRequest
    parcel: dict[str, Any]
    generated_at: str
    partial: bool
    state: dict[str, Any]
    forecast: dict[str, Any] | None
    susceptibility: dict[str, Any] | None
    causes: list[Cause]
    recommendations: list[Recommendation]
    not_evaluated: list[NotEvaluated] = []
    uncertainty: dict[str, Any]
    provenance: list[Provenance]
    limitations: list[str]


class Summary(BaseModel):
    status: Literal["ok", "fallback"]
    model: str
    summary: str
    items: list[dict[str, str]]
    warnings: list[str]
    grounding_ok: bool
    latency_ms: int
    usage: dict[str, Any] | None = None
