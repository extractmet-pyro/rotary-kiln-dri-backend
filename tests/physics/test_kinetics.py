import numpy as np

from app.physics import kinetics as kn
from app.schemas.plant import Kinetics


def test_no_reduction_at_equilibrium_or_without_reductant():
    kin = Kinetics()
    T = np.array([1273.0])
    Xeq = kn.x_eq("wus_CO", T)
    rh, rm, rw = kn.three_interface_rates(np.array([0.0]), np.array([0.0]), np.array([1.0]), 0.006, T,
                                          np.array([0.009]), Xeq, "CO", kin, np.array([0.4]), 3.0)
    assert abs(rw[0]) < 1e-12
    rh, rm, rw = kn.three_interface_rates(np.array([1.0]), np.array([0.0]), np.array([0.0]), 0.006, T,
                                          np.array([0.0]), np.array([0.8]), "CO", kin, np.array([0.4]), 3.0)
    assert rh[0] == 0 and rm[0] == 0


def test_reduction_increases_with_reducing_potential_and_temperature():
    kin = Kinetics()
    f = (np.array([0.0]), np.array([0.0]), np.array([0.6]))
    r1 = kn.three_interface_rates(*f, 0.006, np.array([1173.0]), np.array([0.01]), np.array([0.80]), "CO", kin,
                                  np.array([0.4]), 3.0)[2]
    r2 = kn.three_interface_rates(*f, 0.006, np.array([1173.0]), np.array([0.01]), np.array([0.95]), "CO", kin,
                                  np.array([0.4]), 3.0)[2]
    assert r2 > r1 > 0


def test_boudouard_zero_without_carbon_and_positive_with_co2():
    kin = Kinetics()
    assert kn.boudouard_rate(np.array([0.0]), np.array([1300.0]), 0.2, 0.6, kin, 1.0, 8.0)[0] == 0
    assert kn.boudouard_rate(np.array([10.0]), np.array([1300.0]), 0.2, 0.6, kin, 1.0, 8.0)[0] > 0


def test_arthur_ratio_increases_with_T():
    assert kn.arthur_co_co2_ratio(1300) > kn.arthur_co_co2_ratio(900)
