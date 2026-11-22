"""Kształty pól, które w runtime zostają dict.

Silnik i testy indeksują teren, satelitę i wynik oceny jak słowniki
(`ctx.terrain["stats"]`). Gdyby te pola były modelami Pydantic, walidacja
obcięłaby nieznane klucze. Dlatego modele poniżej nie są typami pól w
`app.models`: `contract_export` wstawia je do wspólnego OpenAPI, a test
sprawdza, że prawdziwy JSON się w nich mieści.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Confidence, DateRange, Interval


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class CacheMeta(_Open):
    """Odwołanie do zapisanego kontekstu działki."""

    ref: str
    saved_at: str = Field(description="ISO-8601, UTC.")
    origin: str
    hit: bool | None = None


class TerrainLayers(_Open):
    """PNG jako data URL, nakładki na mapę."""

    slope: str
    depressions: str
    flow: str


class TerrainMarker(_Open):
    """Znacznik na mapie działki. `at` to [lat, lon]."""

    id: str
    kind: Literal["ditch", "pond", "wet_spot", "outlet", "low"]
    at: list[float]
    title: str
    text: str


class TerrainStats(_Open):
    cell_m: float
    elevation_min_m: float
    elevation_max_m: float
    relief_m: float
    slope_mean_pct: float
    slope_p90_pct: float
    slope_mean_deg: float
    slope_p90_deg: float
    flow_paths_on_parcel: int
    area_slope_over_5pct_pct: float
    inflow_from_outside_ha: float
    inflow_is_lower_bound: bool = True
    pond_volume_m3: float
    n_ponds: int
    n_wet_spots: int
    n_ditches: int
    ditch_near_parcel: bool
    flat_terrain: bool


class Depression(_Open):
    id: str
    kind: Literal["ditch", "pond", "wet_spot"]
    at: list[float] = Field(description="[lat, lon]")
    area_m2: float
    volume_m3: float
    max_depth_m: float
    width_m: float
    length_m: float
    elongation: float
    inside_parcel_pct: float
    outlets_in: int = 0
    inflow_from_parcel_ha: float = 0


class Outlet(_Open):
    at: list[float] = Field(description="[lat, lon]")
    catchment_ha: float
    drains_to: str | None = None


class TerrainParams(_Open):
    buffer_m: float
    coverage: str | None = None
    thresholds: str | None = None


class Terrain(_Open):
    """Analiza NMT: statystyki, znaczniki i warstwy PNG."""

    bounds: list[list[float]] = Field(description="[[lat, lon], [lat, lon]], róg południowo-zachodni i północno-wschodni.")
    layers: TerrainLayers
    markers: list[TerrainMarker]
    depressions: list[Depression] = []
    outlets: list[Outlet] = []
    stats: TerrainStats
    params: TerrainParams | None = None


class SatelliteObs(_Open):
    date: str = Field(description="YYYY-MM-DD")
    scene: str
    valid_frac: float
    ndmi: float | None = None
    ndre: float | None = None
    ndvi: float | None = None


class Satellite(_Open):
    """Sentinel-2 na działce: NDMI i daty zasłonięte chmurami."""

    season: int
    obs: list[SatelliteObs]
    cloudy_dates: list[str] = []
    scenes_found: int
    scenes_checked: int
    scenes_clear: int
    partial: bool
    mode: Literal["lekki", "pelny"] | None = None


class ParcelBrief(_Open):
    """Działka w wyniku oceny: tylko to, co wraca z /api/recommend."""

    id: str
    area_ha: float


class Effect(_Open):
    text: str | None = None


class SiteQuestion(_Open):
    id: str
    text: str


class MapPoint(_Open):
    """Punkt „pokaż na mapie”. `at` to [lat, lon]."""

    id: str
    at: list[float]


class KbwPeriod(_Open):
    label: str
    start: date
    end: date


class KbwSeasonRow(_Open):
    label: str
    kbw_mm: float | None = None
    threshold_mm: float | None = None
    status: str


KbwStatus = Literal["zagrozenie", "na_granicy", "brak_zagrozenia", "poza_okresem", "brak_progu", "brak_danych"]


class KbwState(_Open):
    status: KbwStatus
    period_status: str | None = None
    period: KbwPeriod | None = None
    kbw_mm: float | None = None
    threshold_mm: float | None = None
    margin_mm: float | None = None
    method: str | None = None
    note: str | None = None
    season: list[KbwSeasonRow] | None = None


class SoilWater(_Open):
    """Zapas wody w glebie w dniu analizy. Przedziały to median / low / high."""

    taw_mm: Interval
    dr_mm: Interval | None = None
    pct_of_taw: Interval
    below_raw: bool
    phase: str | None = None
    phase_label: str
    kc: float
    season_start: date | None = None
    harvest: date | None = None
    safe_level_pct: float | None = None
    season_start_source: str | None = None
    taw_runs: list[str] = []


class AnalysisState(_Open):
    """Werdykt pokazywany rolnikowi i liczby, z których powstał."""

    kbw: KbwState
    soil_water: SoilWater | None = None
    headline: str
    headline_key: str | None = None
    headline_more: list[str] = []
    headline_technical: str


class Chance(_Open):
    n: int
    of: int


class DaysToRaw(Interval):
    """Dni do zejścia poniżej RAW. `n` to liczba scenariuszy, w których to nastąpiło."""

    n: int | None = None


class ForecastView(_Open):
    """Prognoza niedoboru na wybrany zakres dat."""

    status: Literal["ok", "poza_sezonem_uprawy", "brak_danych"]
    range: DateRange
    forecast_days_used: int
    scenario_years: list[int]
    in_season_days: int
    stress_chance: Chance | None = None
    days_to_raw: DaysToRaw | None = None
    deficit_mm: Interval | None = None
    deficit_m3: Interval | None = None
    note: str | None = None
    taw_run_used_for_chance: str | None = None


class SeasonStress(_Open):
    year: int
    kbw_exceeded: bool | None = None
    stress_days_critical: int | None = None


class Susceptibility(_Open):
    """Ostatnie sezony: ile razy KBW spadł poniżej progu i ile razy był niedobór w pełni wzrostu."""

    years: list[int]
    n_kbw: int | None = None
    of_kbw: int
    n_ks: int | None = None
    of: int
    risk_months: list[str] = []
    risk_months_counts: dict[str, int] = {}
    per_year: list[SeasonStress] = []
    taw_mm_used: float | None = None


class Uncertainty(_Open):
    overall: Confidence
    reasons: list[str]


# Modele wstawiane do components.schemas. Zagnieżdżone dochodzą z $defs.
ROOT_VIEWS: tuple[type[BaseModel], ...] = (
    CacheMeta, Terrain, Satellite, ParcelBrief, Effect, SiteQuestion, MapPoint,
    AnalysisState, ForecastView, Susceptibility, Uncertainty,
)

# (model w components, pole, widok, czy wartość może być null)
FIELD_VIEWS: tuple[tuple[str, str, type[BaseModel], bool], ...] = (
    ("ParcelContext", "terrain", Terrain, True),
    ("ParcelContext", "satellite", Satellite, True),
    ("ParcelContext", "cache", CacheMeta, True),
    ("AnalysisResult", "parcel", ParcelBrief, False),
    ("AnalysisResult", "state", AnalysisState, False),
    ("AnalysisResult", "forecast", ForecastView, True),
    ("AnalysisResult", "susceptibility", Susceptibility, True),
    ("AnalysisResult", "uncertainty", Uncertainty, False),
    ("Recommendation", "effect", Effect, True),
    ("Recommendation", "marker", MapPoint, True),
    ("Recommendation", "site_question", SiteQuestion, True),
)
