"""Distribution-shift and out-of-distribution checks."""
from __future__ import annotations

import numpy as np


def psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    e = np.asarray(expected, float)
    a = np.asarray(actual, float)
    e, a = e[np.isfinite(e)], a[np.isfinite(a)]
    if len(e) < 10 or len(a) < 5:
        return float("nan")
    qs = np.unique(np.quantile(e, np.linspace(0, 1, bins + 1)))
    if len(qs) < 3:
        return 0.0
    pe = np.histogram(e, qs)[0] / len(e) + 1e-6
    pa = np.histogram(np.clip(a, qs[0], qs[-1]), qs)[0] / len(a) + 1e-6
    return float(np.sum((pa - pe) * np.log(pa / pe)))


class MahalanobisOOD:
    def __init__(self, X: np.ndarray):
        X = np.asarray(X, float)
        self.mu = np.nanmean(X, 0)
        Xc = np.nan_to_num(X - self.mu)
        self.cov_inv = np.linalg.pinv(np.cov(Xc.T) + 1e-6 * np.eye(X.shape[1]))
        d = np.einsum("ij,jk,ik->i", Xc, self.cov_inv, Xc)
        self.threshold = float(np.quantile(d, 0.995))

    def score(self, x: np.ndarray) -> np.ndarray:
        xc = np.nan_to_num(np.atleast_2d(x) - self.mu)
        return np.einsum("ij,jk,ik->i", xc, self.cov_inv, xc)

    def is_ood(self, x) -> np.ndarray:
        return self.score(x) > self.threshold
