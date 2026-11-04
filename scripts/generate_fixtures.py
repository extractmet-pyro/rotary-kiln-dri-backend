"""Regenerate all deterministic SYNTHETIC demo fixtures.
Usage: python -m scripts.generate_fixtures [--skip-baselines]"""
from __future__ import annotations

import argparse
import json
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FX = ROOT / "fixtures"


def baseline(preset):
    from app.physics.finite_volume import KilnModel
    from app.physics.postprocess import summarize
    from app.physics.steady_state import solve_steady
    from app.schemas.plant import preset_config
    m = KilnModel(preset_config(preset))
    st = solve_steady(m)
    r = summarize(m, st.__dict__, "DEMO_SYNTHETIC")
    r["scenario_name"] = "baseline"
    (FX / f"baseline_{preset}.json").write_text(json.dumps(r, default=float))
    return preset, st.message, r["kpi"]["metallization_pct"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-baselines", action="store_true")
    a = ap.parse_args()
    from app.schemas.plant import PRESETS
    if not a.skip_baselines:
        with Pool(2) as P:
            for r in P.imap_unordered(baseline, list(PRESETS)):
                print("baseline", r, flush=True)
    from app.data import fixtures as fxmod
    fxmod.load_json.cache_clear()
    from app.services.compute import job_closed_loop, job_ml_train, job_simulation
    tr = job_simulation({"preset": "RK-100TPD", "scenario_name": "transient demo: +6 % feed coal at 1 h, air -4 % at 5 h",
                         "simulation": {"type": "transient", "duration_min": 600, "output_interval_min": 10,
                                        "schedule": [{"t_min": 60, "changes": {"coal.feed_coal_tph": 4.134}},
                                                     {"t_min": 300, "changes": {"air.secondary_air_scale": 0.96}}]}})
    (FX / "transient_demo_RK-100TPD.json").write_text(json.dumps(tr, default=float))
    print("transient done", flush=True)
    from app.control.reduced_model import load_surrogate
    from app.integration.synthetic import generate_history
    from app.schemas.plant import preset_config
    from app.services.compute import baseline_profile_for_synth
    df = generate_history(load_surrogate(), baseline_profile_for_synth(fxmod.baseline("RK-100TPD")), preset_config(),
                          days=14, seed=42)
    df.to_csv(FX / "synthetic_history_RK-100TPD.csv.gz", float_format="%.5g")
    print("history done", flush=True)
    ml = job_ml_train({"days": 14, "seed": 42})
    (FX / "ml_report_RK-100TPD.json").write_text(json.dumps(ml, default=float))
    print("ml done", flush=True)
    cl = job_closed_loop({"preset": "RK-100TPD", "hours": 10, "interval_min": 60, "disturbance_t_h": 1.0,
                          "disturbance": {"kinetics.gasification_multiplier": 0.85}})
    (FX / "closed_loop_RK-100TPD.json").write_text(json.dumps(cl, default=float))
    print("closed loop done", flush=True)


if __name__ == "__main__":
    main()
