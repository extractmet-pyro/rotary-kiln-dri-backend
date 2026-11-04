"""Unit manager. SI is used internally (kg, kmol, m, s, K, Pa, J).

Normal conditions (NTP) are configurable; default 273.15 K and 101.325 kPa
("Nm3" in Indian/European plant practice). Actual and normal gas volumes are
never conflated: every conversion states its basis explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass

R_J_PER_KMOL_K = 8314.462618  # universal gas constant, J/(kmol K)
R_J_PER_MOL_K = 8.314462618
SIGMA = 5.670374419e-8  # Stefan-Boltzmann, W/(m2 K4)
G = 9.80665
T_REF = 298.15  # thermochemical reference temperature, K
P_ATM = 101325.0


@dataclass(frozen=True)
class NormalConditions:
    T_K: float = 273.15
    P_Pa: float = 101325.0

    @property
    def molar_volume_m3_per_kmol(self) -> float:
        return R_J_PER_KMOL_K * self.T_K / self.P_Pa


NTP = NormalConditions()


def C_to_K(t_c: float) -> float:
    return t_c + 273.15


def K_to_C(t_k: float) -> float:
    return t_k - 273.15


def tph_to_kgps(tph: float) -> float:
    return tph * 1000.0 / 3600.0


def kgps_to_tph(kgps: float) -> float:
    return kgps * 3.6


def nm3h_to_kmolps(nm3h: float, ntp: NormalConditions = NTP) -> float:
    """Normal volumetric flow (Nm3/h, at the declared NTP) -> kmol/s."""
    return nm3h / 3600.0 / ntp.molar_volume_m3_per_kmol


def kmolps_to_nm3h(kmolps: float, ntp: NormalConditions = NTP) -> float:
    return kmolps * 3600.0 * ntp.molar_volume_m3_per_kmol


def kmolps_to_actual_m3ps(kmolps: float, T_K: float, P_Pa: float) -> float:
    """Actual volumetric flow at (T, P) — distinct from normal volume."""
    return kmolps * R_J_PER_KMOL_K * T_K / P_Pa


def wet_to_dry_fraction(y_wet: float, y_h2o_wet: float) -> float:
    """Convert a wet-basis mole fraction to dry basis."""
    if not 0.0 <= y_h2o_wet < 1.0:
        raise ValueError("water mole fraction must be in [0,1)")
    return y_wet / (1.0 - y_h2o_wet)


def dry_to_wet_fraction(y_dry: float, y_h2o_wet: float) -> float:
    return y_dry * (1.0 - y_h2o_wet)


def GJ_per_t(energy_W: float, product_kgps: float) -> float:
    """Specific energy, GJ per tonne of product, from W and kg/s."""
    if product_kgps <= 0:
        return float("nan")
    return energy_W / product_kgps / 1.0e6  # J/kg == GJ/t / 1e6 * 1e6


def pct(x: float) -> float:
    return 100.0 * x
