from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException

from app import baseline, cache
from app.engine.assemble import build
from app.engine.weather import shift_year
from app.models import AnalysisResult, RecommendBody

router = APIRouter()
MAX_YEARS_BACK = 10
MAX_RANGE_YEARS = 2


def _invalid(msg: str):
    raise HTTPException(422, {"error": "invalid_request", "message": msg})


@router.post("/api/recommend", response_model=AnalysisResult)
async def post_recommend(body: RecommendBody):
    if body.context is None:                # odwołanie do zapisanego kontekstu zamiast przesyłania całości
        saved = cache.load(body.context_ref) if body.context_ref else None
        if saved is None:
            _invalid("Brak kontekstu działki: wyślij `context` albo `context_ref` zapisanej działki.")
        body = body.model_copy(update={"context": saved})
    rng = body.request.range
    today = date.today()
    if rng.to < rng.from_:
        _invalid("Koniec zakresu dat musi być po początku.")
    if rng.from_ > today:
        _invalid("Początek zakresu nie może być w przyszłości: prognoza zaczyna się od dziś.")
    if rng.from_ < today - timedelta(days=366 * MAX_YEARS_BACK):
        _invalid("Początek zakresu może być najwyżej 10 lat wstecz.")
    if rng.to > shift_year(rng.from_, MAX_RANGE_YEARS):
        _invalid("Zakres dat może mieć najwyżej 2 lata.")
    if body.context.meteo is None:
        raise HTTPException(409, {"error": "meteo_missing",
                                  "message": "Brak danych pogodowych dla działki, więc nie ma oceny. Spróbuj ponownie za chwilę."})
    first = min(d.date for d in body.context.meteo.daily) if body.context.meteo.daily else None
    need = date(rng.from_.year - MAX_YEARS_BACK, 3, 1)
    if first is None or first > need or rng.from_ > body.context.as_of:
        raise HTTPException(409, {"error": "meteo_range",
                                  "message": "Dane pogodowe nie obejmują 10 lat przed wybraną datą. Pobieram je ponownie.",
                                  "as_of": rng.from_.isoformat()})
    # baza satelitarna z lat ubiegłych (openEO): z pliku w cache; gdy jej brak – zadanie w tle, raport od razu bez niej
    s2state = baseline.ensure(body.context.parcel, rng.from_)
    s2base = baseline.load(body.context.parcel.id) if s2state.get("state") == "gotowe" else None
    return build(body.context, body.request, s2base=s2base, s2state=s2state)
