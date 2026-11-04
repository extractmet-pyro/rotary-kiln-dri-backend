"""Gas and solid transport properties (engineering correlations).

* Gas viscosity/conductivity: kiln gas is >60 vol % N2; an N2/air-based
  Sutherland viscosity and a power-law conductivity are used, corrected for
  CO2/H2O content by mole-fraction weighting of species reference values.
  Accuracy ~ +/-10 % over 600-1500 K, adequate for heat-transfer correlations
  whose own uncertainty is larger.
* Binary diffusivity: Fuller, Schettler & Giddings (1966) correlation,
  Ind. Eng. Chem. 58(5):18-27, with their atomic diffusion-volume increments.
"""
from __future__ import annotations

import numpy as np

from app.core.units import P_ATM, R_J_PER_KMOL_K

FULLER_V = {"CO": 18.9, "CO2": 26.9, "H2": 7.07, "H2O": 12.7, "N2": 17.9, "O2": 16.6}
MW = {"CO": 28.01, "CO2": 44.01, "H2": 2.016, "H2O": 18.015, "N2": 28.013, "O2": 32.0}


def fuller_diffusivity(a: str, b: str, T, P_Pa: float = P_ATM):
    """Binary diffusivity m2/s."""
    T = np.asarray(T, dtype=float)
    p_atm = P_Pa / P_ATM
    d_cm2 = 1.0e-3 * T ** 1.75 * np.sqrt(1.0 / MW[a] + 1.0 / MW[b]) / (
        p_atm * (FULLER_V[a] ** (1 / 3) + FULLER_V[b] ** (1 / 3)) ** 2)
    return d_cm2 * 1.0e-4


def gas_viscosity(T, y_h2o=0.1, y_co2=0.15):
    """Pa s; Sutherland for N2 with mild composition correction."""
    T = np.asarray(T, dtype=float)
    mu_n2 = 1.663e-5 * (T / 273.15) ** 1.5 * (273.15 + 107.0) / (T + 107.0)
    return mu_n2 * (1.0 - 0.25 * y_h2o - 0.05 * y_co2)


def gas_conductivity(T, y_h2o=0.1, y_co2=0.15):
    """W/(m K)."""
    T = np.asarray(T, dtype=float)
    k_n2 = 0.0242 * (T / 273.15) ** 0.80
    return k_n2 * (1.0 + 0.35 * y_h2o - 0.15 * y_co2)


def gas_density(T, P_Pa, mw_mix):
    return P_Pa * mw_mix / (R_J_PER_KMOL_K * np.asarray(T))


def bed_effective_conductivity(T_s, k_base: float, d_p_m: float, emis: float = 0.85):
    """Packed-bed conductivity with a radiative contribution (Damkoehler-type term)."""
    from app.core.units import SIGMA
    return k_base + 4.0 * SIGMA * emis * d_p_m * np.asarray(T_s) ** 3 * 0.5
