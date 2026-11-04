"""Reconciled current state estimate (EKF on synthetic/replayed data) with provenance."""
from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi import APIRouter

from app.api.v1 import _shared
from app.data.fixtures import baseline
from app.estimation.observer import KilnEKF
from app.estimation.reconciliation import fe_balance_reconciliation
from app.estimation.uncertainty import align_lab_sample, monte_carlo
from app.schemas.plant import preset_config

router = APIRouter(prefix="/api/v1", tags=["state estimation"])


def run_ekf(hours: float = 24.0, preset: str = "RK-100TPD"):
    sur = _shared.surrogate(preset)
    df = _shared.history()
    tubes = [c for c in df.columns if c.startswith("AIR_SECONDARY_")]
    tube_ref = df[tubes].iloc[:288].sum(1).mean()
    w = df[df.index > df.index.max() - pd.Timedelta(hours=hours)].iloc[::3]
    ekf = KilnEKF(sur)
    trace = []
    for t, row in w.iterrows():
        u = sur.baseline.copy()
        u[0], u[1], u[2] = row["PELLET_FEED_TPH"], row["COAL_FEED_TPH"], row["COAL_INJECTION_TPH"]
        u[3] = row[tubes].sum() / tube_ref
        u[4] = row["KILN_RPM"]
        u = np.clip(u, sur.lo, sur.hi)
        meas = {"EXHAUST_TEMP_C": row["EXHAUST_TEMP_C"],
                "TEMP_SHELL_MAX_C": max(row[f"TEMP_SHELL_Z{i}_C"] for i in range(1, 7)),
                "EXHAUST_O2_VOLPCT_DRY": row["EXHAUST_O2_VOLPCT_DRY"],
                "LAB_METALLIZATION_PCT": row.get("LAB_METALLIZATION_PCT")}
        rec = ekf.update(u, {k: (None if pd.isna(v) else float(v)) for k, v in meas.items()}, t.isoformat())
        rec["truth_gasification_multiplier"] = float(row.get("_truth_gasification_multiplier", np.nan))
        rec["truth_reduction_multiplier"] = float(row.get("_truth_reduction_multiplier", np.nan))
        trace.append(rec)
    return ekf, trace, u


@router.get("/states/current")
def current(preset: str = "RK-100TPD", hours: float = 24.0):
    sur = _shared.surrogate(preset)
    ekf, trace, u = run_ekf(hours, preset)
    last = trace[-1]
    uu = u.copy()
    uu[5], uu[6] = last["x"]["gasification_multiplier"], last["x"]["reduction_multiplier"]
    est = sur.predict_dict(uu)
    sd = dict(zip(est.keys(), (sur.predict_std(uu)[0] if hasattr(sur, "predict_std") else np.zeros(len(est))).tolist()))
    b = baseline(preset)
    res_h = b["kpi"]["residence_time_h"] if b else 5.0
    df = _shared.history()
    k = b["kpi"] if b else {}
    recon = fe_balance_reconciliation(float(df["PELLET_FEED_TPH"].iloc[-12:].mean()),
                                      preset_config(preset).pellet.assay_dry_wt_pct["Fe_total"] * (1 - preset_config(preset).pellet.moisture_wt_pct / 100),
                                      float(df["DRI_DISCHARGE_TPH"].iloc[-12:].mean()), k.get("Fe_total_pct", 87.0),
                                      k.get("nonmagnetic_t_h", 1.5), 3.0)
    return {
        "timestamp_utc": last["t"], "source": "EKF on SYNTHETIC history (surrogate measurement model)",
        "estimated_parameters": last["x"], "parameter_sd": last["sd"], "confidence": last["confidence"],
        "flags": last["flags"], "used_measurements": last["used_measurements"],
        "estimated_outputs": est, "estimated_outputs_sd": sd,
        "provenance": {k2: ("model-estimated" if k2 not in ("exit_gas_T_C", "peak_shell_T_C") else "measured+model")
                       for k2 in est},
        "trace": [{"t": r["t"], "gasif": r["x"]["gasification_multiplier"], "red": r["x"]["reduction_multiplier"],
                   "gasif_sd": r["sd"]["gasification_multiplier"], "truth_gasif": r["truth_gasification_multiplier"],
                   "truth_red": r["truth_reduction_multiplier"], "nis": r["nis"],
                   "exit_tc_bias": r["x"]["exit_tc_bias_C"]} for r in trace],
        "lab_alignment": align_lab_sample(0.0, res_h), "uncertainty_mc": monte_carlo(sur, uu, n=300),
        "fe_reconciliation": recon,
        "actionable": last["confidence"] >= 0.5 and not any("bound" in f for f in last["flags"]),
        "baseline_profiles_run": "fixture-baseline-" + preset}
