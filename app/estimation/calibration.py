"""Offline parameter identification with provenance.

Fits bounded multipliers (reduction kinetics, char gasification, shell loss,
gas-to-bed heat transfer) to reconciled steady campaign data by weighted
least squares on the detailed physics (bounded trust-region; few evaluations)
or on the surrogate (fast screening).  Every calibration produces a
provenance record: data period, objective, algorithm, before/after residuals,
author and approval status (PENDING until approved by a process engineer).
"""
from __future__ import annotations

import hashlib
import json
import time

import numpy as np
from scipy.optimize import least_squares

from app.control.reduced_model import OUTPUTS

BOUNDS = {"gasification_multiplier": (0.6, 1.6), "reduction_multiplier": (0.6, 1.6)}


def calibrate_on_surrogate(sur, campaigns: list, author: str = "unknown") -> dict:
    """campaigns: [{u: [8 values], y: {output: value}, sigma: {output: s}}]."""
    names = list(BOUNDS)
    lo = np.array([BOUNDS[n][0] for n in names])
    hi = np.array([BOUNDS[n][1] for n in names])

    def resid(p):
        r = []
        for c in campaigns:
            u = np.array(c["u"], float)
            u[5], u[6] = p
            y = sur.predict(u)[0]
            for k, v in c["y"].items():
                s = c.get("sigma", {}).get(k, 1.0)
                r.append((y[OUTPUTS.index(k)] - v) / s)
        return np.array(r)

    p0 = np.array([1.0, 1.0])
    r0 = resid(p0)
    sol = least_squares(resid, p0, bounds=(lo, hi))
    J = sol.jac
    try:
        cov = np.linalg.inv(J.T @ J) * max(1.0, (sol.fun ** 2).sum() / max(len(sol.fun) - 2, 1))
        sd = np.sqrt(np.diag(cov)).tolist()
        cond = float(np.linalg.cond(J.T @ J))
    except np.linalg.LinAlgError:
        sd, cond = [float("nan")] * 2, float("inf")
    data_hash = hashlib.sha256(json.dumps(campaigns, sort_keys=True, default=float).encode()).hexdigest()[:16]
    return {"parameters": dict(zip(names, sol.x.tolist())), "sd": dict(zip(names, sd)),
            "identifiability_condition_number": cond,
            "identifiable": bool(cond < 1e6),
            "cost_before": float((r0 ** 2).sum()), "cost_after": float((sol.fun ** 2).sum()),
            "residuals_after": sol.fun.tolist(), "algorithm": "scipy least_squares (TRF, bounded)",
            "provenance": {"data_hash": data_hash, "n_campaigns": len(campaigns), "author": author,
                           "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                           "approval": "PENDING", "objective": "weighted SSE of steady KPIs",
                           "model": "surrogate (screening) - confirm on detailed physics before approval"}}
