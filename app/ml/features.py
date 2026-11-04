"""Causal feature engineering with an explicit feature data contract.

For a prediction (sample) time s, every feature uses only data with timestamps
<= s - availability_lag.  Transport delays are expressed as fractions of the
solids residence time R so that a discharge sample is aligned with the feed
cohort that produced it.  '_truth_*', 'label_*' and LAB_* columns are never
features (leakage guard)."""
from __future__ import annotations

import numpy as np
import pandas as pd

MV_TAGS = ["PELLET_FEED_TPH", "COAL_FEED_TPH", "COAL_INJECTION_TPH", "KILN_RPM"]
SENSOR_TAGS = ["EXHAUST_TEMP_C", "EXHAUST_O2_VOLPCT_DRY", "EXHAUST_CO2_VOLPCT_DRY", "KILN_DRIVE_TORQUE",
               "TEMP_SHELL_Z3_C", "TEMP_SHELL_Z4_C", "TEMP_SHELL_Z5_C", "TEMP_FREEBOARD_Z4_C", "TEMP_FREEBOARD_Z5_C",
               "WHRB_STEAM_TPH"]
FORBIDDEN_PREFIX = ("_truth_", "label_", "LAB_")


def air_scale(df: pd.DataFrame, ref: dict) -> pd.Series:
    cols = [c for c in df.columns if c.startswith("AIR_SECONDARY_")]
    tot = df[cols].sum(1)
    return tot / max(sum(ref.values()), 1e-9)


def feature_contract(residence_h: float) -> list[dict]:
    rows = []
    for tag in MV_TAGS + ["AIR_SCALE"]:
        for f in (0.25, 0.5, 0.75):
            rows.append({"feature": f"{tag}__lag{int(f*100)}R", "source_tag": tag, "unit": "as tag",
                         "window_min": 60, "lag_min": round(f * residence_h * 60), "causal": True})
    for tag in SENSOR_TAGS:
        rows.append({"feature": f"{tag}__now30", "source_tag": tag, "unit": "as tag", "window_min": 30, "lag_min": 0,
                     "causal": True})
    rows.append({"feature": "physics_met", "source_tag": "surrogate(MV lag 0.5R, nominal DVs)", "unit": "%",
                 "window_min": 60, "lag_min": round(0.5 * residence_h * 60), "causal": True})
    return rows


def build_features(df: pd.DataFrame, sample_times: pd.DatetimeIndex, residence_h: float, sur=None,
                   ref_tubes: dict | None = None) -> pd.DataFrame:
    d = df.copy()
    if ref_tubes:
        d["AIR_SCALE"] = air_scale(d, ref_tubes)
    else:
        d["AIR_SCALE"] = 1.0
    out = []
    idx = d.index
    for s in sample_times:
        row = {"sample_time": s}
        for tag in MV_TAGS + ["AIR_SCALE"]:
            for f in (0.25, 0.5, 0.75):
                lag = pd.Timedelta(minutes=f * residence_h * 60)
                w = d.loc[(idx > s - lag - pd.Timedelta(minutes=60)) & (idx <= s - lag), tag]
                row[f"{tag}__lag{int(f*100)}R"] = float(w.mean()) if len(w) else np.nan
        for tag in SENSOR_TAGS:
            if tag in d:
                w = d.loc[(idx > s - pd.Timedelta(minutes=30)) & (idx <= s), tag]
                row[f"{tag}__now30"] = float(w.mean()) if len(w) else np.nan
        if sur is not None:
            u = sur.baseline.copy()
            u[0] = row["PELLET_FEED_TPH__lag50R"]
            u[1] = row["COAL_FEED_TPH__lag50R"]
            u[2] = row["COAL_INJECTION_TPH__lag50R"]
            u[3] = row["AIR_SCALE__lag50R"]
            u[4] = row["KILN_RPM__lag50R"]
            u = np.clip(np.nan_to_num(u, nan=0.0), sur.lo, sur.hi)
            row["physics_met"] = float(sur.predict(u)[0][0])
        out.append(row)
    F = pd.DataFrame(out).set_index("sample_time")
    bad = [c for c in F.columns if c.startswith(FORBIDDEN_PREFIX)]
    if bad:
        raise ValueError(f"leakage guard: forbidden feature columns {bad}")
    return F


def lab_targets(df: pd.DataFrame, col: str = "LAB_METALLIZATION_PCT") -> pd.Series:
    """Lab values are reported 90 min after sampling; re-index to sample time."""
    s = df[col].dropna()
    off = df.loc[s.index, "LAB_SAMPLE_TIME_OFFSET_MIN"].fillna(-90.0)
    s.index = s.index + pd.to_timedelta(off.values, unit="min")
    return s
