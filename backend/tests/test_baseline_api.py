"""GET /api/baseline/{numer} – stan bazy satelitarnej działki (frontend po „gotowe” sam przelicza wynik). Bez sieci."""

from datetime import date

from fastapi.testclient import TestClient

from app import baseline
from app.main import app


def test_baseline_endpoint_without_account():
    r = TestClient(app).get("/api/baseline/000000_0.0000.1")
    assert r.status_code == 200 and r.json()["state"] == "nieskonfigurowane"


def test_baseline_endpoint_reads_saved_file():
    baseline.save("000000_0.0000.2", {"parcel_id": "000000_0.0000.2", "from": "2018-03-01", "until": "2025-10-01",
                                      "obs": [{"date": "2025-07-01", "ndvi": 0.7, "ndmi": 0.3, "valid_frac": 1.0}],
                                      "retrieved_at": "2025-10-01T00:00:00+00:00"})
    body = TestClient(app).get("/api/baseline/000000_0.0000.2").json()
    assert body["state"] == "gotowe" and body["obs"] == 1 and body["until"] == "2025-10-01"
    assert baseline.covers(baseline.load("000000_0.0000.2"), date(2025, 7, 15))
    assert not baseline.covers(baseline.load("000000_0.0000.2"), date(2026, 7, 15))


def test_demo_parcel_has_seeded_baseline():
    """Działka przykładowa ma bazę w zapisie startowym, więc porównanie jest od razu (bez zadania w tle)."""
    b = baseline.load("046101_1.0445.7")
    assert b is not None and len(b["obs"]) > 100 and b["from"] == "2018-03-01"
