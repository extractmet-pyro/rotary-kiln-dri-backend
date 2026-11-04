import numpy as np
import pandas as pd
import pytest

from app.control.reduced_model import load_surrogate
from app.data.fixtures import baseline
from app.integration.synthetic import generate_history
from app.ml.drift import MahalanobisOOD, psi
from app.ml.features import build_features, lab_targets
from app.ml.predict import project_correction
from app.ml.train import train_anomaly, train_soft_sensor
from app.ml.validate import leakage_check
from app.schemas.plant import preset_config
from app.services.compute import baseline_profile_for_synth


@pytest.fixture(scope="module")
def hist():
    prof = baseline_profile_for_synth(baseline("RK-100TPD"))
    return generate_history(load_surrogate(), prof, preset_config(), days=6, seed=3), prof


def test_synthetic_is_labelled_and_deterministic(hist):
    df, prof = hist
    assert "SYNTHETIC" in df.attrs["banner"]
    df2 = generate_history(load_surrogate(), prof, preset_config(), days=6, seed=3)
    assert np.allclose(df["EXHAUST_TEMP_C"].values, df2["EXHAUST_TEMP_C"].values)


def test_no_leakage(hist):
    df, prof = hist
    y = lab_targets(df)
    y = y[y.index > df.index.min() + pd.Timedelta(hours=8)]
    pub = df[[c for c in df.columns if not c.startswith(("_truth_", "label_"))]]
    F = build_features(pub, y.index[:20], prof["residence_h"], load_surrogate())
    assert leakage_check(F, pub, prof["residence_h"])["pass"]


def test_training_pipeline_runs_and_reports(hist, tmp_path, monkeypatch):
    df, prof = hist
    cfg = preset_config()
    r = train_soft_sensor(df, load_surrogate(), prof["residence_h"], {t.tube_id: t.flow_nm3h for t in cfg.air.secondary_tubes},
                          save=False)
    assert "physics_only" in r["models"] and "hybrid_physics_plus_ridge_residual" in r["models"]
    for m in r["models"].values():
        assert np.isfinite(m["test"]["MAE"])
    a = train_anomaly(df, save=False)
    assert "isolation_forest_any_fault" in a


def test_drift_tools():
    rng = np.random.default_rng(0)
    assert psi(rng.normal(0, 1, 1000), rng.normal(0, 1, 1000)) < 0.1
    assert psi(rng.normal(0, 1, 1000), rng.normal(2, 1, 1000)) > 0.5
    o = MahalanobisOOD(rng.normal(0, 1, (500, 3)))
    assert o.is_ood(np.array([[8, 8, 8]]))[0]


def test_conservative_projection():
    dri = {"mass_kg_s": 1.4, "Fe_total_pct": 87.0, "Fe_metallic_pct": 80.0, "metallization_pct": 91.95}
    out = project_correction(dri, (10.0, 100.0), +1.0)
    fe_before = 0.87 * 1.4
    fe_after = out["dri"]["Fe_total_pct"] / 100 * out["dri"]["mass_kg_s"]
    assert fe_after == pytest.approx(fe_before)
    assert out["dri"]["metallization_pct"] == pytest.approx(80.0 / 87.0 * 100 + 1.0, abs=1e-9)
