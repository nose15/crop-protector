"""/api/report.pdf: raport działki do pobrania jako PDF.

Backend jest bezstanowy, więc frontend odsyła gotowy wynik z `/api/recommend` (jak przy eksporcie „Dane”)
i opcjonalnie dane działki do nagłówka (gmina, obręb). Nic nie jest przeliczane – PDF pokazuje ten sam wynik,
który rolnik widzi na ekranie.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from app.models import AnalysisResult
from app.report_pdf import render

router = APIRouter()


class ReportBody(BaseModel):
    result: AnalysisResult
    parcel: dict[str, Any] | None = None    # Parcel z /api/parcel; do nagłówka bierzemy id, gmina, obreb, area_ha


def filename(result: AnalysisResult) -> str:
    pid = re.sub(r"[^0-9A-Za-z_.-]", "_", str((result.parcel or {}).get("id", "dzialka")))
    return f"raport-{pid}-{result.request.range.from_.isoformat()}.pdf"


@router.post("/api/report.pdf", response_class=Response,
             responses={200: {"content": {"application/pdf": {}}, "description": "Raport działki (PDF)"}})
def post_report(body: ReportBody) -> Response:   # zwykła funkcja: FastAPI składa PDF w puli wątków, nie blokuje pętli
    pdf = render(body.result, body.parcel)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename(body.result)}"'})
