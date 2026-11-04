"""State/parameter observer: constrained extended Kalman filter.

Augmented slow states (random walk): char reactivity (gasification multiplier),
reduction-kinetics multiplier, exit-gas thermocouple bias and shell-scanner
bias.  The measurement function is the physics-derived surrogate (steady,
appropriate for the 10-30 min advisory interval); delayed laboratory
metallization is assimilated against the operating point of its RTD-aligned
feed cohort (see uncertainty.align_lab_sample).  Parameters are clipped to
documented physical bounds after each update so they cannot drift arbitrarily
and hide plant faults.  Innovation tests (NIS) flag sensor/model problems.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.stats import chi2

from app.control.reduced_model import OUTPUTS, Surrogate

OI = {k: i for i, k in enumerate(OUTPUTS)}
PARAM_NAMES = ["gasification_multiplier", "reduction_multiplier", "exit_tc_bias_C", "shell_scanner_bias_C"]
PARAM_BOUNDS = np.array([[0.6, 1.6], [0.6, 1.6], [-60.0, 60.0], [-40.0, 40.0]])
MEAS = {  # name -> (surrogate output, parameter bias index or None, default sigma)
    "EXHAUST_TEMP_C": ("exit_gas_T_C", 2, 8.0),
    "TEMP_SHELL_MAX_C": ("peak_shell_T_C", 3, 6.0),
    "EXHAUST_O2_VOLPCT_DRY": ("exit_O2_vol_pct_dry", None, 0.4),
    "LAB_METALLIZATION_PCT": ("metallization_pct", None, 1.0),
}


@dataclass
class EKFState:
    x: np.ndarray = field(default_factory=lambda: np.array([1.0, 1.0, 0.0, 0.0]))
    P: np.ndarray = field(default_factory=lambda: np.diag([0.04, 0.04, 100.0, 64.0]))
    Q: np.ndarray = field(default_factory=lambda: np.diag([1e-4, 1e-4, 0.5, 0.3]))
    history: list = field(default_factory=list)


class KilnEKF:
    def __init__(self, sur: Surrogate, state: EKFState | None = None):
        self.sur = sur
        self.s = state or EKFState()

    def _h(self, x, u, names):
        uu = np.asarray(u, float).copy()
        uu[5], uu[6] = x[0], x[1]
        y = self.sur.predict(uu)[0]
        out = []
        for nm in names:
            o, b, _ = MEAS[nm]
            out.append(y[OI[o]] + (x[b] if b is not None else 0.0))
        return np.array(out)

    def update(self, u: np.ndarray, meas: dict, t_iso: str, sigmas: dict | None = None) -> dict:
        """One predict/update cycle.  meas: {tag: value or None}; None = missing."""
        s = self.s
        # predict (random walk)
        s.P = s.P + s.Q
        names = [k for k, v in meas.items() if k in MEAS and v is not None and np.isfinite(v)]
        flags = []
        nis = None
        if names:
            z = np.array([meas[k] for k in names], float)
            R = np.diag([(sigmas or {}).get(k, MEAS[k][2]) ** 2 for k in names])
            hx = self._h(s.x, u, names)
            H = np.zeros((len(names), len(s.x)))
            for i in range(len(s.x)):
                dx = np.zeros(len(s.x))
                dx[i] = 1e-4 * max(1.0, abs(s.x[i]))
                H[:, i] = (self._h(s.x + dx, u, names) - hx) / dx[i]
            nu = z - hx
            Sm = H @ s.P @ H.T + R
            K = s.P @ H.T @ np.linalg.inv(Sm)
            nis = float(nu @ np.linalg.solve(Sm, nu))
            crit = float(chi2.ppf(0.995, df=len(names)))
            if nis > crit:
                flags.append(f"innovation test failed (NIS {nis:.1f} > {crit:.1f}): possible sensor fault or model mismatch")
                # robust: inflate R for this update instead of trusting outliers
                Sm = H @ s.P @ H.T + R * (nis / crit)
                K = s.P @ H.T @ np.linalg.inv(Sm)
            s.x = s.x + K @ nu
            s.P = (np.eye(len(s.x)) - K @ H) @ s.P
            s.P = 0.5 * (s.P + s.P.T)
        clipped = []
        for i, (lo, hi) in enumerate(PARAM_BOUNDS):
            if s.x[i] < lo or s.x[i] > hi:
                clipped.append(PARAM_NAMES[i])
            s.x[i] = float(np.clip(s.x[i], lo, hi))
        if clipped:
            flags.append(f"parameter(s) at physical bound: {clipped} - investigate plant fault before trusting")
        sd = np.sqrt(np.maximum(np.diag(s.P), 0))
        conf = float(np.clip(1.0 - (sd[0] / 0.3 + sd[1] / 0.3) / 2, 0.0, 1.0))
        rec = {"t": t_iso, "x": dict(zip(PARAM_NAMES, s.x.tolist())), "sd": dict(zip(PARAM_NAMES, sd.tolist())),
               "nis": nis, "used_measurements": names, "flags": flags, "confidence": conf}
        s.history.append(rec)
        if len(s.history) > 500:
            s.history = s.history[-500:]
        return rec
