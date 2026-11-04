"""Solver verification: conservation, positivity, boundary conditions,
steady/transient agreement, grid sensitivity, failure modes."""
import numpy as np
import pytest

from app.core.exceptions import InputValidationError
from app.physics.balances import element_audit
from app.physics.finite_volume import KilnModel
from app.physics.postprocess import summarize
from app.physics.species import GI, SI
from app.physics.steady_state import solve_steady
from app.physics.transient import run_transient
from app.schemas.plant import PlantConfig, preset_config


def test_steady_converges_and_conserves(steady100):
    m, st = steady100
    assert st.converged, st.message
    a = element_audit(m.logs, m.ms, window=60)
    assert a["mass"]["relative_residual"] < 1e-5
    assert a["energy"]["relative_residual"] < 1e-6
    for row in a["elements"]:
        assert row["relative_residual"] < 1e-9, row


def test_nonnegative_inventories(steady100):
    m, _ = steady100
    assert np.all(m.state.n >= 0)
    assert np.all(m.state.F >= 0)


def test_counter_current_boundary(steady100):
    m, _ = steady100
    # gas enters at z = L: discharge-end cell inflow is the boundary air (no combustibles)
    assert m.gas_boundary[GI["CO"]] == 0 and m.gas_boundary[GI["O2"]] > 0
    # solids enter at z = 0: feed cell holds raw moisture/VM, discharge cell is reduced
    n = m.state.n
    assert n[SI["H2O_l"], 0] > n[SI["H2O_l"], -1]
    fe = lambda j: n[SI["Fe"], j] / (2 * n[SI["Fe2O3"], j] + 3 * n[SI["Fe3O4"], j] + n[SI["FeO"], j] + n[SI["Fe"], j])
    assert fe(-1) > 0.5 > fe(0)


def test_plausible_kpis(steady100):
    m, st = steady100
    r = summarize(m, st.__dict__)
    k = r["kpi"]
    assert 80 < k["metallization_pct"] <= 100
    assert 600 < k["coal_kg_per_t_dri"] < 2000
    assert 900 < k["peak_bed_T_C"] < 1300
    assert abs(r["heat_balance"]["relative_residual"]) < 0.01
    assert r["quality"]["dri"]["Fe_total_pct"] > r["quality"]["dri"]["Fe_metallic_pct"]


def test_transient_from_steady_stays_steady(steady100):
    m, _ = steady100
    import copy
    m2 = copy.deepcopy(m)
    m2.logs = []
    met0 = summarize(m2, {})["kpi"]["metallization_pct"]
    tr = run_transient(m2, 120, 30)
    assert tr["status"] == "completed"
    assert abs(tr["series"][-1]["metallization_discharge_pct"] - met0) < 1.5
    assert tr["max_step_residuals"]["Fe_rel"] < 1e-9


def test_grid_refinement(fast_cfg):
    res = []
    for n in (18, 36):
        c = PlantConfig.model_validate(fast_cfg.model_dump())
        c.numerics.n_cells = n
        m = KilnModel(c)
        solve_steady(m, max_steps=1200)
        res.append(summarize(m, {})["kpi"])
    assert abs(res[0]["peak_bed_T_C"] - res[1]["peak_bed_T_C"]) < 60
    assert abs(res[0]["dri_t_h"] - res[1]["dri_t_h"]) < 0.25


def test_invalid_inputs_rejected():
    with pytest.raises(Exception):
        PlantConfig.model_validate({**preset_config().model_dump(), "pellet": {**preset_config().pellet.model_dump(),
                                                                                 "feed_tph": -1}})
    c = preset_config().model_dump()
    c["pellet"]["assay_dry_wt_pct"] = {"Fe_total": 90.0, "FeO": 1.0}
    with pytest.raises(InputValidationError):
        KilnModel(PlantConfig.model_validate(c))
