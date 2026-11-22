"""openEO (CDSE): graf procesów z szablonu i parser wyniku zadania. Bez sieci; w testach openEO jest wyłączone."""

from datetime import date

from app.sources import openeo_cdse

RING = [[18.130, 53.100], [18.140, 53.100], [18.140, 53.110], [18.130, 53.110], [18.130, 53.100]]


def test_openeo_graph_fills_parcel_and_dates():
    g = openeo_cdse.build_graph(RING, date(2018, 3, 1), date(2025, 9, 30))
    lc = next(n for n in g.values() if n["process_id"] == "load_collection")["arguments"]
    assert lc["id"] == "SENTINEL2_L2A" and lc["temporal_extent"] == ["2018-03-01", "2025-09-30"]
    assert lc["spatial_extent"] == {"west": 18.13, "south": 53.1, "east": 18.14, "north": 53.11}
    agg = next(n for n in g.values() if n["process_id"] == "aggregate_spatial")["arguments"]
    inner = agg["geometries"]["coordinates"][0]
    assert inner != RING and min(p[0] for p in inner) > 18.13          # obrys pomniejszony o 10 m
    assert [n for n in g.values() if n.get("result")][0]["process_id"] == "save_result"


def test_openeo_parse_timeseries():
    res = {"2022-06-19T00:00:00Z": [[0.6165, 0.21, 1.0]], "2022-06-24T00:00:00Z": [[None, None, 0.0]],
           "2022-06-14T00:00:00Z": [[0.58, 0.18, 0.0]]}
    obs = openeo_cdse.parse_timeseries(res)
    assert [o["date"] for o in obs] == ["2022-06-14", "2022-06-19"]   # pusty dzień pominięty, kolejność rosnąca
    assert obs[1] == {"date": "2022-06-19", "ndvi": 0.6165, "ndmi": 0.21, "valid_frac": 1.0}


def test_openeo_disabled_in_tests():
    assert openeo_cdse.configured() is False
