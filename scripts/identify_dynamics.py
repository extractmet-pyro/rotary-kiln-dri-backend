"""Identify FOPDT time constants/dead times from step tests on the detailed
transient physics.  Usage: python -m scripts.identify_dynamics --preset RK-100TPD"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.control.dynamics import default_dynamics, fit_fopdt  # noqa: E402
from app.control.reduced_model import INPUTS, OUTPUTS  # noqa: E402
from app.physics.finite_volume import KilnModel  # noqa: E402
from app.physics.steady_state import solve_steady  # noqa: E402
from app.physics.transient import run_transient  # noqa: E402
from app.schemas.plant import preset_config  # noqa: E402

MAP = {"metallization_pct": "metallization_discharge_pct", "dri_t_h": "dri_t_h", "peak_bed_T_C": "peak_bed_T_C",
       "exit_gas_T_C": "exit_gas_T_C", "char_C_discharge_t_h": "char_C_discharge_t_h",
       "peak_shell_T_C": "peak_shell_T_C", "exit_O2_vol_pct_dry": "exit_O2_pct_dry"}
STEPS = {0: ("pellet.feed_tph", 1.05), 1: ("coal.feed_coal_tph", 1.05), 2: ("coal.injection_coal_tph", 1.10),
         3: ("air.secondary_air_scale", 1.03), 4: ("geometry.rpm", 1.05)}

ap = argparse.ArgumentParser()
ap.add_argument("--preset", default="RK-100TPD")
ap.add_argument("--hours", type=float, default=12.0)
a = ap.parse_args()
cfg = preset_config(a.preset)
m0 = KilnModel(cfg)
solve_steady(m0)
base_state = {k: getattr(m0.state, k).copy() for k in ("n", "Hs", "Ts", "Tw", "Tg", "F", "X", "yH")}
dyn = default_dynamics()
tau, theta = dyn.tau_min.copy(), dyn.theta_min.copy()
report = {}
for j, (path, fac) in STEPS.items():
    m = KilnModel(preset_config(a.preset))
    m.initial_state()
    for k, v in base_state.items():
        setattr(m.state, k, v.copy())
    m.state.t = 0.0
    sec, key = path.split(".")
    val = 1.0 * fac if key == "secondary_air_scale" else getattr(getattr(m.cfg, sec), key) * fac
    tr = run_transient(m, a.hours * 60, 10, [{"t_min": 0.0, "changes": {path: val}}])
    t = np.array([0.0] + [s["t_h"] * 60 for s in tr["series"]])
    for i, o in enumerate(OUTPUTS):
        if o not in MAP:
            continue
        y = np.array([tr["series"][0][MAP[o]]] + [s[MAP[o]] for s in tr["series"]])
        if np.ptp(y) < 1e-6:
            continue
        K, ta, th = fit_fopdt(t, y)
        tau[i, j], theta[i, j] = ta, th
        report[f"{INPUTS[j][0]}->{o}"] = {"gain_per_step": K, "tau_min": ta, "theta_min": th}
    print("identified", path, flush=True)
out = {"tau_min": tau.tolist(), "theta_min": theta.tolist(), "source": f"identified from physics step tests ({a.preset})",
       "pairs": report, "inputs": [i[0] for i in INPUTS], "outputs": OUTPUTS}
(ROOT / "fixtures" / f"dynamics_{a.preset}.json").write_text(json.dumps(out, indent=1))
print("written")
