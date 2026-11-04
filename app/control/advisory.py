"""Advisory workflow: scenario ranking, recommendation records, operator
decisions (approve/reject with mandatory note), override handling.

"Approve recommendation" records an auditable decision ONLY.  There is no code
path from this module (or anywhere in this repository) to a PLC/DCS write.
"""
from __future__ import annotations

import numpy as np

from app.control.constraints import SCENARIO_WEIGHTS, MPCSettings
from app.control.mpc import SupervisoryMPC
from app.control.safety_gates import evaluate_gates


def rank_scenarios(sur, dyn, cfg, u_now, y_meas=None, scenarios=None, locked=None, mode="OFFLINE_SIMULATION",
                   data_ts=None, settings: MPCSettings | None = None):
    """Solve each scenario and rank by a common, transparent scorecard."""
    out = []
    for sc in scenarios or list(SCENARIO_WEIGHTS):
        s = settings or MPCSettings()
        s = MPCSettings(interval_min=s.interval_min, Np=s.Np, Nc=s.Nc, weights={}, scenario=sc)
        r = SupervisoryMPC(sur, dyn, cfg, s).recommend(u_now, y_meas, sc, locked)
        g = evaluate_gates(mode, r, data_ts)
        d = r["expected_deltas"]
        score = (0.5 * d["metallization_pp"] - 0.01 * d["coal_kg_per_t_dri"] + 0.8 * d["dri_t_h"]
                 - 2.0 * max(d["accretion_risk"], 0) - 0.01 * max(d["peak_bed_T_C"], 0))
        out.append({"scenario": sc, "score": float(score), "actionable": g["actionable"], "gates": g,
                    "expected_deltas": d, "explanation": r["explanation"], "result": r})
    out.sort(key=lambda x: (not x["actionable"], -x["score"]))
    for i, o in enumerate(out):
        o["rank"] = i + 1
    return out


ALLOWED_DECISIONS = {"approve", "reject", "defer"}


def validate_decision(decision: str, note: str, role: str, rec_status: str) -> list:
    errs = []
    if decision not in ALLOWED_DECISIONS:
        errs.append(f"decision must be one of {sorted(ALLOWED_DECISIONS)}")
    if not note or len(note.strip()) < 5:
        errs.append("a decision note (>= 5 characters) is mandatory")
    if role not in ("operator", "process_engineer", "approver", "administrator", "metallurgist"):
        errs.append(f"role '{role}' may not decide on recommendations")
    if decision == "approve" and rec_status != "RECOMMENDATION_AVAILABLE":
        errs.append("cannot approve a recommendation that failed safety gates")
    return errs


def summarise_moves(moves: list) -> list:
    return [{"mv": m["mv"], "from": round(m["current"], 4), "to": round(m["recommended"], 4), "unit": m["unit"]}
            for m in moves if abs(m["delta"]) > 1e-6]


def uncertainty_score(rec: dict) -> float:
    e = rec.get("model_error_95", {})
    return float(np.clip(1.0 - e.get("metallization_pct", 3.0) / 6.0, 0.0, 1.0))
