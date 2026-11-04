import math

import pytest

from app.core import units as u


def test_temperature_roundtrip():
    assert u.K_to_C(u.C_to_K(1050.0)) == pytest.approx(1050.0)


def test_normal_volume_kmol():
    assert u.NTP.molar_volume_m3_per_kmol == pytest.approx(22.414, rel=1e-3)
    assert u.kmolps_to_nm3h(u.nm3h_to_kmolps(12345.0)) == pytest.approx(12345.0)


def test_actual_vs_normal_volume_differ():
    k = u.nm3h_to_kmolps(3600.0)
    act = u.kmolps_to_actual_m3ps(k, 1273.15, 101325.0)
    assert act == pytest.approx(1273.15 / 273.15, rel=1e-3)


def test_dry_wet():
    assert u.dry_to_wet_fraction(u.wet_to_dry_fraction(0.12, 0.2), 0.2) == pytest.approx(0.12)
    with pytest.raises(ValueError):
        u.wet_to_dry_fraction(0.1, 1.0)


def test_tph():
    assert u.kgps_to_tph(u.tph_to_kgps(6.8)) == pytest.approx(6.8)
    assert u.GJ_per_t(1e6, 1.0) == pytest.approx(1.0)
    assert math.isnan(u.GJ_per_t(1.0, 0.0))
