"""Steady counter-current solution by pseudo-transient continuation.

The same conservative finite-volume operator as the transient solver is
marched with an accelerated wall (thermal capacity scaled by
`steady_wall_capacity_factor`, which does not change the steady solution) until
max |dT/dt| of bed, gas and wall and the relative solids-inventory drift fall
below tolerance.  This handles the two-point (counter-current) boundary
problem without a shooting method.  Non-convergence is reported, never hidden.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from app.physics.finite_volume import KilnModel


@dataclass
class SolverStatus:
    converged: bool
    steps: int
    simulated_h: float
    wall_time_s: float
    max_dTdt_K_per_h: float
    max_rel_mass_drift_per_h: float
    history: list = field(default_factory=list)
    message: str = ""


def solve_steady(model: KilnModel, max_steps: int | None = None, tol_K_h: float | None = None,
                 warm_start: bool = False, progress=None, min_steps: int = 150) -> SolverStatus:
    num = model.cfg.numerics
    dt = num.steady_dt_s
    cap = num.steady_wall_capacity_factor
    max_steps = max_steps or num.steady_max_steps
    tol = tol_K_h or num.steady_tol_K_per_h
    if model.state is None or not warm_start:
        model.initial_state()
    t0 = time.time()
    hist = []
    dTmax, dm = np.inf, np.inf
    window = 20
    Ts_hist, Tg_hist, Tw_hist, M_hist = [], [], [], []
    k = 0
    for k in range(1, max_steps + 1):
        st = model.step(dt, cap, log=(k % 5 == 0))
        if not (np.all(np.isfinite(st.Ts)) and np.all(np.isfinite(st.Tg))):
            return SolverStatus(False, k, k * dt / 3600, time.time() - t0, float("nan"), float("nan"), hist,
                                "non-finite state (NaN/Inf) - run rejected")
        Ts_hist.append(st.Ts.copy())
        Tg_hist.append(st.Tg.copy())
        Tw_hist.append(st.Tw[:, 0].copy())
        M_hist.append(float((model.ms.mw_s @ st.n).sum()))
        if len(Ts_hist) > window:
            Ts_hist.pop(0), Tg_hist.pop(0), Tw_hist.pop(0), M_hist.pop(0)
        if k % window == 0 and len(Ts_hist) == window:
            span_h = (window - 1) * dt / 3600.0
            dTmax = max(np.max(np.abs(Ts_hist[-1] - Ts_hist[0])), np.max(np.abs(Tg_hist[-1] - Tg_hist[0])),
                        np.max(np.abs(Tw_hist[-1] - Tw_hist[0]))) / span_h
            dm = abs(M_hist[-1] - M_hist[0]) / max(M_hist[-1], 1e-9) / span_h
            hist.append({"step": k, "t_h": k * dt / 3600, "max_dTdt_K_h": float(dTmax), "mass_drift_per_h": float(dm),
                         "Ts_peak_C": float(st.Ts.max() - 273.15), "Tg_exit_C": float(st.Tg[0] - 273.15)})
            if progress:
                progress(k / max_steps, hist[-1])
            if k >= min_steps and dTmax < tol and dm < 1e-3:
                return SolverStatus(True, k, k * dt / 3600, time.time() - t0, float(dTmax), float(dm), hist,
                                    "converged")
    return SolverStatus(False, k, k * dt / 3600, time.time() - t0, float(dTmax), float(dm), hist,
                        f"not converged within {max_steps} steps (max dT/dt {dTmax:.2f} K/h)")
