"""Wspólny kontrakt frontendu i backendu.

Źródło: modele Pydantic, trasy FastAPI i kształty z app/contract_views.py.
Z katalogu backend:

    python -m app.contract_export

Zapisuje contract/openapi.json i hacknation/frontend/src/api/shapes.js.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from pydantic import BaseModel

from app.contract_views import FIELD_VIEWS, ROOT_VIEWS
from app.main import app
from app.models import Summary

ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = ROOT / "contract" / "openapi.json"
SHAPES_PATH = ROOT / "hacknation" / "frontend" / "src" / "api" / "shapes.js"

# Etykiety upraw do selektora. Kody muszą być równe CropCode w modelach.
CROP_LABELS = (
    ("zboza_ozime", "Zboża ozime"),
    ("zboza_jare", "Zboża jare"),
    ("kukurydza_ziarno", "Kukurydza na ziarno"),
    ("kukurydza_kiszonka", "Kukurydza na kiszonkę"),
    ("rzepak", "Rzepak"),
    ("ziemniak", "Ziemniaki"),
    ("burak_cukrowy", "Burak cukrowy"),
    ("uzytki_zielone", "Użytki zielone"),
)

SKIP_JSDOC = {"HTTPValidationError", "ValidationError"}
METHODS = ("get", "post", "put", "delete")


def contract_document() -> dict:
    doc = copy.deepcopy(app.openapi())
    doc["info"]["description"] = (
        "Kontrakt współdzielony przez hacknation/frontend i backend. "
        "Generowany z modeli Pydantic (`python -m app.contract_export`). "
        "POST /api/summary jest w kontrakcie, bo woła go klient i opisuje go model Summary; "
        "trasy w backendzie jeszcze nie ma (x-implemented: false)."
    )
    components = doc["components"]["schemas"]
    for model in (*ROOT_VIEWS, Summary):
        _add_model(components, model)
    for parent, field, view, nullable in FIELD_VIEWS:
        prop: dict = {"$ref": f"#/components/schemas/{view.__name__}"}
        if nullable:
            prop = {"anyOf": [prop, {"type": "null"}]}
        text = (view.__doc__ or "").strip()
        if text:
            prop["description"] = " ".join(text.split())
        components[parent]["properties"][field] = prop
    doc["paths"]["/api/summary"] = {
        "post": {
            "summary": "Opis gotowego wyniku. Klient woła ten adres; backend jeszcze nie wystawia trasy.",
            "operationId": "summarize",
            "x-implemented": False,
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AnalysisResult"}}},
            },
            "responses": {
                "200": {
                    "description": "Podsumowanie policzonego wyniku.",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Summary"}}},
                }
            },
        }
    }
    return doc


def _add_model(components: dict, model: type[BaseModel]) -> None:
    raw = model.model_json_schema(ref_template="#/components/schemas/{model}")
    defs = raw.pop("$defs", {})
    for name, schema in defs.items():
        components.setdefault(name, schema)
    components.setdefault(model.__name__, raw)


def render_shapes(doc: dict) -> str:
    codes = _crop_codes(doc)
    labels = dict(CROP_LABELS)
    if set(codes) != set(labels):
        missing = sorted(set(codes) ^ set(labels))
        raise SystemExit(f"Kody upraw w modelu i w CROP_LABELS się różnią: {missing}")

    schemas = doc["components"]["schemas"]
    lines = [
        "// Wspólny kontrakt z backendem. Źródło: contract/openapi.json",
        "// Nie edytuj ręcznie. Regeneracja: cd backend && python -m app.contract_export",
        "//",
    ]
    for path, item in doc["paths"].items():
        for method in METHODS:
            if method not in item:
                continue
            note = "" if item[method].get("x-implemented", True) else "  (trasy w backendzie jeszcze nie ma)"
            lines.append(f"// {method.upper():4} {path}{note}")
    lines.append("")
    order = [name for name in _preferred(schemas) if name not in SKIP_JSDOC]
    for name in order:
        lines.append(_typedef(name, schemas[name]))
        lines.append("")
    lines.append("export const CROPS = [")
    for code in codes:
        lines.append(f"  [{json.dumps(code, ensure_ascii=False)}, {json.dumps(labels[code], ensure_ascii=False)}],")
    lines.append("];")
    lines.append("")
    return "\n".join(lines)


def write_contract() -> None:
    doc = contract_document()
    OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPENAPI_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    SHAPES_PATH.write_text(render_shapes(doc), encoding="utf-8")


def _preferred(schemas: dict) -> list[str]:
    first = [
        "Health", "ApiErrorDetail", "ApiErrorResponse", "CachedParcel",
        "Provenance", "Parcel", "MeteoDay", "Meteo", "Quantiles", "IungSoil", "SoilGrids", "Soil", "Water",
        "CacheMeta", "TerrainLayers", "TerrainMarker", "TerrainStats", "Depression", "Outlet", "TerrainParams", "Terrain",
        "SatelliteObs", "Satellite", "ParcelContext", "ContextRequest",
        "DateRange", "Answers", "RecommendRequest", "RecommendBody",
        "Interval", "DaysToRaw", "Evidence", "Effect", "SiteQuestion", "MapPoint", "Recommendation",
        "NotEvaluated", "Cause", "ParcelBrief", "KbwPeriod", "KbwSeasonRow", "KbwState", "SoilWater", "AnalysisState",
        "Chance", "ForecastView", "SeasonStress", "Susceptibility", "Uncertainty", "AnalysisResult", "Summary",
    ]
    return [name for name in first if name in schemas] + sorted(name for name in schemas if name not in first)


def _typedef(name: str, schema: dict) -> str:
    if "enum" in schema and "properties" not in schema:
        return f"/** @typedef {{{_js_type(schema)}}} {name} */"
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    description = _one_line(schema.get("description"))
    lines = ["/**"]
    if description:
        lines.append(f" * {description}")
    lines.append(f" * @typedef {{Object}} {name}")
    for prop, spec in props.items():
        bracket = prop if prop in required else f"[{prop}]"
        note = _prop_note(spec)
        lines.append(f" * @property {{{_js_type(spec)}}} {bracket}{note}")
    lines.append(" */")
    return "\n".join(lines)


def _prop_note(schema: dict) -> str:
    text = _one_line(schema.get("description"))
    if not text:
        fmt = schema.get("format")
        if fmt == "date":
            text = "YYYY-MM-DD"
        elif fmt == "date-time":
            text = "ISO-8601"
    if not text and "anyOf" in schema:
        for part in schema["anyOf"]:
            if part.get("format") == "date":
                text = "YYYY-MM-DD"
            elif part.get("format") == "date-time":
                text = "ISO-8601"
            text = text or _one_line(part.get("description"))
    return f"  {text}" if text else ""


def _one_line(text: str | None) -> str:
    return " ".join(text.split()) if text else ""


def _js_type(schema: dict) -> str:
    if not schema or schema is True:
        return "any"
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "allOf" in schema:
        parts = [_js_type(part) for part in schema["allOf"]]
        return parts[0] if len(parts) == 1 else "|".join(_unique(parts))
    if "anyOf" in schema or "oneOf" in schema:
        parts = [_js_type(part) for part in schema.get("anyOf") or schema.get("oneOf")]
        return "|".join(_unique(parts))
    if "enum" in schema:
        return "|".join(_enum_value(value) for value in schema["enum"])
    if "const" in schema:
        return _enum_value(schema["const"])
    kind = schema.get("type")
    if isinstance(kind, list):
        parts = []
        for item in kind:
            if item == "null":
                parts.append("null")
            else:
                parts.append(_js_type({**{k: v for k, v in schema.items() if k != "type"}, "type": item}))
        return "|".join(_unique(parts))
    if kind == "array":
        return f"{_js_type(schema.get('items') or {})}[]"
    if kind == "object":
        extra = schema.get("additionalProperties")
        props = schema.get("properties")
        if isinstance(extra, dict) and not props:
            return f"Object<string, {_js_type(extra)}>"
        if props:
            return "Object"
        return "Object<string, any>" if extra else "Object"
    if kind == "integer" or kind == "number":
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "string":
        return "string"
    if kind == "null":
        return "null"
    return "any"


def _enum_value(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _unique(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def _crop_codes(doc: dict) -> list[str]:
    prop = doc["components"]["schemas"]["RecommendRequest"]["properties"]["crop"]
    codes = _enum_of(prop, doc)
    if not codes:
        raise SystemExit("W schemacie RecommendRequest.crop nie ma listy upraw.")
    return codes


def _enum_of(schema: dict, doc: dict) -> list[str] | None:
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return _enum_of(doc["components"]["schemas"][name], doc)
    if "enum" in schema:
        return list(schema["enum"])
    for key in ("anyOf", "oneOf", "allOf"):
        for part in schema.get(key) or []:
            found = _enum_of(part, doc)
            if found:
                return found
    return None


if __name__ == "__main__":
    write_contract()
    print(f"{OPENAPI_PATH.relative_to(ROOT)}")
    print(f"{SHAPES_PATH.relative_to(ROOT)}")
