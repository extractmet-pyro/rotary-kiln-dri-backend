import warnings

import numpy as np
import pytest

from app.control.advisory import validate_decision
from app.control.constraints import MPCSettings, default_mvs
from app.control.dynamics import load_dynamics
from app.control.mpc import SupervisoryMPC
from app.control.reduced_model import load_surrogate
from app.control.safety_gates import evaluate_gates
from app.schemas.plant import preset_config

warnings.filterwarnings("ignore")


@pytest.fixture(scope="module")
def ctx():
    return load_surrogate(), load_dynamics(), preset_config()


def test_recommendation_respects_bounds_and_ramps(ctx):
    sur, dyn, cfg = ctx
    r = SupervisoryMPC(sur, dyn, cfg, MPCSettings()).recommend(sur.baseline.copy())
    assert r["solver"]["success"]
    mvs = {m.name: m for m in default_mvs(cfg, sur.baseline)}
    for mv in r["moves"]:
        spec = mvs[mv["mv"]]
        assert spec.lo - 1e-6 <= mv["recommended"] <= spec.hi + 1e-6
        sched = [mv["current"]] + mv["schedule"]
        assert np.all(np.abs(np.diff(sched)) <= spec.ramp_per_interval + 1e-6)


def test_locked_variable_unchanged(ctx):
    sur, dyn, cfg = ctx
    r = SupervisoryMPC(sur, dyn, cfg).recommend(sur.baseline.copy(), locked=["rpm", "pellet_tph"])
    d = {m["mv"]: m for m in r["moves"]}
    assert d["rpm"]["delta"] == 0 and d["pellet_tph"]["delta"] == 0


def test_supervisory_mode_blocked(ctx):
    sur, dyn, cfg = ctx
    r = SupervisoryMPC(sur, dyn, cfg).recommend(sur.baseline.copy())
    g = evaluate_gates("SITE_SUPERVISORY", r, None)
    assert not g["actionable"] and "NONE" in g["write_authority"]


def test_failed_optimiser_or_stale_data_not_actionable(ctx):
    sur, dyn, cfg = ctx
    r = SupervisoryMPC(sur, dyn, cfg).recommend(sur.baseline.copy())
    r["solver"]["success"] = False
    assert not evaluate_gates("OFFLINE_SIMULATION", r, None)["actionable"]
    r["solver"]["success"] = True
    assert not evaluate_gates("SHADOW", r, "2020-01-01T00:00:00Z")["actionable"]


def test_out_of_domain_flagged(ctx):
    sur, dyn, cfg = ctx
    u = sur.baseline.copy()
    u[5] = 3.0
    assert not sur.domain_check(u)["in_domain"]


def test_decision_requires_note_and_role():
    assert validate_decision("approve", "", "operator", "RECOMMENDATION_AVAILABLE")
    assert validate_decision("approve", "looks fine", "viewer", "RECOMMENDATION_AVAILABLE")
    assert validate_decision("approve", "looks fine", "operator", "ADVISORY_ALARM_NO_RECOMMENDATION")
    assert not validate_decision("reject", "not now, lab pending", "operator", "RECOMMENDATION_AVAILABLE")


def test_surrogate_fidelity_reported(ctx):
    sur, _, _ = ctx
    assert sur.n_runs >= 40 and np.all(np.isfinite(sur.loo_rmse))
