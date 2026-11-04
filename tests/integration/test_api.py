import warnings

import pytest
from fastapi.testclient import TestClient

warnings.filterwarnings("ignore")


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def login(c, role="operator"):
    r = c.post("/api/v1/auth/login", json={"username": f"demo_{role}", "password": "demo-change-me"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health_meta(client):
    assert client.get("/health/live").json()["status"] == "alive"
    assert client.get("/health/ready").json()["database"] == "ok"
    m = client.get("/api/v1/meta").json()
    assert "NO write path" in m["disclaimer"]


def test_security_headers(client):
    r = client.get("/api/v1/meta")
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_presets_and_config(client):
    p = client.get("/api/v1/config/presets").json()
    assert len(p["presets"]) == 4
    cfg = client.get("/api/v1/config/plant?preset=RK-350TPD").json()["config"]
    assert client.post("/api/v1/config/validate", json=cfg).json()["valid"]
    bad = dict(cfg)
    bad["geometry"] = {**cfg["geometry"], "rpm": 9.0}
    r = client.post("/api/v1/config/validate", json=bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INPUT_VALIDATION"


def test_rbac_config_write_denied_for_anonymous(client):
    r = client.put("/api/v1/config/plant", json={"config": {}})
    assert r.status_code == 403


def test_cached_baseline_simulation_and_exports(client):
    r = client.post("/api/v1/simulations", json={"preset": "RK-100TPD"}).json()
    assert r["cached"] is True
    rid = r["run_id"]
    res = client.get(f"/api/v1/simulations/{rid}/results").json()
    for key in ("profiles", "material_balance", "elemental_balances", "heat_balance", "quality", "kpi",
                "solver_diagnostics", "warnings", "model_version"):
        assert key in res
    assert client.get(f"/api/v1/simulations/{rid}/export?format=csv").status_code == 200
    assert client.get(f"/api/v1/simulations/{rid}/export?format=xlsx").content[:2] == b"PK"
    assert client.get(f"/api/v1/simulations/{rid}/export?format=pdf").content[:4] == b"%PDF"


def test_supervisory_mode_rejected(client):
    r = client.post("/api/v1/simulations", json={"mode": "SITE_SUPERVISORY"})
    assert r.status_code == 422


def test_mpc_recommend_and_decision(client):
    r = client.post("/api/v1/mpc/recommend", json={"rank_all": False}).json()
    assert "Approve recommendation" in r["apply_label"]
    rid = r["recommendation_id"]
    h = login(client)
    d = client.post(f"/api/v1/mpc/recommendations/{rid}/decision", json={"decision": "reject", "note": "lab pending"},
                    headers=h).json()
    assert d["actuator_write"] is False
    assert client.post(f"/api/v1/mpc/recommendations/{rid}/decision", json={"decision": "reject", "note": "x"},
                       headers=h).status_code == 422
    assert client.get(f"/api/v1/mpc/recommendations/{rid}").json()["decisions"]


def test_data_endpoints(client):
    h = client.get("/api/v1/tags/history?tags=EXHAUST_TEMP_C,LAB_METALLIZATION_PCT&hours=12").json()
    assert "SYNTHETIC" in h["banner"] and len(h["timestamps_utc"]) > 10
    assert client.get("/api/v1/tags").json()["count"] > 30
    assert client.get("/api/v1/alerts").json()["alerts"]
    s = client.get("/api/v1/states/current?hours=6").json()
    assert "estimated_parameters" in s
    q = client.post("/api/v1/quality/predict", json={}).json()
    assert "hybrid_metallization" in q
    t = client.post("/api/v1/scenarios/sensitivity", json={}).json()
    assert len(t["rows"]) == 8


def test_admin_supervisory_cannot_enable(client):
    h = login(client, "approver")
    r = client.post("/api/v1/admin/supervisory-request?reason=test", headers=h).json()
    assert r["enabled"] is False


def test_adapters_are_read_only():
    from app.integration import csv_excel, historian, mqtt_reader, opcua_reader, rest, synthetic
    for mod in (csv_excel, historian, mqtt_reader, opcua_reader, rest, synthetic):
        for name in dir(mod):
            obj = getattr(mod, name)
            if isinstance(obj, type):
                assert not any(hasattr(obj, w) for w in ("write", "write_setpoint", "publish", "call_method"))


def test_websocket_telemetry(client):
    with client.websocket_connect("/ws/v1/telemetry") as ws:
        msg = ws.receive_json()
        assert msg["banner"] == "SYNTHETIC"
