"""Steady-state economic optimisation, Pareto fronts, verification of MPC end
points against the detailed physics, and closed-loop simulation of the
receding-horizon MPC versus a fixed (rule-based/"PID-held") baseline.

Closed-loop results are SIMULATION-ONLY evidence of controller behaviour on the
model itself.  They are not plant savings and must never be quoted as such.
"""
from __future__ import annotations

import copy

import numpy as np
from scipy.optimize import minimize

from app.control.constraints import MPCSettings, default_mvs, limits_from_config
from app.control.mpc import OI, SupervisoryMPC
from app.control.reduced_model import apply_u_to_config
from app.physics.finite_volume import KilnModel
from app.physics.postprocess import summarize
from app.physics.steady_state import solve_steady
from app.physics.transient import apply_change, quick_kpis


def pareto_front(sur, cfg, u_now, n_points: int = 15):
    """Coal-vs-metallization trade-off on the nonlinear surrogate, subject to
    bed/shell envelopes and actuator ranges (steady end points only)."""
    lim = limits_from_config(cfg)
    mvs = default_mvs(cfg, sur.baseline)
    bnds = [(max(mv.lo, sur.lo[j]), min(mv.hi, sur.hi[j])) for j, mv in enumerate(mvs)]
    pts = []
    for w in np.linspace(0.0, 1.0, n_points):
        def f(x):
            u = u_now.copy()
            u[:5] = x
            y = sur.predict(u)[0]
            coal = (u[1] + u[2]) * 1000 / max(y[OI["dri_t_h"]], 1e-6)
            pen = 1e3 * (max(y[OI["peak_bed_T_C"]] - lim.bed_T_max, 0) / 10) ** 2 + \
                1e3 * (max(y[OI["peak_shell_T_C"]] - lim.shell_T_max, 0) / 10) ** 2
            return w * coal / 1000 - (1 - w) * y[OI["metallization_pct"]] / 10 + pen
        r = minimize(f, u_now[:5], method="SLSQP", bounds=bnds, options={"maxiter": 150})
        u = u_now.copy()
        u[:5] = r.x
        y = sur.predict(u)[0]
        pts.append({"weight_coal": float(w), "coal_kg_per_t_dri": float((u[1] + u[2]) * 1000 / max(y[OI["dri_t_h"]], 1e-6)),
                    "metallization_pct": float(y[OI["metallization_pct"]]), "accretion_risk": float(y[OI["accretion_risk_max"]]),
                    "dri_t_h": float(y[OI["dri_t_h"]]), "peak_bed_T_C": float(y[OI["peak_bed_T_C"]]),
                    "u": [float(v) for v in r.x], "success": bool(r.success)})
    # keep non-dominated points (min coal, max metallization)
    nd = []
    for p in pts:
        dominated = any(q["coal_kg_per_t_dri"] <= p["coal_kg_per_t_dri"] and q["metallization_pct"] >= p["metallization_pct"]
                        and (q["coal_kg_per_t_dri"] < p["coal_kg_per_t_dri"] or q["metallization_pct"] > p["metallization_pct"])
                        for q in pts)
        p["non_dominated"] = not dominated
        nd.append(p)
    return {"points": nd, "basis": "nonlinear surrogate steady states (model-projected)",
            "variables": [mv.name for mv in mvs]}


def verify_with_physics(cfg, u, warm=None) -> dict:
    """Run the detailed steady physics at the recommended point."""
    c = apply_u_to_config(cfg, u)
    m = KilnModel(c)
    m.initial_state()
    st = solve_steady(m)
    r = summarize(m, st.__dict__)
    k = r["kpi"]
    return {"converged": st.converged, "solver": st.message, "kpi": {
        "metallization_pct": k["metallization_pct"], "dri_t_h": k["dri_t_h"], "peak_bed_T_C": k["peak_bed_T_C"],
        "exit_gas_T_C": k["exit_gas_T_C"], "peak_shell_T_C": k["peak_shell_T_C"],
        "accretion_risk_max": k["accretion_risk_max"], "coal_kg_per_t_dri": k["coal_kg_per_t_dri"],
        "char_C_discharge_t_h": k["char_C_discharge_t_h"], "FeO_pct": k["FeO_pct"]}, "warnings": r["warnings"]}


def closed_loop(cfg, sur, dyn, hours: float = 12.0, interval_min: float = 60.0, disturbance: dict | None = None,
                scenario: str = "multiobjective", use_mpc: bool = True, base_state=None, progress=None) -> dict:
    """Plant = detailed transient physics.  Controller = receding-horizon MPC
    (re-solved each interval with bias update from the 'measured' plant) or a
    fixed baseline that holds setpoints (local PID loops assumed to hold flows)."""
    disturbance = disturbance or {"t_h": 1.0, "changes": {"kinetics.gasification_multiplier": 0.85}}
    c = copy.deepcopy(cfg)
    m = KilnModel(c)
    if base_state is None:
        m.initial_state()
        solve_steady(m)
    else:
        m.initial_state()
        for k, v in base_state.items():
            setattr(m.state, k, np.array(v))
        m.state.Hs = (m.ms.h_s(m.state.Ts) * m.state.n).sum(0)
        solve_steady(m, warm_start=True, min_steps=60)
    m.state.t = 0.0
    m.logs = []
    ref_tubes = [t.flow_nm3h for t in c.air.secondary_tubes]
    settings = MPCSettings(interval_min=30.0, Np=16, Nc=3, scenario=scenario)
    dt = c.numerics.dt_s
    steps_per = int(interval_min * 60 / dt)
    n_int = int(hours * 60 / interval_min)
    u = np.array([c.pellet.feed_tph, c.coal.feed_coal_tph, c.coal.injection_coal_tph, 1.0, c.geometry.rpm,
                  c.kinetics.gasification_multiplier, c.kinetics.reduction_multiplier, c.pellet.moisture_wt_pct])
    traj, decisions = [], []
    dist_done = False
    for k in range(n_int):
        t_h = m.state.t / 3600
        if not dist_done and t_h >= disturbance["t_h"]:
            for p, v in disturbance["changes"].items():
                apply_change(m, p, v)
            m.refresh_inputs()
            dist_done = True
        q = quick_kpis(m)
        if use_mpc and k > 0:
            # controller knows MVs; DVs are NOT known (unmeasured) -> bias handles mismatch
            y_meas = {"metallization_pct": q["metallization_discharge_pct"], "peak_bed_T_C": q["peak_bed_T_C"],
                      "exit_gas_T_C": q["exit_gas_T_C"], "peak_shell_T_C": q["peak_shell_T_C"], "dri_t_h": q["dri_t_h"]}
            u_ctrl = u.copy()
            u_ctrl[5:] = sur.baseline[5:]
            r = SupervisoryMPC(sur, dyn, c, settings).recommend(u_ctrl, y_meas, scenario)
            first = np.array([mv["schedule"][0] for mv in r["moves"]])
            u[:5] = first
            c2 = apply_u_to_config(m.cfg, np.concatenate([u[:5], [m.cfg.kinetics.gasification_multiplier,
                                                                    m.cfg.kinetics.reduction_multiplier,
                                                                    m.cfg.pellet.moisture_wt_pct]]), ref_tubes)
            m.cfg.pellet.feed_tph, m.cfg.coal.feed_coal_tph = c2.pellet.feed_tph, c2.coal.feed_coal_tph
            m.cfg.coal.injection_coal_tph, m.cfg.geometry.rpm = c2.coal.injection_coal_tph, c2.geometry.rpm
            for t_old, t_new in zip(m.cfg.air.secondary_tubes, c2.air.secondary_tubes):
                t_old.flow_nm3h = t_new.flow_nm3h
            m.refresh_inputs()
            decisions.append({"t_h": t_h, "moves": {mv["mv"]: mv["schedule"][0] for mv in r["moves"]},
                              "solver_ok": r["solver"]["success"]})
        for _ in range(steps_per):
            m.step(dt, 1.0, log=False)
        q = quick_kpis(m)
        q["specific_coal_kg_t"] = q["coal_tph"] * 1000 / max(q["dri_t_h"], 1e-6)
        traj.append(q)
        if progress:
            progress((k + 1) / n_int, q)
    lim = limits_from_config(c)
    mets = np.array([t["metallization_discharge_pct"] for t in traj])
    return {"controller": "MPC (receding horizon)" if use_mpc else "fixed setpoints (rule-based hold)",
            "trajectory": traj, "decisions": decisions, "disturbance": disturbance,
            "summary": {"mean_metallization": float(mets.mean()), "min_metallization": float(mets.min()),
                        "time_below_min_h": float((mets < lim.met_min).sum() * interval_min / 60),
                        "mean_specific_coal": float(np.mean([t["specific_coal_kg_t"] for t in traj])),
                        "max_peak_bed_T_C": float(max(t["peak_bed_T_C"] for t in traj))},
            "label": "SIMULATION ONLY - controller behaviour on the model; not a plant benefit claim"}
