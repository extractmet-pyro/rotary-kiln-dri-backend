"""Training pipelines for ML-A (quality soft sensor), ML-B (bounded physics
residual correction) and ML-C (anomaly / accretion-precursor diagnostics).

Chronological blocked split (train 60 % / validation 20 % / test 20 %), imputation
and scaling fitted on training data only (inside sklearn Pipelines), split-
conformal 90 % prediction intervals from validation residuals, comparison of
physics-only, ML-only and hybrid estimators.  Results on SYNTHETIC data
demonstrate the pipeline only."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cross_decomposition import PLSRegression
from sklearn.ensemble import HistGradientBoostingRegressor, IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml import registry
from app.ml.drift import MahalanobisOOD
from app.ml.explain import NOTE, permutation
from app.ml.features import SENSOR_TAGS, build_features, feature_contract, lab_targets

SEED = 20261102
DELTA_BOUND_PP = 3.0


def _metrics(y, p, lo=None, hi=None):
    e = p - y
    m = {"MAE": float(np.mean(np.abs(e))), "RMSE": float(np.sqrt(np.mean(e ** 2))), "bias": float(np.mean(e)),
         "n": int(len(y))}
    if len(e) > 3:
        m["resid_lag1_autocorr"] = float(np.corrcoef(e[:-1], e[1:])[0, 1])
    if lo is not None:
        m["PI90_coverage"] = float(np.mean((y >= lo) & (y <= hi)))
        m["PI90_mean_width"] = float(np.mean(hi - lo))
    return m


def chrono_split(n, f_train=0.6, f_val=0.2):
    a, b = int(n * f_train), int(n * (f_train + f_val))
    return np.arange(0, a), np.arange(a, b), np.arange(b, n)


def train_soft_sensor(df: pd.DataFrame, sur, residence_h: float, ref_tubes: dict, save: bool = True) -> dict:
    y_all = lab_targets(df)
    y_all = y_all[y_all.index >= df.index.min() + pd.Timedelta(hours=residence_h + 1)]
    F = build_features(df, y_all.index, residence_h, sur, ref_tubes)
    ok = F.notna().mean(1) > 0.8
    F, y = F[ok], y_all[ok].values
    names = list(F.columns)
    X = F.values
    tr, va, te = chrono_split(len(y))
    phys = F["physics_met"].values
    feats_ml = [i for i, c in enumerate(names) if c != "physics_met"]
    res = {"n_samples": len(y), "split": {"train": [str(F.index[tr[0]]), str(F.index[tr[-1]])],
                                          "validation": [str(F.index[va[0]]), str(F.index[va[-1]])],
                                          "test": [str(F.index[te[0]]), str(F.index[te[-1]])]},
           "models": {}}

    def pipe(est):
        return Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("ridge", est)])
    candidates = {
        "ridge_ml_only": (pipe(Ridge(alpha=3.0)), feats_ml, "level"),
        "pls_ml_only": (Pipeline([("impute", SimpleImputer()), ("scale", StandardScaler()),
                                  ("ridge", PLSRegression(n_components=4))]), feats_ml, "level"),
        "hgb_ml_only": (Pipeline([("impute", SimpleImputer()), ("ridge", HistGradientBoostingRegressor(
            max_iter=200, learning_rate=0.05, max_depth=3, random_state=SEED))]), feats_ml, "level"),
        "hybrid_physics_plus_ridge_residual": (pipe(Ridge(alpha=10.0)), feats_ml + [names.index("physics_met")],
                                               "residual"),
    }
    preds = {"physics_only": phys}
    fitted = {}
    for key, (est, cols, kind) in candidates.items():
        Xc = X[:, cols]
        target = y - phys if kind == "residual" else y
        est.fit(Xc[tr], target[tr])
        p = np.ravel(est.predict(Xc))
        if kind == "residual":
            p = phys + np.clip(p, -DELTA_BOUND_PP, DELTA_BOUND_PP)
        preds[key] = p
        fitted[key] = (est, cols, kind)
    for key, p in preds.items():
        q = np.quantile(np.abs(y[va] - p[va]), 0.9)  # split conformal from validation
        res["models"][key] = {"validation": _metrics(y[va], p[va]),
                              "test": _metrics(y[te], p[te], p[te] - q, p[te] + q), "conformal_q90": float(q)}
    best = min((k for k in res["models"]), key=lambda k: res["models"][k]["validation"]["MAE"])
    res["selected_by_validation_MAE"] = best
    res["test_series"] = {"t": [str(x) for x in F.index[te]], "lab": y[te].tolist(),
                          **{k: preds[k][te].tolist() for k in preds}}
    ood = MahalanobisOOD(X[tr][:, feats_ml])
    res["feature_contract"] = feature_contract(residence_h)
    if best != "physics_only":
        est, cols, kind = fitted[best]
        try:
            res["explanation"] = permutation(est, X[te][:, cols], (y - phys)[te] if kind == "residual" else y[te],
                                             [names[c] for c in cols])
        except Exception as e:  # pragma: no cover
            res["explanation"] = [{"error": str(e)}]
    res["explanation_note"] = NOTE
    if save:
        est, cols, kind = fitted["hybrid_physics_plus_ridge_residual"]
        res["registry_version_mlB"] = registry.save("ml_b_residual_correction", {"model": est, "cols": cols,
                                                                                 "names": names, "ood": ood},
            {"purpose": "ML-B bounded residual correction of physics metallization (+/-3 pp)",
             "features": [names[c] for c in cols], "metrics": res["models"]["hybrid_physics_plus_ridge_residual"]["test"],
             "seed": SEED, "split": "chronological 60/20/20", "data": "SYNTHETIC history",
             "status": "DEMO - synthetic", "conformal_q90": res["models"]["hybrid_physics_plus_ridge_residual"]["conformal_q90"]})
        bk = best if best != "physics_only" else "ridge_ml_only"
        est, cols, kind = fitted[bk]
        res["registry_version_mlA"] = registry.save("ml_a_soft_sensor", {"model": est, "cols": cols, "names": names,
                                                                         "kind": kind, "ood": ood},
            {"purpose": "ML-A metallization soft sensor", "algorithm": bk, "features": [names[c] for c in cols],
             "metrics": res["models"][bk]["test"], "seed": SEED, "split": "chronological 60/20/20",
             "data": "SYNTHETIC history", "status": "DEMO - synthetic", "conformal_q90": res["models"][bk]["conformal_q90"]})
    return res


def train_anomaly(df: pd.DataFrame, save: bool = True) -> dict:
    """ML-C: unsupervised IsolationForest on sensor features + rule detectors,
    evaluated against injected synthetic fault labels; plus a supervised
    accretion-precursor classifier (labels exist only in synthetic data)."""
    cols = [c for c in SENSOR_TAGS + ["TEMP_SHELL_Z2_C", "COAL_FEED_TPH"] if c in df]
    X = df[cols].copy()
    # engineered: zone-4 shell temperature relative to neighbours (ring signature), rolling std (freeze)
    X["shell_z4_rel"] = df["TEMP_SHELL_Z4_C"] - 0.5 * (df["TEMP_SHELL_Z3_C"] + df["TEMP_SHELL_Z5_C"])
    X["exh_roll_std"] = df["EXHAUST_TEMP_C"].rolling(12, min_periods=3).std()
    X["coal_vs_o2"] = df["COAL_FEED_TPH"].rolling(24).mean() / (df["EXHAUST_O2_VOLPCT_DRY"].rolling(24).mean() + 1.0)
    X = X.bfill().ffill()
    n = len(X)
    tr = np.arange(0, int(0.5 * n))
    iso = Pipeline([("scale", StandardScaler()), ("iso", IsolationForest(n_estimators=200, contamination=0.03,
                                                                         random_state=SEED))])
    iso.fit(X.iloc[tr])
    score = -iso.decision_function(X)
    flag_iso = iso.predict(X) == -1
    freeze = (X["exh_roll_std"] < 0.05).values
    labels = {c: df[c].values.astype(bool) for c in df.columns if c.startswith("label_")}
    any_fault = np.any(np.column_stack(list(labels.values())), axis=1)

    def pr(flag, truth):
        tp = int((flag & truth).sum())
        fp = int((flag & ~truth).sum())
        fn = int((~flag & truth).sum())
        days = n * (df.index[1] - df.index[0]).total_seconds() / 86400
        return {"precision": tp / max(tp + fp, 1), "recall": tp / max(tp + fn, 1), "false_alarms_per_day": fp / days}
    out = {"isolation_forest_any_fault": pr(flag_iso, any_fault),
           "rule_freeze_detector": pr(freeze, labels.get("label_sensor_freeze_EXHAUST_TEMP", any_fault)),
           "validation_status": "UNVALIDATED RESEARCH SUPPORT - evaluated on injected synthetic faults only"}
    # accretion precursor (supervised, chronological): train first 70 %
    yacc = labels["label_accretion_precursor"]
    Xa = X[["shell_z4_rel", "KILN_DRIVE_TORQUE"]].values
    a = int(0.7 * n)
    clf = Pipeline([("scale", StandardScaler()), ("lr", LogisticRegression(class_weight="balanced", max_iter=500))])
    if yacc[:a].sum() > 5:
        clf.fit(Xa[:a], yacc[:a])
        p = clf.predict_proba(Xa)[:, 1]
        out["accretion_classifier"] = {**pr(p[a:] > 0.5, yacc[a:]), "train_positive": int(yacc[:a].sum()),
                                       "note": "few positive events; metric is illustrative"}
    else:
        clf.fit(Xa, yacc)
        p = clf.predict_proba(Xa)[:, 1]
        out["accretion_classifier"] = {"note": "insufficient positive labels before test block; fitted on all data "
                                               "for demonstration only (no holdout metric reported)"}
    out["timeline"] = {"t": [str(x) for x in df.index[::6]], "iso_score": score[::6].tolist(),
                       "accretion_prob": p[::6].tolist(), "any_fault_label": any_fault[::6].astype(int).tolist()}
    if save:
        out["registry_version"] = registry.save("ml_c_anomaly", {"iso": iso, "acc": clf, "cols": list(X.columns)},
                                                {"purpose": "ML-C anomaly / accretion-precursor detection",
                                                 "metrics": {k: v for k, v in out.items() if isinstance(v, dict) and "precision" in v},
                                                 "seed": SEED, "data": "SYNTHETIC history",
                                                 "status": "UNVALIDATED RESEARCH SUPPORT"})
    return out
