"""GET /api/status – czy serwer aplikacji działa (frontend odpytuje co 30 s). Bez sieci."""

from fastapi.testclient import TestClient

from app.main import app


def test_status_endpoint():
    r = TestClient(app).get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["meteo_primary"] in ("nasa_power", "open_meteo")
    assert body["openeo_configured"] is False and body["satellite_jobs_running"] == 0
