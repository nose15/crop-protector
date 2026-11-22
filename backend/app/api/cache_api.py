from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import cache
from app.models import ParcelContext

router = APIRouter()


@router.get("/api/cache")
async def list_cached():
    """Działki zapisane w cache (do prezentacji bez zapytań do usług)."""
    return cache.list_all()


@router.get("/api/cache/{parcel_id}", response_model=ParcelContext)
async def get_cached(parcel_id: str):
    ctx = cache.load(parcel_id)
    if ctx is None:
        raise HTTPException(404, {"error": "not_cached", "message": f"Działki {parcel_id} nie ma w zapisanych danych."})
    return ctx.model_copy(update={"cache": {**(ctx.cache or {}), "hit": True}})
