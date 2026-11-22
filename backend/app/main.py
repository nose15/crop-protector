"""KOWR „Zatrzymaj wodę, chroń plony” – backend (FastAPI, bezstanowy)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from datetime import datetime, timezone

from app import baseline
from app.api import cache_api, context, parcel, recommend, report
from app.sources import meteo, openeo_cdse
from app.sources.base import make_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = make_client()     # jeden współdzielony klient HTTP, bez ponowień
    yield
    await app.state.http.aclose()


app = FastAPI(title="KOWR – Zatrzymaj wodę, chroń plony", lifespan=lifespan)
# CORS bez ograniczeń: API jest publiczne i bez ciasteczek/logowania, więc frontend z dowolnej domeny
# (np. osobna usługa statyczna na Render) może je wołać bez błędów CORS.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   allow_credentials=False, max_age=86400)
app.include_router(parcel.router)
app.include_router(context.router)
app.include_router(recommend.router)
app.include_router(cache_api.router)
app.include_router(report.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/status")
async def status():
    """Czy serwer aplikacji działa – frontend odpytuje to co 30 s i pokazuje stan w pasku.
    Odpowiada od razu: bez zapytań do usług zewnętrznych (ich stan widać w „Źródłach danych” każdego wyniku)."""
    return {"status": "ok", "server_time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "meteo_primary": meteo.primary(), "openeo_configured": openeo_cdse.configured(),
            "satellite_jobs_running": baseline.running()}


# Opcjonalnie: zbudowany frontend pod tym samym adresem (jedna usługa, bez CORS). Montowany na końcu,
# żeby nie przesłaniał /api. Katalog: FRONTEND_DIST albo ../frontend/dist (gdy istnieje).
_dist = Path(os.environ.get("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if (_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
