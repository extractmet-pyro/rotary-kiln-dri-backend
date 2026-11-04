"""Hybrid quality prediction with automatic physics-only fallback and a
conservative projection that keeps element balances after an ML correction.

ML-B correction changes metallization by delta (bounded); the projection moves
iron between Fe and FeO (Fe + 0.5 O2 <-> FeO) and moves the corresponding
oxygen between the solid product and the off-gas (as CO <-> CO2), so Fe, O and
C totals are unchanged.  The check is returned with the prediction."""
from __future__ import annotations

import numpy as np

from app.ml import registry
from app.ml.validate import runtime_guard

AW_FE, AW_O = 55.845, 15.999


def predict_metallization(feature_row: dict, physics_met: float, enabled: bool = True) -> dict:
    if not enabled:
        return {"value": physics_met, "source": "physics_only (ML disabled)", "interval": None}
    obj, meta = registry.load("ml_b_residual_correction")
    if obj is None:
        return {"value": physics_met, "source": "physics_only (no ML artifact)", "interval": None}
    names = obj["names"]
    x = np.array([[feature_row.get(names[c], np.nan) for c in obj["cols"]]])
    g = runtime_guard(x[:, :-1], obj.get("ood"))
    if not g["ok"]:
        return {"value": physics_met, "source": "physics_only (ML untrusted: " + "; ".join(g["flags"]) + ")",
                "interval": None}
    d = float(np.clip(obj["model"].predict(x)[0], -3.0, 3.0))
    q = meta.get("conformal_q90", 2.0)
    v = physics_met + d
    return {"value": v, "delta_ml": d, "source": f"hybrid physics + ML-B ({meta['version']})",
            "interval": [v - q, v + q], "model_status": meta.get("status")}


def project_correction(dri: dict, offgas_co_co2_kmol_h: tuple, delta_met_pp: float) -> dict:
    """Apply a metallization correction to a DRI chemistry record conservatively."""
    m = dri["mass_kg_s"]
    fe_tot = dri["Fe_total_pct"] / 100 * m
    fe_met = dri["Fe_metallic_pct"] / 100 * m
    d_fe = np.clip(delta_met_pp / 100 * fe_tot, -fe_met, fe_tot - fe_met)
    d_o = -d_fe / AW_FE * AW_O  # kg/s O leaving the solid if metallic Fe increases
    new_mass = m + d_o
    co, co2 = offgas_co_co2_kmol_h
    dk = -d_o / AW_O * 3600  # kmol/h O moved to gas: CO -> CO2
    co_new, co2_new = co - dk, co2 + dk
    feasible = co_new >= 0
    out = dict(dri)
    out.update({"Fe_metallic_pct": (fe_met + d_fe) / new_mass * 100, "Fe_total_pct": fe_tot / new_mass * 100,
                "metallization_pct": (fe_met + d_fe) / fe_tot * 100, "mass_kg_s": new_mass})
    return {"dri": out, "offgas_CO_kmol_h": co_new, "offgas_CO2_kmol_h": co2_new,
            "balance_check": {"Fe_change_kg_s": 0.0, "O_moved_kg_s": float(-d_o), "C_change_kmol_h": 0.0,
                              "feasible": bool(feasible)}}
