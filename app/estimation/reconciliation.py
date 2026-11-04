"""Data reconciliation and gross-error detection.

Weighted least squares with linear balance constraints A x = 0:
    x_hat = x - S A^T (A S A^T)^-1 A x ,  S = diag(sigma^2)
Gross errors: global chi-square test on the constraint residual and the
maximum normalised measurement adjustment (Tamhane & Mah style tests).
Grossly inconsistent inputs are REJECTED (flagged), never silently adjusted.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import chi2


def reconcile(x: np.ndarray, sigma: np.ndarray, A: np.ndarray, alpha: float = 0.05) -> dict:
    x = np.asarray(x, float)
    S = np.diag(np.asarray(sigma, float) ** 2)
    r = A @ x
    V = A @ S @ A.T
    Vi = np.linalg.pinv(V)
    adj = S @ A.T @ Vi @ r
    xh = x - adj
    g = float(r @ Vi @ r)
    crit = float(chi2.ppf(1 - alpha, df=A.shape[0]))
    cov_adj = S @ A.T @ Vi @ A @ S
    z = np.abs(adj) / np.sqrt(np.maximum(np.diag(cov_adj), 1e-18))
    suspect = int(np.argmax(z)) if g > crit else None
    return {"reconciled": xh.tolist(), "adjustments": (-adj).tolist(), "constraint_residual": r.tolist(),
            "global_test": g, "critical_value": crit, "gross_error_detected": g > crit,
            "normalised_adjustments": z.tolist(), "suspect_index": suspect}


def fe_balance_reconciliation(pellet_tph, pellet_fe_pct, dri_tph, dri_fe_pct, nonmag_tph, nonmag_fe_pct,
                              dust_tph=0.0, dust_fe_pct=0.0, rel_sigma=None) -> dict:
    """Reconcile measured flows against the iron balance (Fe in = Fe out).
    Variables are Fe flows (t/h) of each stream; returns adjusted flows."""
    rel_sigma = rel_sigma or {"pellet": 0.02, "dri": 0.03, "nonmag": 0.10, "dust": 0.30}
    fe = np.array([pellet_tph * pellet_fe_pct / 100, dri_tph * dri_fe_pct / 100, nonmag_tph * nonmag_fe_pct / 100,
                   dust_tph * dust_fe_pct / 100])
    sig = np.maximum(np.abs(fe) * np.array([rel_sigma["pellet"], rel_sigma["dri"], rel_sigma["nonmag"],
                                            rel_sigma["dust"]]), 1e-6)
    A = np.array([[1.0, -1.0, -1.0, -1.0]])
    res = reconcile(fe, sig, A)
    res["streams"] = ["pellet_Fe_tph", "dri_Fe_tph", "nonmag_Fe_tph", "dust_Fe_tph"]
    res["closure_before_pct"] = float((fe[0] - fe[1:].sum()) / max(fe[0], 1e-9) * 100)
    return res
