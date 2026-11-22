"""Generuje (offline, bez połączenia z serwerem) graf procesów openEO dla bazy wieloletniej Sentinel-2.

NARZĘDZIE, NIE ZALEŻNOŚĆ APLIKACJI: wymaga pakietu `openeo` (pip install openeo) w dowolnym środowisku.
Backend nie importuje `openeo` – wysyła gotowy graf (`app/data/openeo_s2_graph.json`) przez httpx.

Przepis (metodyka sprawdzona 21.11.2026): SENTINEL2_L2A, maska SCL ∈ {4, 5}, NDVI (B08, B04), NDMI (B8A, B11),
pasmo VALID (0/1), mediana w obrysie działki. Wynik: JSON z zaślepkami, które backend podmienia przy każdym
zadaniu (spatial_extent i temporal_extent w load_collection, geometries w aggregate_spatial).

Użycie:  python gen_openeo_graph.py graf.json
Potem do grafu dopisujemy węzeł save_result (format JSON) jako wynik i zapisujemy jako app/data/openeo_s2_graph.json.
"""
import json
import sys

from openeo.rest.datacube import DataCube

geom = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
cube = DataCube.load_collection(
    "SENTINEL2_L2A", connection=None,
    spatial_extent={"west": 0, "south": 0, "east": 1, "north": 1},
    temporal_extent=["2000-01-01", "2000-12-31"],
    bands=["B04", "B08", "B8A", "B11", "SCL"],
    max_cloud_cover=80,
    fetch_metadata=False,
)
scl = cube.band("SCL")
valid = (scl == 4) | (scl == 5)
b04, b08, b8a, b11 = cube.band("B04"), cube.band("B08"), cube.band("B8A"), cube.band("B11")
ndvi = ((b08 - b04) / (b08 + b04)).mask(~valid)
ndmi = ((b8a - b11) / (b8a + b11)).mask(~valid)
merged = (ndvi.add_dimension("bands", "NDVI", "bands")
          .merge_cubes(ndmi.add_dimension("bands", "NDMI", "bands"))
          .merge_cubes((valid * 1.0).add_dimension("bands", "VALID", "bands")))
res = merged.aggregate_spatial(geometries=geom, reducer="median")
graph = res.flat_graph()
json.dump(graph, open(sys.argv[1], "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("nodes:", len(graph), sorted({n["process_id"] for n in graph.values()}))
