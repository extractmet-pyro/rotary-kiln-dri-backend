"""API smoke test against a running service.  Usage: python scripts/smoke_api.py https://<host>"""
import json
import sys
import urllib.request

base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")


def get(p):
    with urllib.request.urlopen(base + p, timeout=60) as r:
        return json.loads(r.read())


def post(p, body):
    req = urllib.request.Request(base + p, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


print("live:", get("/health/live"))
print("ready:", get("/health/ready"))
print("meta:", get("/api/v1/meta")["release_label"])
acc = post("/api/v1/simulations", {"preset": "RK-100TPD"})
print("baseline cached:", acc["cached"])
k = get(f"/api/v1/simulations/{acc['run_id']}/results")["kpi"]
print("metallization %:", round(k["metallization_pct"], 2), "DRI t/h:", round(k["dri_t_h"], 3))
r = post("/api/v1/mpc/recommend", {"rank_all": False})
print("mpc:", r["gates"]["status"], "|", r["explanation"][:120])
print("SMOKE OK")
