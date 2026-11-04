"""Model explanations (associational, not causal)."""
from __future__ import annotations

import numpy as np
from sklearn.inspection import permutation_importance


def permutation(model, X, y, names, seed=0, n_repeats=8):
    r = permutation_importance(model, X, y, n_repeats=n_repeats, random_state=seed, scoring="neg_mean_absolute_error")
    order = np.argsort(-r.importances_mean)
    return [{"feature": names[i], "importance_mae": float(r.importances_mean[i]), "sd": float(r.importances_std[i])}
            for i in order[:15]]


def ridge_coefficients(pipe, names):
    reg = pipe.named_steps.get("ridge") or pipe.steps[-1][1]
    coef = getattr(reg, "coef_", None)
    if coef is None:
        return []
    order = np.argsort(-np.abs(coef))
    return [{"feature": names[i], "std_coef": float(coef[i])} for i in order[:15]]


NOTE = "Feature importances are associational; they do not establish causal effects on the process."
