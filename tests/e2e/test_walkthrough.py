"""End-to-end demo walkthrough (API level): mirrors docs/DEMO_WALKTHROUGH.md."""
import time
import warnings

from fastapi.testclient import TestClient

warnings.filterwarnings("ignore")


def test_walkthrough():
    from app.main import app
    with TestClient(app) as c:
        assert c.get("/health/ready").status_code == 200
        base = c.post("/api/v1/simulations", json={"preset": "RK-100TPD"}).json()
        k = c.get(f"/api/v1/simulations/{base['run_id']}/results").json()["kpi"]
        assert k["metallization_pct"] > 80
        job = c.post("/api/v1/simulations", json={"preset": "RK-100TPD", "scenario_name": "e2e fast wet pellets",
                                                  "disturbances": {"pellet_moisture_wt_pct": 3.0},
                                                  "simulation": {"type": "steady", "fast": True}}).json()
        t0 = time.time()
        while time.time() - t0 < 300:
            s = c.get(f"/api/v1/simulations/{job['run_id']}").json()
            if s["status"] in ("succeeded", "failed"):
                break
            time.sleep(2)
        assert s["status"] == "succeeded", s
        res = c.get(f"/api/v1/simulations/{job['run_id']}/results").json()
        assert res["elemental_balances"]["mass"]["relative_residual"] < 1e-4
        rec = c.post("/api/v1/mpc/recommend", json={"scenario": "minimize_specific_coal", "rank_all": False}).json()
        assert rec["moves"]
