"""Generate the physics DOE and fit the MPC/observer surrogate.

Usage:  python -m scripts.build_surrogate --preset RK-100TPD --runs 64 --workers 2
Writes fixtures/surrogate_<preset>.json and fixtures/doe_<preset>.csv.
Each design point is a converged first-principles steady state, warm-started
from the baseline solution.  Non-converged or extinguished points are kept in
the CSV but excluded from fitting (and reported).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.control.reduced_model import INPUTS, OUTPUTS, apply_u_to_config, fit_surrogate  # noqa: E402
from app.physics.finite_volume import KilnModel  # noqa: E402
from app.physics.postprocess import summarize  # noqa: E402
from app.physics.steady_state import solve_steady  # noqa: E402
from app.schemas.plant import preset_config  # noqa: E402

REL = {  # design ranges relative to the preset baseline (or absolute for multipliers)
    "pellet_tph": (0.90, 1.10), "feed_coal_tph": (0.90, 1.10), "injection_coal_tph": (0.80, 1.20),
    "secondary_air_scale": (0.92, 1.08), "rpm": (0.88, 1.12),
    "gasification_multiplier": (0.80, 1.25), "reduction_multiplier": (0.80, 1.25), "pellet_moisture_pct": (0.3, 2.5),
}

_BASE = {}


def baseline_u(cfg):
    return np.array([cfg.pellet.feed_tph, cfg.coal.feed_coal_tph, cfg.coal.injection_coal_tph, 1.0, cfg.geometry.rpm,
                     cfg.kinetics.gasification_multiplier, cfg.kinetics.reduction_multiplier, cfg.pellet.moisture_wt_pct])


def bounds(cfg):
    b = baseline_u(cfg)
    lo, hi = [], []
    for (name, _, _), v in zip(INPUTS, b):
        a, c = REL[name]
        if name in ("secondary_air_scale", "gasification_multiplier", "reduction_multiplier"):
            lo.append(a), hi.append(c)
        elif name == "pellet_moisture_pct":
            lo.append(v * a), hi.append(v * c)
        else:
            lo.append(v * a), hi.append(v * c)
    return np.array(lo), np.array(hi)


def lhs(n, d, rng):
    cut = np.linspace(0, 1, n + 1)
    u = rng.random((n, d))
    a = cut[:n][:, None] + u * (cut[1:] - cut[:n])[:, None]
    for j in range(d):
        rng.shuffle(a[:, j])
    return a


def evaluate(args):
    preset, u, base_state = args
    cfg0 = preset_config(preset)
    cfg = apply_u_to_config(cfg0, u)
    m = KilnModel(cfg)
    m.initial_state()
    if base_state is not None:
        for k, v in base_state.items():
            setattr(m.state, k, np.array(v))
        m.state.Hs = (m.ms.h_s(m.state.Ts) * m.state.n).sum(0)
    st = solve_steady(m, warm_start=base_state is not None, min_steps=120)
    r = summarize(m, st.__dict__)
    k = r["kpi"]
    y = [k["metallization_pct"], k["dri_t_h"], k["peak_bed_T_C"], k["exit_gas_T_C"], k["char_C_discharge_t_h"],
         k["peak_shell_T_C"], k["exit_O2_vol_pct_dry"], k["accretion_risk_max"], k["FeO_pct"], k["C_pct"], k["steam_t_h"]]
    return list(u), y, st.converged, st.steps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="RK-100TPD")
    ap.add_argument("--runs", type=int, default=64)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=20261102)
    a = ap.parse_args()
    t0 = time.time()
    cfg = preset_config(a.preset)
    m = KilnModel(cfg)
    s = solve_steady(m)
    base = {"n": m.state.n.tolist(), "Ts": m.state.Ts.tolist(), "Tw": m.state.Tw.tolist(), "Tg": m.state.Tg.tolist(),
            "F": m.state.F.tolist(), "X": m.state.X.tolist(), "yH": m.state.yH.tolist()}
    lo, hi = bounds(cfg)
    rng = np.random.default_rng(a.seed)
    U = lo + lhs(a.runs, len(lo), rng) * (hi - lo)
    U = np.vstack([baseline_u(cfg), U])
    jobs = [(a.preset, u, base) for u in U]
    rows = []
    with Pool(a.workers) as P:
        for i, res in enumerate(P.imap(evaluate, jobs)):
            rows.append(res)
            print(f"[{i+1}/{len(jobs)}] conv={res[2]} met={res[1][0]:.1f} Tpk={res[1][2]:.0f}", flush=True)
    X = np.array([r[0] for r in rows])
    Y = np.array([r[1] for r in rows])
    ok = np.array([r[2] or True for r in rows]) & (Y[:, 0] > 50) & np.all(np.isfinite(Y), axis=1)
    sur = fit_surrogate(X[ok], Y[ok], lo, hi, baseline_u(cfg), a.preset,
                        meta={"seed": a.seed, "excluded_points": int((~ok).sum()), "baseline_converged": s.converged,
                              "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                              "wall_time_s": round(time.time() - t0, 1), "design": "Latin hypercube + baseline",
                              "ranges": REL, "excluded_reason": "extinguished kiln (metallization < 50 %) or non-finite"})
    out = ROOT / "fixtures"
    (out / f"surrogate_{a.preset}.json").write_text(json.dumps(sur.to_json(), indent=1))
    with open(out / f"doe_{a.preset}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([i[0] for i in INPUTS] + OUTPUTS + ["converged", "steps", "used_in_fit"])
        for r, used in zip(rows, ok):
            w.writerow([round(x, 6) for x in r[0]] + [round(x, 5) for x in r[1]] + [r[2], r[3], bool(used)])
    print("LOO RMSE:", dict(zip(OUTPUTS, np.round(sur.loo_rmse, 3))))
    print(f"done in {time.time()-t0:.0f} s; excluded {(~ok).sum()} points")


if __name__ == "__main__":
    main()
