import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="rktest-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("MODEL_STORE_DIR", str(ROOT / "model_store"))
os.environ.setdefault("APP_ENV", "demo")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def steady100():
    from app.physics.finite_volume import KilnModel
    from app.physics.steady_state import solve_steady
    from app.schemas.plant import preset_config
    m = KilnModel(preset_config("RK-100TPD"))
    st = solve_steady(m)
    return m, st


@pytest.fixture(scope="session")
def fast_cfg():
    from app.schemas.plant import preset_config
    c = preset_config("RK-100TPD")
    c.numerics.n_cells = 18
    c.numerics.steady_max_steps = 700
    return c
