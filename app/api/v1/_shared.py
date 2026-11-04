"""Shared lazy resources for API routes (read-only fixtures, synthetic history)."""
from __future__ import annotations

import threading
from functools import lru_cache

import numpy as np
import pandas as pd

from app.control.dynamics import load_dynamics
from app.control.reduced_model import load_surrogate
from app.core.settings import settings
from app.data.fixtures import baseline
from app.data.tag_dictionary import build_registry
from app.schemas.plant import preset_config

_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def history() -> pd.DataFrame:
    p = settings.fixtures_dir / "synthetic_history_RK-100TPD.csv.gz"
    if p.exists():
        df = pd.read_csv(p, parse_dates=["timestamp_utc"]).set_index("timestamp_utc")
        df.attrs["banner"] = "SYNTHETIC DEMONSTRATION DATA - NOT PLANT MEASUREMENTS"
        return df
    from app.integration.synthetic import generate_history
    from app.services.compute import baseline_profile_for_synth
    return generate_history(load_surrogate(), baseline_profile_for_synth(baseline("RK-100TPD")), preset_config(),
                            days=7)


def public_history() -> pd.DataFrame:
    df = history()
    return df[[c for c in df.columns if not c.startswith("_truth_") and not c.startswith("label_")]]


@lru_cache(maxsize=4)
def registry(preset: str = "RK-100TPD") -> dict:
    return {t.tag_id: t for t in build_registry(preset_config(preset))}


def surrogate(preset="RK-100TPD"):
    return load_surrogate(preset)


def dynamics(preset="RK-100TPD"):
    return load_dynamics(preset)


def u_from_current(sur, current: dict) -> np.ndarray:
    names = ["pellet_tph", "feed_coal_tph", "injection_coal_tph", "secondary_air_scale", "rpm",
             "gasification_multiplier", "reduction_multiplier", "pellet_moisture_pct"]
    u = sur.baseline.copy()
    for i, n in enumerate(names):
        if n in current and current[n] is not None:
            u[i] = float(current[n])
    return u
