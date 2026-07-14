"""
Smoke tests for the KSP CIAP backend.

Run with:
    pip install -r requirements.txt
    pip install pytest httpx
    pytest tests/ -v

Uses a fresh temp SQLite file per test session so this never touches your
real ciap.db, and exercises the full auth -> RBAC -> data flow end to end.
"""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

# Point the app at a throwaway DB *before* importing it, since main.py
# creates its engine at import time.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ["SECRET_KEY"] = "test-secret"

from main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="session")
def admin_token():
    resp = client.post("/api/v1/auth/login", data={"username": "KSP-3003", "password": "admin123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def officer_token():
    resp = client.post("/api/v1/auth/login", data={"username": "KSP-1001", "password": "officer123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_login_rejects_bad_password():
    resp = client.post("/api/v1/auth/login", data={"username": "KSP-3003", "password": "wrong"})
    assert resp.status_code == 401


def test_login_succeeds_and_returns_role(admin_token):
    resp = client.get("/api/v1/auth/me", headers=auth_header(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "admin"
    assert "dismiss" in body["permissions"]


def test_unauthenticated_request_rejected():
    resp = client.get("/api/v1/incidents")
    assert resp.status_code == 401


def test_list_districts_seeded(admin_token):
    resp = client.get("/api/v1/districts", headers=auth_header(admin_token))
    assert resp.status_code == 200
    districts = resp.json()
    assert len(districts) == 6
    assert any(d["name"] == "Bengaluru Urban" for d in districts)


def test_incidents_are_seeded_and_paginated(admin_token):
    resp = client.get("/api/v1/incidents?since_hours=720&page=1&page_size=10", headers=auth_header(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] > 0
    assert len(body["items"]) <= 10


def test_risk_scores_present(admin_token):
    resp = client.get("/api/v1/risk/districts", headers=auth_header(admin_token))
    assert resp.status_code == 200
    assert len(resp.json()) == 6


def test_officer_cannot_ack_alert(officer_token, admin_token):
    alerts = client.get("/api/v1/alerts", headers=auth_header(admin_token)).json()
    assert len(alerts) > 0
    alert_id = alerts[0]["id"]
    resp = client.post(f"/api/v1/alerts/{alert_id}/ack", headers=auth_header(officer_token))
    assert resp.status_code == 403


def test_admin_can_ack_alert(admin_token):
    alerts = client.get("/api/v1/alerts", headers=auth_header(admin_token)).json()
    unacked = [a for a in alerts if not a["acknowledged"]]
    assert unacked, "expected at least one unacknowledged seeded alert"
    resp = client.post(f"/api/v1/alerts/{unacked[0]['id']}/ack", headers=auth_header(admin_token))
    assert resp.status_code == 200
    assert resp.json()["acknowledged"] is True


def test_graph_neighbors_returns_shared_location_suspects(admin_token):
    suspects = client.get("/api/v1/suspects", headers=auth_header(admin_token)).json()
    assert len(suspects) == 8
    name = suspects[0]["full_name"]
    resp = client.get(f"/api/v1/graph/neighbors/{name}", headers=auth_header(admin_token))
    assert resp.status_code == 200
    assert resp.json()["suspect"] == name


def test_graph_neighbors_404_for_unknown_suspect(admin_token):
    resp = client.get("/api/v1/graph/neighbors/Nobody-Real", headers=auth_header(admin_token))
    assert resp.status_code == 404


def test_ingest_csv_inserts_and_dedupes(admin_token):
    row = {
        "fir_number": "FIR-TEST-0001",
        "district": "Mysuru",
        "crime_type": "Theft",
        "lat": "12.30",
        "lon": "76.64",
        "occurred_at": "2026-07-01T10:00:00",
        "modus_operandi": "Test row",
    }
    resp = client.post("/api/v1/ingest/csv", json=[row], headers=auth_header(admin_token))
    assert resp.status_code == 200
    assert resp.json()["rows_inserted"] == 1

    # Second submission of the same FIR number should be skipped as a duplicate
    resp2 = client.post("/api/v1/ingest/csv", json=[row], headers=auth_header(admin_token))
    assert resp2.json()["rows_skipped_duplicate"] == 1


def test_ingest_csv_requires_admin(officer_token):
    resp = client.post("/api/v1/ingest/csv", json=[], headers=auth_header(officer_token))
    assert resp.status_code == 403


def test_districts_include_lat_lon(admin_token):
    resp = client.get("/api/v1/districts", headers=auth_header(admin_token))
    assert resp.status_code == 200
    for d in resp.json():
        assert d["lat"] is not None and d["lon"] is not None


def test_hotspot_matrix_shape(admin_token):
    resp = client.get("/api/v1/incidents/hotspots/matrix", headers=auth_header(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 6
    for row in body:
        assert len(row["hours"]) == 24


def test_incidents_trend_shape(admin_token):
    resp = client.get("/api/v1/incidents/trend?hours=24", headers=auth_header(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 24
    assert all("actual" in h and "baseline" in h for h in body)


def test_graph_full_returns_nodes_and_links(admin_token):
    resp = client.get("/api/v1/graph/full", headers=auth_header(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nodes"]) > 0
    suspect_nodes = [n for n in body["nodes"] if n["type"] == "suspect"]
    assert len(suspect_nodes) == 8


def test_ingest_status_lists_all_districts(admin_token):
    resp = client.get("/api/v1/ingest/status", headers=auth_header(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 6
    assert all(row["status"] in ("SYNCED", "SCHEMA DRIFT", "NO DATA") for row in body)


def test_ingest_csv_updates_ingest_status(admin_token):
    before = {r["district"]: r["rows"] for r in client.get("/api/v1/ingest/status", headers=auth_header(admin_token)).json()}
    row = {
        "fir_number": "FIR-TEST-STATUS-0001",
        "district": "Belagavi",
        "crime_type": "Theft",
        "lat": "15.85",
        "lon": "74.50",
        "occurred_at": "2026-07-01T10:00:00",
        "modus_operandi": "Test row",
    }
    client.post("/api/v1/ingest/csv", json=[row], headers=auth_header(admin_token))
    after = {r["district"]: r["rows"] for r in client.get("/api/v1/ingest/status", headers=auth_header(admin_token)).json()}
    assert after["Belagavi"] == 1  # this run's own insert count, not cumulative
