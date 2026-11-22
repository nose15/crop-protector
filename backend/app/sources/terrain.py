"""NMT GUGiK (WCS) + analiza terenu (app.terrain.analysis)."""

from __future__ import annotations

from datetime import date

import httpx

from app.models import Parcel
from app.sources.base import SourceAdapter
from app.terrain import analysis

BUFFER_M = 50     # 150 m nie mieścił się w limicie (zmierzone 10 s dla 300×300 m)


class TerrainAdapter(SourceAdapter[dict]):
    name = "NMT GUGiK (WCS, siatka 1 m, próbkowane co 2 m)"
    licence = "GUGiK, bezpłatnie"
    timeout_s = 15.0

    async def _fetch(self, client: httpx.AsyncClient, parcel: Parcel, as_of: date):
        result = await analysis.analyze(client, parcel.rings[0], buffer_m=BUFFER_M)
        result["dem_source"] = "nmt_gugik_1m"
        return result, None
