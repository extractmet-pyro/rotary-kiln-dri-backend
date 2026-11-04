"""Fit the GP surrogate from an existing physics DOE CSV (no new physics runs).
Usage: python -m scripts.fit_gp_surrogate --preset RK-100TPD"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.control.reduced_model import INPUTS, OUTPUTS, fit_gp_surrogate  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--preset", default="RK-100TPD")
a = ap.parse_args()
d = pd.read_csv(ROOT / "fixtures" / f"doe_{a.preset}.csv")
d = d[d["used_in_fit"]]
q = json.loads((ROOT / "fixtures" / f"surrogate_{a.preset}.json").read_text())
X = d[[i[0] for i in INPUTS]].values
Y = d[OUTPUTS].values
gp = fit_gp_surrogate(X, Y, q["lo"], q["hi"], q["baseline"], a.preset, meta={**q["meta"], "quadratic_loo_rmse": q["loo_rmse"]})
joblib.dump(gp, ROOT / "fixtures" / f"surrogate_gp_{a.preset}.joblib")
print("GP 6-fold RMSE:", dict(zip(OUTPUTS, np.round(gp.loo_rmse, 3))))
print("quadratic LOO RMSE:", dict(zip(OUTPUTS, np.round(q["loo_rmse"], 3))))
