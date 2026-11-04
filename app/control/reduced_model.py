"""Reduced-order surrogate of the steady physics model for MPC and estimation.

Form: full quadratic response surface (ridge-regularised) in normalised
inputs x in [-1, 1], fitted to a Latin-hypercube design of converged
first-principles steady states (scripts/build_surrogate.py).  Fidelity is
reported as leave-one-out RMSE per output and must be quoted alongside every
MPC prediction.  Outside the design hull the surrogate is flagged
out-of-domain and recommendations are blocked by the safety gates.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations_with_replacement
from pathlib import Path

import numpy as np

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

INPUTS = [
    # name, unit, kind (MV/DV), how it maps into the plant config
    ("pellet_tph", "t/h", "MV"),
    ("feed_coal_tph", "t/h", "MV"),
    ("injection_coal_tph", "t/h", "MV"),
    ("secondary_air_scale", "-", "MV"),
    ("rpm", "rev/min", "MV"),
    ("gasification_multiplier", "-", "DV"),
    ("reduction_multiplier", "-", "DV"),
    ("pellet_moisture_pct", "wt %", "DV"),
]
OUTPUTS = ["metallization_pct", "dri_t_h", "peak_bed_T_C", "exit_gas_T_C", "char_C_discharge_t_h",
           "peak_shell_T_C", "exit_O2_vol_pct_dry", "accretion_risk_max", "FeO_pct", "C_pct", "steam_t_h"]


def quad_features(x: np.ndarray) -> np.ndarray:
    x = np.atleast_2d(x)
    n, d = x.shape
    cols = [np.ones(n)] + [x[:, i] for i in range(d)]
    cols += [x[:, i] * x[:, j] for i, j in combinations_with_replacement(range(d), 2)]
    return np.column_stack(cols)


@dataclass
class Surrogate:
    preset: str
    lo: np.ndarray
    hi: np.ndarray
    baseline: np.ndarray
    coef: np.ndarray  # (n_features, n_outputs)
    y_mean: np.ndarray
    y_std: np.ndarray
    loo_rmse: np.ndarray
    n_runs: int
    meta: dict

    @property
    def input_names(self):
        return [i[0] for i in INPUTS]

    def normalise(self, u):
        return 2 * (np.asarray(u, dtype=float) - self.lo) / (self.hi - self.lo) - 1

    def predict(self, u) -> np.ndarray:
        x = self.normalise(u)
        z = quad_features(x) @ self.coef
        return z * self.y_std + self.y_mean

    def predict_dict(self, u) -> dict:
        y = self.predict(u)[0]
        return {k: float(v) for k, v in zip(OUTPUTS, y)}

    def jacobian(self, u, eps=1e-4):
        u = np.asarray(u, dtype=float)
        y0 = self.predict(u)[0]
        J = np.zeros((len(OUTPUTS), len(u)))
        for i in range(len(u)):
            du = eps * (self.hi[i] - self.lo[i])
            up = u.copy()
            up[i] += du
            J[:, i] = (self.predict(up)[0] - y0) / du
        return J

    def domain_check(self, u, margin=0.05) -> dict:
        x = self.normalise(u)
        out = np.abs(x) > 1 + margin
        return {"in_domain": bool(not out.any()),
                "violations": [self.input_names[i] for i in np.where(out)[0]],
                "max_abs_normalised": float(np.max(np.abs(x)))}

    def to_json(self) -> dict:
        return {"preset": self.preset, "inputs": INPUTS, "outputs": OUTPUTS, "lo": self.lo.tolist(), "hi": self.hi.tolist(),
                "baseline": self.baseline.tolist(), "coef": self.coef.tolist(), "y_mean": self.y_mean.tolist(),
                "y_std": self.y_std.tolist(), "loo_rmse": self.loo_rmse.tolist(), "n_runs": self.n_runs, "meta": self.meta}

    @classmethod
    def from_json(cls, d: dict) -> "Surrogate":
        return cls(d["preset"], np.array(d["lo"]), np.array(d["hi"]), np.array(d["baseline"]), np.array(d["coef"]),
                   np.array(d["y_mean"]), np.array(d["y_std"]), np.array(d["loo_rmse"]), d["n_runs"], d.get("meta", {}))


def fit_surrogate(X: np.ndarray, Y: np.ndarray, lo, hi, baseline, preset: str, alpha: float = 1e-2,
                  meta: dict | None = None) -> Surrogate:
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    x = 2 * (X - lo) / (hi - lo) - 1
    Phi = quad_features(x)
    y_mean, y_std = Y.mean(0), Y.std(0) + 1e-9
    Z = (Y - y_mean) / y_std
    P = Phi.shape[1]
    reg = alpha * np.eye(P)
    reg[0, 0] = 0.0
    A = Phi.T @ Phi + reg
    coef = np.linalg.solve(A, Phi.T @ Z)
    # leave-one-out via hat matrix (exact for ridge)
    H = Phi @ np.linalg.solve(A, Phi.T)
    resid = Z - Phi @ coef
    loo = resid / np.maximum(1 - np.diag(H), 1e-6)[:, None]
    loo_rmse = np.sqrt((loo ** 2).mean(0)) * y_std
    return Surrogate(preset, lo, hi, np.asarray(baseline, float), coef, y_mean, y_std, loo_rmse, len(X), meta or {})


LOGIT = {"metallization_pct": (40.0, 100.2)}


def _tr(name, y):
    if name in LOGIT:
        a, b = LOGIT[name]
        y = np.clip(y, a + 1e-3, b - 1e-3)
        return np.log((y - a) / (b - y))
    return y


def _itr(name, z):
    if name in LOGIT:
        a, b = LOGIT[name]
        return a + (b - a) / (1 + np.exp(-z))
    return z


class GPSurrogate(Surrogate):
    """Gaussian-process response surface (ARD RBF + white noise) per output,
    with a logit transform for metallization (saturates near 100 %).  Same
    interface as the quadratic surrogate plus local predictive std."""

    def __init__(self, preset, lo, hi, baseline, gps, mus, sds, kfold_rmse, n_runs, meta):
        super().__init__(preset, np.asarray(lo), np.asarray(hi), np.asarray(baseline), np.zeros((1, 1)),
                         np.zeros(len(OUTPUTS)), np.ones(len(OUTPUTS)), np.asarray(kfold_rmse), n_runs, meta)
        self.gps, self.mus, self.sds = gps, np.asarray(mus), np.asarray(sds)

    def predict(self, u):
        x = np.atleast_2d(self.normalise(u))
        cols = []
        for i, name in enumerate(OUTPUTS):
            z = self.gps[i].predict(x) * self.sds[i] + self.mus[i]
            cols.append(_itr(name, z))
        return np.column_stack(cols)

    def predict_std(self, u):
        x = np.atleast_2d(self.normalise(u))
        out = []
        for i, name in enumerate(OUTPUTS):
            m, s = self.gps[i].predict(x, return_std=True)
            z = m * self.sds[i] + self.mus[i]
            zs = s * self.sds[i]
            if name in LOGIT:  # delta method
                a, b = LOGIT[name]
                e = np.exp(-z)
                out.append((b - a) * e / (1 + e) ** 2 * zs)
            else:
                out.append(zs)
        return np.column_stack(out)


def fit_gp_surrogate(X, Y, lo, hi, baseline, preset, meta=None, folds=6, seed=0):
    import warnings

    from sklearn.exceptions import ConvergenceWarning
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel
    from sklearn.model_selection import KFold
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    x = 2 * (X - lo) / (hi - lo) - 1
    d = X.shape[1]

    def make():
        k = ConstantKernel(1.0, (1e-3, 1e3)) * RBF(np.ones(d), (0.05, 200.0)) + WhiteKernel(1e-2, (1e-8, 1.0))
        return GaussianProcessRegressor(k, n_restarts_optimizer=2, random_state=seed)
    gps, mus, sds, rmse = [], [], [], []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        for i, name in enumerate(OUTPUTS):
            z = _tr(name, Y[:, i])
            errs = []
            for tr, te in KFold(folds, shuffle=True, random_state=seed).split(x):
                mu, sd = z[tr].mean(), z[tr].std() + 1e-12
                g = make().fit(x[tr], (z[tr] - mu) / sd)
                errs += list(_itr(name, g.predict(x[te]) * sd + mu) - Y[te, i])
            rmse.append(float(np.sqrt(np.mean(np.square(errs)))))
            mu, sd = z.mean(), z.std() + 1e-12
            gps.append(make().fit(x, (z - mu) / sd))
            mus.append(mu)
            sds.append(sd)
    return GPSurrogate(preset, lo, hi, baseline, gps, mus, sds, rmse, len(X),
                       {**(meta or {}), "model": "GP ARD-RBF + white noise; logit(metallization)",
                        "fidelity_metric": f"{folds}-fold CV RMSE (stored as loo_rmse field)"})


_CACHE: dict = {}


def load_surrogate(preset: str = "RK-100TPD") -> Surrogate | None:
    if preset in _CACHE:
        return _CACHE[preset]
    import joblib
    for name in (f"surrogate_gp_{preset}.joblib", "surrogate_gp_RK-100TPD.joblib"):
        p = FIXTURES / name
        if p.exists():
            s = joblib.load(p)
            _CACHE[preset] = s
            return s
    p = FIXTURES / f"surrogate_{preset}.json"
    if not p.exists():
        p = FIXTURES / "surrogate_RK-100TPD.json"
        if not p.exists():
            return None
    s = Surrogate.from_json(json.loads(p.read_text()))
    _CACHE[preset] = s
    return s


def config_to_u(cfg) -> np.ndarray:
    """Map a PlantConfig to the surrogate input vector."""
    base_tubes = sum(t.flow_nm3h for t in cfg.air.secondary_tubes)
    ref = cfg.meta.model_extra.get("ref_secondary_air", base_tubes) if hasattr(cfg.meta, "model_extra") and \
        cfg.meta.model_extra else base_tubes
    return np.array([cfg.pellet.feed_tph, cfg.coal.feed_coal_tph, cfg.coal.injection_coal_tph,
                     base_tubes / max(ref, 1e-9), cfg.geometry.rpm, cfg.kinetics.gasification_multiplier,
                     cfg.kinetics.reduction_multiplier, cfg.pellet.moisture_wt_pct])


def apply_u_to_config(cfg, u, ref_tubes: list | None = None):
    """Write MV/DV vector into a config copy (secondary air scales the reference tube flows)."""
    c = cfg.model_copy(deep=True)
    c.pellet.feed_tph = float(u[0])
    c.coal.feed_coal_tph = float(u[1])
    c.coal.injection_coal_tph = float(u[2])
    tubes = ref_tubes or [t.flow_nm3h for t in cfg.air.secondary_tubes]
    for t, f in zip(c.air.secondary_tubes, tubes):
        t.flow_nm3h = float(min(f * u[3], t.max_nm3h))
    c.geometry.rpm = float(u[4])
    c.kinetics.gasification_multiplier = float(u[5])
    c.kinetics.reduction_multiplier = float(u[6])
    c.pellet.moisture_wt_pct = float(u[7])
    return c
