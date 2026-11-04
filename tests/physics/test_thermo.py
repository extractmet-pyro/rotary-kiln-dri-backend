import numpy as np
import pytest

from app.physics import kinetics as kn
from app.physics.thermo import K_BOUDOUARD, K_WGS, NIST_CP298, THERMO_DB, entry_arrays, equilibrium_K


@pytest.mark.parametrize("sp", sorted(NIST_CP298))
def test_cp298_against_nist(sp):
    cp = entry_arrays([THERMO_DB[sp]]).cp(298.15)[0] / 1000
    assert abs(cp - NIST_CP298[sp]) / NIST_CP298[sp] < 0.06


def test_enthalpy_dimension_and_continuity():
    a = entry_arrays([THERMO_DB["Fe3O4"]])
    h1, h2 = a.h(899.999)[0], a.h(900.001)[0]
    assert abs(h2 - h1) < 1e3  # J/kmol: continuous across Cp break
    assert a.h(298.15)[0] == pytest.approx(THERMO_DB["Fe3O4"].hf298 * 1000)


def test_fastK_equals_general():
    T = np.array([800.0, 1000.0, 1300.0])
    assert np.allclose(K_BOUDOUARD(T), equilibrium_K({"C": -1, "CO2": -1, "CO": 2}, T))
    assert np.allclose(K_WGS(T), equilibrium_K({"CO": -1, "H2O": -1, "CO2": 1, "H2": 1}, T))


def test_boudouard_crossover_near_700C():
    T = np.linspace(850, 1150, 301)
    k = K_BOUDOUARD(T)
    T1 = T[np.argmin(np.abs(np.log(k)))]
    assert 930 < T1 < 1030


@pytest.mark.parametrize("T", [1000.0, 1173.0, 1273.0])
def test_logK_fits_consistent_with_thermo_db(T):
    x_fit = kn.x_eq("wus_CO", T)
    x_db = 1 / (1 + equilibrium_K({"FeO": -1, "CO": -1, "Fe": 1, "CO2": 1}, T))
    assert abs(x_fit - x_db) < 0.12
    assert 0.55 < x_fit < 0.75  # Fe/FeO CO fraction band (classical diagram)
