"""Uncertainty propagation and lab-sample cohort alignment.

* Monte Carlo propagation of kinetic/heat-transfer parameter uncertainty
  through the surrogate (fast) with optional physics spot-checks.
* RTD alignment: a discharge sample taken at time t is attributed to the feed
  cohort that entered at t - tau, weighted by the axial-dispersion RTD E(t);
  the confidence interval of the cohort time follows from the RTD spread.
"""
from __future__ import annotations

import numpy as np

from app.control.reduced_model import OUTPUTS
from app.physics.bed_transport import rtd_axial_dispersion


def monte_carlo(sur, u, n=500, rel_sd=None, seed=7) -> dict:
    rel_sd = rel_sd or {"gasification_multiplier": 0.10, "reduction_multiplier": 0.10}
    rng = np.random.default_rng(seed)
    U = np.tile(np.asarray(u, float), (n, 1))
    for j, name in ((5, "gasification_multiplier"), (6, "reduction_multiplier")):
        U[:, j] = U[:, j] * (1 + rel_sd[name] * rng.standard_normal(n))
    U = np.clip(U, sur.lo, sur.hi)
    Y = sur.predict(U)
    return {k: {"mean": float(Y[:, i].mean()), "p05": float(np.percentile(Y[:, i], 5)),
                "p95": float(np.percentile(Y[:, i], 95)), "sd": float(Y[:, i].std())} for i, k in enumerate(OUTPUTS)}


def align_lab_sample(sample_time_h: float, mean_residence_h: float, peclet: float = 200.0, n=400) -> dict:
    """Return feed-cohort weights for a discharge sample."""
    ages = np.linspace(0.05, 3 * mean_residence_h, n)
    E = rtd_axial_dispersion(ages * 3600, mean_residence_h * 3600, peclet) * 3600
    E = E / np.trapezoid(E, ages)
    cdf = np.cumsum(E) * (ages[1] - ages[0])
    lo = float(np.interp(0.05, cdf, ages))
    hi = float(np.interp(0.95, cdf, ages))
    mode = float(ages[np.argmax(E)])
    return {"cohort_feed_time_h": sample_time_h - mode, "ci90_feed_time_h": [sample_time_h - hi, sample_time_h - lo],
            "rtd_age_h": ages[::10].tolist(), "rtd_E_per_h": E[::10].tolist(), "peclet": peclet}
