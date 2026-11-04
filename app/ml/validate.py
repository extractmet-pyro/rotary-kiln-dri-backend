"""ML validation utilities: leakage checks and runtime input validation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.ml.features import FORBIDDEN_PREFIX


def leakage_check(F: pd.DataFrame, raw: pd.DataFrame, residence_h: float) -> dict:
    issues = [c for c in F.columns if c.startswith(FORBIDDEN_PREFIX)]
    # recompute one feature with future data removed: must be identical
    s = F.index[len(F) // 2]
    past = raw[raw.index <= s]
    lag = pd.Timedelta(minutes=0.5 * residence_h * 60)
    w = past.loc[(past.index > s - lag - pd.Timedelta(minutes=60)) & (past.index <= s - lag), "PELLET_FEED_TPH"].mean()
    ok_future = bool(np.isclose(w, F.loc[s, "PELLET_FEED_TPH__lag50R"]))
    return {"forbidden_columns": issues, "future_independence": ok_future, "pass": (not issues) and ok_future}


def runtime_guard(x: np.ndarray, ood=None) -> dict:
    x = np.asarray(x, float)
    flags = []
    if not np.all(np.isfinite(x)):
        flags.append("NaN/Inf in features")
    if ood is not None and np.all(np.isfinite(x)) and bool(ood.is_ood(x)[0]):
        flags.append("out-of-distribution input (Mahalanobis)")
    return {"ok": not flags, "flags": flags}
