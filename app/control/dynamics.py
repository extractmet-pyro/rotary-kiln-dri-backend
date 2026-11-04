"""Multi-rate dynamic response model (FOPDT step responses per MV/DV -> CV).

Time constants and dead times are identified from step tests on the detailed
transient physics model (scripts/identify_dynamics.py) and stored with the
surrogate.  Steady gains come from local linearisation of the surrogate
(gain scheduling), so the prediction model is

    y(t) = y_ss(u_0) + sum_j sum_m  K_ij(u) * du_j,m * S(t - t_m - theta_ij; tau_ij)

with S(s) = 1 - exp(-s/tau) for s > 0.  Time scales: PLC loops (seconds) are
not modelled; advisory decisions are minutes; thermal dynamics 10-60 min;
solids transport hours (dead time ~ residence time for feed changes).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.control.reduced_model import INPUTS, OUTPUTS

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@dataclass
class FOPDT:
    tau_min: np.ndarray  # (n_out, n_in)
    theta_min: np.ndarray
    source: str

    def step(self, t_min: np.ndarray) -> np.ndarray:
        """Unit step response S[t, i, j]."""
        t = np.asarray(t_min, float)[:, None, None]
        s = t - self.theta_min[None]
        return np.where(s > 0, 1.0 - np.exp(-s / np.maximum(self.tau_min[None], 1e-3)), 0.0)


def default_dynamics(residence_h: float = 5.0) -> FOPDT:
    """Engineering prior used until identification is run: feed/coal/rpm act after
    a fraction of the solids residence time; air acts on gas/thermal states fast."""
    n_o, n_i = len(OUTPUTS), len(INPUTS)
    tau = np.full((n_o, n_i), 45.0)
    theta = np.full((n_o, n_i), 10.0)
    R = residence_h * 60
    solid_inputs = [0, 1, 2, 4, 7]  # pellet, coal, inj coal, rpm, moisture
    for j in solid_inputs:
        theta[:, j] = 0.15 * R
        tau[:, j] = 0.35 * R
    for i, name in enumerate(OUTPUTS):
        if name in ("metallization_pct", "dri_t_h", "FeO_pct", "C_pct", "char_C_discharge_t_h"):
            theta[i, solid_inputs] = 0.45 * R
            tau[i, :] = np.maximum(tau[i, :], 0.30 * R)
            theta[i, 3] = 0.25 * R
        if name in ("exit_gas_T_C", "exit_O2_vol_pct_dry", "steam_t_h"):
            theta[i, 3] = 1.0
            tau[i, 3] = 8.0
        if name == "peak_shell_T_C":
            tau[i, :] = np.maximum(tau[i, :], 90.0)
    return FOPDT(tau, theta, "engineering prior (not identified)")


def load_dynamics(preset: str = "RK-100TPD") -> FOPDT:
    p = FIXTURES / f"dynamics_{preset}.json"
    if not p.exists():
        p = FIXTURES / "dynamics_RK-100TPD.json"
    if p.exists():
        d = json.loads(p.read_text())
        return FOPDT(np.array(d["tau_min"]), np.array(d["theta_min"]), d.get("source", "identified"))
    return default_dynamics()


def fit_fopdt(t_min: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Fit gain, tau, theta to a step response by grid search on theta and
    closed-form least squares on gain for each tau (robust, no optimiser)."""
    y = np.asarray(y, float) - y[0]
    best = (0.0, 30.0, 0.0, np.inf)
    T = t_min[-1]
    for theta in np.linspace(0, 0.6 * T, 25):
        for tau in np.geomspace(2.0, 1.5 * T, 30):
            s = np.where(t_min > theta, 1 - np.exp(-(t_min - theta) / tau), 0.0)
            denom = s @ s
            if denom <= 0:
                continue
            K = (s @ y) / denom
            err = np.sum((y - K * s) ** 2)
            if err < best[3]:
                best = (K, tau, theta, err)
    return best[0], best[1], best[2]
