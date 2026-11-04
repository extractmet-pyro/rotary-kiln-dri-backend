"""Dynamic forward simulation with scheduled operating changes.

Starts from a converged steady state (initialisation from steady state), then
marches the same conservative operator with true wall heat capacity.  Records
time trajectories at the requested output interval plus per-step conservation
residuals.  Feed *chemistry* changes that alter pseudo-species definitions are
rejected in-run (a new steady state must be computed instead).
"""
from __future__ import annotations

import time

import numpy as np

from app.core.exceptions import InputValidationError
from app.core.units import kmolps_to_nm3h
from app.physics.finite_volume import KilnModel
from app.physics.species import GI, SI

ALLOWED_DYNAMIC = {
    "pellet.feed_tph", "pellet.moisture_wt_pct", "coal.feed_coal_tph", "coal.injection_coal_tph",
    "flux.dolomite_tph", "geometry.rpm", "air.primary_air_nm3h", "air.injection_carrier_air_nm3h",
    "air.leak_feed_end_nm3h", "air.leak_discharge_end_nm3h", "air.air_temperature_C", "air.ambient_temperature_C",
    "kinetics.reduction_multiplier", "kinetics.gasification_multiplier", "heat.shell_loss_multiplier",
    "air.secondary_air_scale",
}


def apply_change(model: KilnModel, path: str, value):
    cfg = model.cfg
    if path.startswith("air.tube."):
        tid = path.split(".")[2]
        for t in cfg.air.secondary_tubes:
            if t.tube_id == tid:
                t.flow_nm3h = float(min(max(value, 0.0), t.max_nm3h))
                return
        raise InputValidationError(f"unknown air tube {tid}")
    if path == "air.secondary_air_scale":
        for t in cfg.air.secondary_tubes:
            base = getattr(t, "_base", None)
            if base is None:
                object.__setattr__(t, "_base", t.flow_nm3h)
                base = t.flow_nm3h
            t.flow_nm3h = float(min(max(base * value, 0.0), t.max_nm3h))
        return
    if path not in ALLOWED_DYNAMIC:
        raise InputValidationError(f"'{path}' cannot be changed during a transient run")
    sec, key = path.split(".")
    obj = getattr(cfg, sec)
    setattr(obj, key, float(value))
    g = cfg.geometry
    if not (g.rpm_min <= g.rpm <= g.rpm_max):
        raise InputValidationError("rpm outside configured limits")


def quick_kpis(model: KilnModel) -> dict:
    st, d, ms = model.state, model.diag, model.ms
    out = d.out_flow
    fe_t = 2 * out[SI["Fe2O3"]] + 3 * out[SI["Fe3O4"]] + out[SI["FeO"]] + out[SI["Fe"]]
    met = out[SI["Fe"]] / max(fe_t, 1e-12) * 100
    dri = sum(out[SI[k]] * ms.mw_s[SI[k]] for k in ("Fe2O3", "Fe3O4", "FeO", "Fe", "GANGUE", "FeS")) * 3.6
    F = st.F[:, 0]
    dry = max(F.sum() - F[GI["H2O"]], 1e-12)
    n = st.n
    fe_b = 2 * n[SI["Fe2O3"]] + 3 * n[SI["Fe3O4"]] + n[SI["FeO"]] + n[SI["Fe"]]
    met_prof = n[SI["Fe"]] / np.maximum(fe_b, 1e-12) * 100
    return {
        "t_h": st.t / 3600.0,
        "metallization_discharge_pct": float(met), "dri_t_h": float(dri),
        "char_C_discharge_t_h": float(out[SI["C"]] * 12.011 * 3.6),
        "exit_gas_T_C": float(st.Tg[0] - 273.15), "exit_CO_pct_dry": float(F[GI["CO"]] / dry * 100),
        "exit_CO2_pct_dry": float(F[GI["CO2"]] / dry * 100), "exit_O2_pct_dry": float(F[GI["O2"]] / dry * 100),
        "exit_gas_Nm3h": float(kmolps_to_nm3h(F.sum())),
        "peak_bed_T_C": float(st.Ts.max() - 273.15), "z_peak_bed_m": float(model.zc[int(np.argmax(st.Ts))]),
        "peak_gas_T_C": float(st.Tg.max() - 273.15), "peak_shell_T_C": float(d.T_shell.max() - 273.15),
        "discharge_bed_T_C": float(st.Ts[-1] - 273.15), "mid_kiln_metallization_pct": float(met_prof[model.N // 2]),
        "holdup_t": float((ms.mw_s @ n).sum() / 1000),
        "shell_loss_kW": float(d.Q_shell.sum() / 1e3),
        "coal_tph": model.cfg.coal.feed_coal_tph + model.cfg.coal.injection_coal_tph,
        "pellet_tph": model.cfg.pellet.feed_tph, "rpm": model.cfg.geometry.rpm,
        "secondary_air_nm3h": float(sum(t.flow_nm3h for t in model.cfg.air.secondary_tubes)),
    }


def run_transient(model: KilnModel, duration_min: float, output_interval_min: float = 5.0, schedule=None,
                  dt_s: float | None = None, progress=None, max_wall_s: float = 900.0) -> dict:
    dt = dt_s or model.cfg.numerics.dt_s
    schedule = sorted(schedule or [], key=lambda e: e["t_min"])
    n_steps = int(round(duration_min * 60 / dt))
    out_every = max(int(round(output_interval_min * 60 / dt)), 1)
    t_start = model.state.t
    series, profiles, residuals, events = [], [], [], []
    si = 0
    wall0 = time.time()
    status = "completed"
    for k in range(1, n_steps + 1):
        t_rel_min = (model.state.t - t_start) / 60.0
        while si < len(schedule) and schedule[si]["t_min"] <= t_rel_min + 1e-9:
            ev = schedule[si]
            for path, val in ev["changes"].items():
                apply_change(model, path, val)
            model.refresh_inputs()
            events.append({"t_min": ev["t_min"], "changes": ev["changes"]})
            si += 1
        st = model.step(dt, 1.0, log=True)
        if not (np.all(np.isfinite(st.Ts)) and np.all(np.isfinite(st.Tg))):
            status = "failed: non-finite state"
            break
        lg = model.logs[-1]
        residuals.append({"t_h": (st.t - t_start) / 3600, "mass_rel": abs(lg.mass_in - lg.mass_out - lg.accum) / max(lg.mass_in, 1e-9),
                          "energy_rel": abs(lg.H_in - lg.H_out - lg.Q_loss - lg.H_accum) / max(abs(lg.H_in) + abs(lg.H_out), 1e-9),
                          "Fe_rel": float(abs(lg.el_in[0] - lg.el_out[0] - lg.el_accum[0]) / max(lg.el_in[0], 1e-12))})
        if k % out_every == 0 or k == n_steps:
            q = quick_kpis(model)
            q["t_h"] = (st.t - t_start) / 3600.0
            series.append(q)
            profiles.append({"t_h": q["t_h"], "T_bed_C": [round(float(x) - 273.15, 1) for x in st.Ts],
                             "T_gas_C": [round(float(x) - 273.15, 1) for x in st.Tg],
                             "T_shell_C": [round(float(x) - 273.15, 1) for x in model.diag.T_shell]})
            if progress:
                progress(k / n_steps, q)
        if time.time() - wall0 > max_wall_s:
            status = f"stopped: wall-time cap {max_wall_s:.0f} s reached at t={(st.t - t_start)/3600:.2f} h"
            break
    mx = {key: max(r[key] for r in residuals) for key in ("mass_rel", "energy_rel", "Fe_rel")} if residuals else {}
    return {"status": status, "series": series, "profiles": profiles[-48:] if len(profiles) > 48 else profiles,
            "events": events, "max_step_residuals": mx, "wall_time_s": time.time() - wall0, "dt_s": dt,
            "residual_trace": residuals[:: max(len(residuals) // 200, 1)]}
