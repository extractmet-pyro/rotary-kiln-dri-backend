"""Deterministic SYNTHETIC plant-history generator (no-credential fallback).

!!! SYNTHETIC DATA - NOT FROM ANY PLANT !!!
Operating moves, coal/pellet lot changes and sensor faults are simulated; the
process response is the physics-derived surrogate with first-order dynamics and
transport delay.  Hidden truth columns are prefixed '_truth_' and fault labels
'label_' - they must never be used as ML features (leakage test enforces this).
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.control.reduced_model import OUTPUTS
from app.integration.base import DataAdapter

OI = {k: i for i, k in enumerate(OUTPUTS)}
SYNTHETIC_BANNER = "SYNTHETIC DEMONSTRATION DATA - NOT PLANT MEASUREMENTS"


def generate_history(sur, baseline_profile: dict, cfg, days: float = 14.0, step_min: float = 5.0, seed: int = 42,
                     start: datetime | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = int(days * 24 * 60 / step_min)
    start = start or datetime(2026, 10, 1, tzinfo=timezone.utc)
    t = pd.date_range(start, periods=n, freq=f"{int(step_min)}min", tz="UTC")
    b = sur.baseline.copy()
    lo, hi = sur.lo, sur.hi
    U = np.tile(b, (n, 1))
    # operator moves: piecewise constant within 70 % of design range
    for j in range(5):
        k = 0
        level = b[j]
        while k < n:
            dur = int(rng.integers(int(4 * 60 / step_min), int(14 * 60 / step_min)))
            span = 0.35 * (hi[j] - lo[j])
            level = float(np.clip(level + rng.normal(0, 0.35) * span, b[j] - span, b[j] + span))
            U[k:k + dur, j] = level
            k += dur
    # disturbances: coal lots (gasification), pellet lots (reduction), moisture (diurnal + rain)
    for j, every_h, sd in ((5, 60, 0.08), (6, 96, 0.06)):
        k = 0
        while k < n:
            dur = int(rng.integers(int(0.6 * every_h * 60 / step_min), int(1.4 * every_h * 60 / step_min)))
            U[k:k + dur, j] = np.clip(1.0 + rng.normal(0, sd), lo[j] + 0.02, hi[j] - 0.02)
            k += dur
    hrs = np.arange(n) * step_min / 60
    U[:, 7] = np.clip(b[7] + 0.4 * np.sin(2 * np.pi * hrs / 24) + 0.15 * rng.standard_normal(n), lo[7], hi[7])
    rain = rng.integers(0, n - 300)
    U[rain:rain + 240, 7] = np.clip(U[rain:rain + 240, 7] + 1.0, lo[7], hi[7])
    U = np.clip(U, lo, hi)
    Yss = sur.predict(U)
    # dynamics: first order + delay per output (solids outputs delayed by ~0.45 residence)
    res_h = baseline_profile.get("residence_h", 5.0)
    tau = {k: 40.0 for k in OUTPUTS}
    delay = {k: 15.0 for k in OUTPUTS}
    for k in ("metallization_pct", "dri_t_h", "FeO_pct", "C_pct", "char_C_discharge_t_h"):
        tau[k], delay[k] = 0.3 * res_h * 60, 0.45 * res_h * 60
    tau["peak_shell_T_C"] = 120.0
    Y = np.zeros_like(Yss)
    for i, k in enumerate(OUTPUTS):
        d = int(delay[k] / step_min)
        a = np.exp(-step_min / tau[k])
        y = Yss[0, i]
        for s in range(n):
            src = Yss[max(s - d, 0), i]
            y = a * y + (1 - a) * src
            Y[s, i] = y
    df = pd.DataFrame(index=t)
    df.index.name = "timestamp_utc"
    # MVs as measured (feeder readings) incl. a feeder drift fault
    df["PELLET_FEED_TPH"] = U[:, 0] * (1 + 0.005 * rng.standard_normal(n))
    coal_meas = U[:, 1] * (1 + 0.006 * rng.standard_normal(n))
    f0 = int(n * 0.55)
    f1 = f0 + int(12 * 60 / step_min)
    coal_meas[f0:f1] *= 1.08
    df["COAL_FEED_TPH"] = coal_meas
    df["COAL_INJECTION_TPH"] = U[:, 2] * (1 + 0.01 * rng.standard_normal(n))
    df["DOLOMITE_TPH"] = cfg.flux.dolomite_tph * (1 + 0.02 * rng.standard_normal(n))
    df["KILN_RPM"] = U[:, 4] + 0.002 * rng.standard_normal(n)
    tubes = cfg.air.secondary_tubes
    for tb in tubes:
        df[f"AIR_SECONDARY_{tb.tube_id}_NM3H"] = tb.flow_nm3h * U[:, 3] * (1 + 0.01 * rng.standard_normal(n))
    df["AIR_PRIMARY_NM3H"] = cfg.air.primary_air_nm3h * (1 + 0.01 * rng.standard_normal(n))
    # process sensors
    exh = Y[:, OI["exit_gas_T_C"]] + 6 * rng.standard_normal(n)
    z0 = int(n * 0.3)
    exh[z0:z0 + int(3 * 60 / step_min)] = exh[z0]  # frozen thermocouple
    df["EXHAUST_TEMP_C"] = exh
    df["EXHAUST_O2_VOLPCT_DRY"] = np.clip(Y[:, OI["exit_O2_vol_pct_dry"]] + 0.25 * rng.standard_normal(n), 0, 21)
    co2_base = baseline_profile.get("exit_CO2_dry", 18.0)
    df["EXHAUST_CO2_VOLPCT_DRY"] = co2_base - 0.8 * (df["EXHAUST_O2_VOLPCT_DRY"] - Y[0, OI["exit_O2_vol_pct_dry"]]) + \
        0.3 * rng.standard_normal(n)
    df["EXHAUST_CO_VOLPCT_DRY"] = np.clip(0.05 + 0.03 * rng.standard_normal(n), 0, None)
    zf = np.array(baseline_profile["zf"])
    Tb = np.array(baseline_profile["T_bed_C"])
    Tsh = np.array(baseline_profile["T_shell_C"])
    dpk = Y[:, OI["peak_bed_T_C"]] - Yss[0, OI["peak_bed_T_C"]]
    dsh = Y[:, OI["peak_shell_T_C"]] - Yss[0, OI["peak_shell_T_C"]]
    # accretion precursor event: localised shell cooling + torque rise in zone 4
    a0, a1 = int(n * 0.75), int(n * 0.75) + int(30 * 60 / step_min)
    ring = np.zeros(n)
    ring[a0:a1] = np.linspace(0, 1, a1 - a0)
    ring[a1:] = 1.0 if a1 < n else 0
    ring[a1 + int(6 * 60 / step_min):] = 0.0  # "cleared" after maintenance action
    for i, frac in enumerate([0.1, 0.25, 0.4, 0.55, 0.7, 0.85]):
        w = np.clip((frac - 0.2) / 0.5, 0, 1)
        Tz = np.interp(frac, zf, Tb)
        Sz = np.interp(frac, zf, Tsh)
        df[f"TEMP_FREEBOARD_Z{i+1}_C"] = Tz + 40 + w * dpk + 5 * rng.standard_normal(n)
        sh = Sz + w * dsh + 3 * rng.standard_normal(n)
        if i == 3:
            sh = sh - 45 * ring
        if i == 1:
            dr0 = int(n * 0.4)
            sh[dr0:dr0 + int(10 * 60 / step_min)] += np.linspace(0, 20, int(10 * 60 / step_min))  # scanner drift
        df[f"TEMP_SHELL_Z{i+1}_C"] = sh
    df["KILN_DRIVE_TORQUE"] = 55 * (U[:, 0] / b[0]) * (b[4] / U[:, 4]) ** 0.5 + 8 * ring + 1.0 * rng.standard_normal(n)
    df["KILN_DRAFT_PA"] = cfg.offgas.kiln_feed_end_draft_Pa + 3 * rng.standard_normal(n)
    df["DRI_DISCHARGE_TPH"] = Y[:, OI["dri_t_h"]] * (1 + 0.02 * rng.standard_normal(n))
    df["WHRB_STEAM_TPH"] = Y[:, OI["steam_t_h"]] * (1 + 0.015 * rng.standard_normal(n))
    df["COOLER_EXIT_C"] = 45 + 4 * rng.standard_normal(n)
    df["ESP_DP_PA"] = 900 + 20 * rng.standard_normal(n)
    # lab samples every 2 h, result available 1.5 h later (value refers to sample time)
    lab_every = int(120 / step_min)
    lab_delay = int(90 / step_min)
    met = np.full(n, np.nan)
    feo = np.full(n, np.nan)
    car = np.full(n, np.nan)
    for s in range(0, n - lab_delay, lab_every):
        met[s + lab_delay] = Y[s, OI["metallization_pct"]] + 0.8 * rng.standard_normal()
        feo[s + lab_delay] = Y[s, OI["FeO_pct"]] + 0.4 * rng.standard_normal()
        car[s + lab_delay] = max(Y[s, OI["C_pct"]] + 0.03 * rng.standard_normal(), 0)
    df["LAB_METALLIZATION_PCT"] = met
    df["LAB_SAMPLE_TIME_OFFSET_MIN"] = np.where(np.isfinite(met), -90.0, np.nan)
    df["LAB_DRI_CARBON_PCT"] = car
    df["LAB_FEO_PCT"] = feo
    df["LAB_TOTAL_FE_PCT"] = np.where(np.isfinite(met), 87.0 + 0.4 * rng.standard_normal(n), np.nan)
    df["LAB_METALLIC_FE_PCT"] = df["LAB_TOTAL_FE_PCT"] * df["LAB_METALLIZATION_PCT"] / 100
    # truth & labels (never features)
    for k in OUTPUTS:
        df[f"_truth_{k}"] = Y[:, OI[k]]
    df["_truth_gasification_multiplier"] = U[:, 5]
    df["_truth_reduction_multiplier"] = U[:, 6]
    df["_truth_pellet_moisture_pct"] = U[:, 7]
    df["_truth_coal_feed_tph"] = U[:, 1]
    lab = np.zeros(n, dtype=int)
    lab[z0:z0 + int(3 * 60 / step_min)] = 1
    df["label_sensor_freeze_EXHAUST_TEMP"] = lab
    lab = np.zeros(n, dtype=int)
    lab[f0:f1] = 1
    df["label_feeder_drift_COAL_FEED"] = lab
    lab = np.zeros(n, dtype=int)
    dr0 = int(n * 0.4)
    lab[dr0:dr0 + int(10 * 60 / step_min)] = 1
    df["label_scanner_drift_SHELL_Z2"] = lab
    df["label_accretion_precursor"] = (ring > 0.2).astype(int)
    df.attrs["banner"] = SYNTHETIC_BANNER
    return df


class SyntheticAdapter(DataAdapter):
    name = "synthetic"

    def __init__(self, df: pd.DataFrame):
        self.df = df

    def read_recent(self, tags=None, minutes=60):
        w = self.df[self.df.index >= self.df.index.max() - pd.Timedelta(minutes=minutes)]
        cols = [c for c in (tags or w.columns) if not c.startswith("_truth_") and not c.startswith("label_")]
        return w[cols]

    def read_range(self, start, end, tags=None):
        w = self.df[(self.df.index >= pd.Timestamp(start)) & (self.df.index <= pd.Timestamp(end))]
        cols = [c for c in (tags or w.columns) if not c.startswith("_truth_") and not c.startswith("label_")]
        return w[cols]

    def health(self):
        return {"adapter": self.name, "rows": len(self.df), "banner": SYNTHETIC_BANNER, "read_only": True,
                "last_timestamp_utc": str(self.df.index.max())}
