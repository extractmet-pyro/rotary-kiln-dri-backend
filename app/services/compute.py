"""Compute-heavy job bodies (executed in a separate worker process).

Each function takes a JSON-serialisable request and returns a JSON-
serialisable result.  Progress is written back through the `report` callback.
"""
from __future__ import annotations

import copy
import hashlib
import json

import numpy as np

from app.control.dynamics import load_dynamics
from app.control.optimizer import closed_loop, verify_with_physics
from app.control.reduced_model import INPUTS, OUTPUTS, load_surrogate
from app.core.exceptions import InputValidationError
from app.data.fixtures import baseline as baseline_fixture
from app.physics.finite_volume import KilnModel
from app.physics.postprocess import summarize
from app.physics.steady_state import solve_steady
from app.physics.transient import run_transient
from app.schemas.plant import PlantConfig, preset_config


def set_path(d: dict, path: str, value):
    """Dotted-path setter on a config dict; supports air.tube.<ID>.<field>."""
    parts = path.split(".")
    if parts[:2] == ["air", "tube"]:
        for t in d["air"]["secondary_tubes"]:
            if t["tube_id"] == parts[2]:
                t[parts[3]] = value
                return
        raise InputValidationError(f"unknown air tube {parts[2]}")
    o = d
    for p in parts[:-1]:
        if p not in o:
            raise InputValidationError(f"unknown configuration path '{path}'")
        o = o[p]
    if parts[-1] not in o:
        raise InputValidationError(f"unknown configuration key '{path}'")
    o[parts[-1]] = value


DISTURBANCE_PATHS = {
    "pellet_moisture_wt_pct": "pellet.moisture_wt_pct", "coal_reactivity_factor": "coal.feed_coal.reactivity_factor",
    "ambient_temperature_C": "air.ambient_temperature_C", "air_leak_feed_end_nm3h": "air.leak_feed_end_nm3h",
    "air_leak_discharge_end_nm3h": "air.leak_discharge_end_nm3h", "refractory_wear_fraction": "lining.wear_fraction",
    "accretion_thickness_m": "geometry.accretion_thickness_m", "gasification_multiplier": "kinetics.gasification_multiplier",
    "reduction_multiplier": "kinetics.reduction_multiplier", "pellet_diameter_mm": "pellet.diameter_mm",
    "pellet_porosity": "pellet.porosity", "relative_humidity_pct": "air.relative_humidity_pct",
}


def build_config(req: dict) -> PlantConfig:
    base = PlantConfig.model_validate(req["plant_config"]) if req.get("plant_config") else preset_config(
        req.get("preset", "RK-100TPD"))
    d = base.model_dump()
    f = req.get("feed") or {}
    m = {"pellet_feed_tph": "pellet.feed_tph", "feed_coal_tph": "coal.feed_coal_tph",
         "injected_coal_tph": "coal.injection_coal_tph", "dolomite_tph": "flux.dolomite_tph",
         "recycle_char_tph": "flux.recycle_char_tph"}
    for k, v in f.items():
        if v is not None:
            set_path(d, m[k], v)
    for k, v in (req.get("disturbances") or {}).items():
        if k not in DISTURBANCE_PATHS:
            raise InputValidationError(f"unknown disturbance '{k}'; allowed {sorted(DISTURBANCE_PATHS)}")
        set_path(d, DISTURBANCE_PATHS[k], v)
    for k, v in (req.get("overrides") or {}).items():
        set_path(d, k, v)
    sim = req.get("simulation") or {}
    if sim.get("fast"):
        d["numerics"]["n_cells"] = min(d["numerics"]["n_cells"], 24)
        d["numerics"]["steady_max_steps"] = min(d["numerics"]["steady_max_steps"], 1000)
        d["numerics"]["steady_dt_s"] = max(d["numerics"]["steady_dt_s"], 120.0)
    try:
        return PlantConfig.model_validate(d)
    except Exception as e:
        raise InputValidationError(str(e)) from e


def input_hash(req: dict) -> str:
    cfg = build_config(req)
    payload = {"cfg": cfg.model_dump(), "sim": req.get("simulation"), "v": "1.0.0"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _template(preset: str):
    b = baseline_fixture(preset)
    if not b:
        return None
    p = b["profiles"]
    L = b["geometry"]["length_m"]
    return {"zf": [z / L for z in p["z_m"]], "met": p["metallization_pct"], "Ts_C": p["T_bed_C"], "Tg_C": p["T_gas_C"]}


def steady_model(cfg: PlantConfig, preset: str, report=None):
    m = KilnModel(cfg)
    m.initial_state(template=_template(preset))
    st = solve_steady(m, warm_start=True,
                      progress=(lambda f, h: report(0.9 * f, f"steady pseudo-time {h['t_h']:.1f} h, "
                                                       f"max dT/dt {h['max_dTdt_K_h']:.1f} K/h")) if report else None)
    return m, st


def job_simulation(req: dict, report=None) -> dict:
    cfg = build_config(req)
    preset = req.get("preset", "RK-100TPD")
    sim = req.get("simulation") or {}
    m, st = steady_model(cfg, preset, report)
    if not np.all(np.isfinite(m.state.Ts)):
        raise RuntimeError("solver produced non-finite state; run rejected")
    res = summarize(m, st.__dict__, req.get("mode", "OFFLINE_SIMULATION"))
    res["scenario_name"] = req.get("scenario_name", "")
    res["simulation_type"] = sim.get("type", "steady")
    if sim.get("type") == "transient":
        m.logs = []
        tr = run_transient(m, sim.get("duration_min", 240), sim.get("output_interval_min", 10),
                           [{"t_min": e["t_min"], "changes": e["changes"]} for e in sim.get("schedule", [])],
                           progress=(lambda f, q: report(0.9 + 0.1 * f, f"transient t = {q['t_h']:.2f} h")) if report else None)
        res["transient"] = tr
        res["final_state_summary"] = summarize(m, {"transient_end": True}, req.get("mode"))["kpi"]
    return res


def job_compare(req: dict, report=None) -> dict:
    out = []
    n = len(req["scenarios"])
    for i, s in enumerate(req["scenarios"]):
        if report:
            report(i / n, f"scenario {i+1}/{n}: {s.get('scenario_name')}")
        r = job_simulation(s)
        out.append({"scenario_name": s.get("scenario_name", f"S{i+1}"), "kpi": r["kpi"],
                    "profiles": {k: r["profiles"][k] for k in ("z_m", "T_bed_C", "T_gas_C", "T_shell_C",
                                                               "metallization_pct", "char_C_kg_per_m")},
                    "heat_balance": r["heat_balance"], "warnings": r["warnings"]})
    return {"scenarios": out, "basis": "detailed physics steady states (illustrative synthetic configuration)"}


def job_sensitivity_physics(req: dict, report=None) -> dict:
    preset = req.get("preset", "RK-100TPD")
    rel = req.get("rel_step", 0.08)
    outs = req.get("outputs", ["metallization_pct", "peak_bed_T_C"])
    factors = {"pellet.feed_tph": "Pellet feed", "coal.feed_coal_tph": "Feed coal", "coal.injection_coal_tph": "Injection coal",
               "geometry.rpm": "Kiln rpm", "kinetics.gasification_multiplier": "Char reactivity",
               "pellet.moisture_wt_pct": "Pellet moisture"}
    base = job_simulation({"preset": preset})
    rows = []
    k = 0
    for path, label in factors.items():
        vals = {}
        for sgn in (-1, 1):
            cfg = preset_config(preset).model_dump()
            o = cfg
            for p in path.split(".")[:-1]:
                o = o[p]
            o[path.split(".")[-1]] *= (1 + sgn * rel)
            r = job_simulation({"plant_config": cfg, "preset": preset})
            vals[sgn] = {q: r["kpi"].get(q) for q in outs}
            k += 1
            if report:
                report(k / (2 * len(factors)), f"{label} {'+' if sgn > 0 else '-'}{rel*100:.0f} %")
        rows.append({"factor": label, "path": path, "low": vals[-1], "high": vals[1]})
    return {"method": "physics one-factor-at-a-time", "rel_step": rel, "baseline": {q: base["kpi"].get(q) for q in outs},
            "rows": rows}


def job_verify(req: dict, report=None) -> dict:
    cfg = preset_config(req.get("preset", "RK-100TPD"))
    u = np.array(req["u"], float)
    if report:
        report(0.1, "detailed physics verification of MPC end point")
    v = verify_with_physics(cfg, u)
    v["surrogate_prediction"] = req.get("surrogate_end_point")
    if v["surrogate_prediction"]:
        v["difference"] = {k: v["kpi"][k] - v["surrogate_prediction"][k] for k in v["kpi"]
                           if k in v["surrogate_prediction"]}
    return v


def job_closed_loop(req: dict, report=None) -> dict:
    preset = req.get("preset", "RK-100TPD")
    cfg = preset_config(preset)
    sur = load_surrogate(preset)
    dyn = load_dynamics(preset)
    if sur is None:
        raise RuntimeError("surrogate not available")
    dist = {"t_h": req.get("disturbance_t_h", 1.0), "changes": req.get("disturbance", {"kinetics.gasification_multiplier": 0.85})}
    a = closed_loop(cfg, sur, dyn, req.get("hours", 10), req.get("interval_min", 60), dist, req.get("scenario", "multiobjective"),
                    use_mpc=False, progress=(lambda f, q: report(0.5 * f, "baseline (fixed setpoints)")) if report else None)
    b = closed_loop(cfg, sur, dyn, req.get("hours", 10), req.get("interval_min", 60), dist, req.get("scenario", "multiobjective"),
                    use_mpc=True, progress=(lambda f, q: report(0.5 + 0.5 * f, "receding-horizon MPC")) if report else None)
    return {"baseline": a, "mpc": b, "label": a["label"]}


def job_ml_train(req: dict, report=None) -> dict:
    from app.integration.synthetic import generate_history
    from app.ml.train import train_anomaly, train_soft_sensor
    preset = "RK-100TPD"
    cfg = preset_config(preset)
    sur = load_surrogate(preset)
    b = baseline_fixture(preset)
    prof = baseline_profile_for_synth(b)
    if report:
        report(0.05, "generating synthetic plant history")
    df = generate_history(sur, prof, cfg, days=req.get("days", 14), seed=req.get("seed", 42))
    ref = {t.tube_id: t.flow_nm3h for t in cfg.air.secondary_tubes}
    if report:
        report(0.3, "training ML-A / ML-B (chronological split)")
    a = train_soft_sensor(df, sur, prof["residence_h"], ref)
    if report:
        report(0.75, "training ML-C anomaly detectors")
    c = train_anomaly(df)
    return {"soft_sensor": a, "anomaly": c, "data_banner": "SYNTHETIC DEMONSTRATION DATA - NOT PLANT MEASUREMENTS",
            "days": req.get("days", 14)}


def baseline_profile_for_synth(b: dict) -> dict:
    p = b["profiles"]
    L = b["geometry"]["length_m"]
    return {"zf": [z / L for z in p["z_m"]], "T_bed_C": p["T_bed_C"], "T_shell_C": p["T_shell_C"],
            "residence_h": b["kpi"]["residence_time_h"], "holdup_t": b["kpi"]["holdup_t"],
            "exit_CO2_dry": b["kpi"]["exit_CO2_vol_pct_dry"]}


JOBS = {"steady": job_simulation, "transient": job_simulation, "simulation": job_simulation, "compare": job_compare,
        "sensitivity": job_sensitivity_physics, "verify": job_verify, "closed_loop": job_closed_loop,
        "ml_train": job_ml_train}

__all__ = ["JOBS", "build_config", "input_hash", "INPUTS", "OUTPUTS", "copy"]
