"""Rate laws: pellet reduction (three-interface unreacted-core model), char
gasification, devolatilisation, drying, calcination, sulfur reactions.

Pellet model - three-interface shrinking core (Spitzer, Manning & Philbrook
1966; Tsay, Ray & Szekely 1976, AIChE J. 22:1064): concentric Fe | FeO |
Fe3O4 | Fe2O3 layers, external film, intraparticle diffusion through each
product layer and first-order reversible interfacial reactions.  The linear
resistance network gives a 4x4 tridiagonal system per cell solved in vector
form.  Pellets are assumed isothermal at the bed temperature.

Equilibria used as kinetic driving forces (log10 K = A/T + B, gas activities as
partial pressures) - classical fits reproduced in the iron-ore reduction
literature (e.g. von Bogdandy & Engell, "The Reduction of Iron Ores",
Springer 1971).  These are cross-checked against the internal NIST-based
thermo database in tests (agreement within 0.12 in CO fraction) and flagged
VERIFY-SOURCE in docs/MODEL_ASSUMPTIONS.md.

All Arrhenius parameters in the demo configuration are PLACEHOLDER values
chosen inside literature-typical ranges and must be calibrated (see
CALIBRATION_GUIDE.md).  They do not represent measured plant kinetics.
"""
from __future__ import annotations

import numpy as np

from app.core.units import R_J_PER_MOL_K
from app.physics.properties import fuller_diffusivity
from app.physics.thermo import K_BOUDOUARD, K_CALC_CA, K_CALC_MG, K_STEAM

LOGK = {  # (A, B): log10 K = A/T + B
    "hem_CO": (2726.0, 2.144),
    "mag_CO": (-1834.0, 2.170),
    "wus_CO": (688.0, -0.900),
    "hem_H2": (131.0, 4.420),
    "mag_H2": (-3410.0, 3.610),
    "wus_H2": (-827.0, 0.468),
}


def K_eq(step: str, T):
    A, B = LOGK[step]
    return 10.0 ** (A / np.asarray(T) + B)


def x_eq(step: str, T):
    """Equilibrium reducing-gas fraction CO/(CO+CO2) or H2/(H2+H2O)."""
    return 1.0 / (1.0 + K_eq(step, T))


def arrhenius(A, E, T):
    return A * np.exp(-E / (R_J_PER_MOL_K * np.asarray(T)))


def _tridiag4(a, b, c, d):
    from app.physics.heat_transfer import thomas
    return thomas(a, b, c, d)


def three_interface_rates(f_h, f_m, f_w, r0, T, C_pool, X, step_prefix, kin, eps_layer, tort):
    """Per-pellet interfacial rates (kmol reducing gas /s) for one reductant.

    f_h, f_m, f_w: fraction of pellet iron present as Fe2O3, Fe3O4, FeO.
    C_pool: total molar concentration of the reductant/oxidant pair (kmol/m3).
    X: reductant fraction of the pair in the bulk bed gas.
    Returns (rate_hem, rate_mag, rate_wus) - extents per pellet (kmol/s);
    negative values mean re-oxidation (only physically permitted for wustite).
    """
    T = np.asarray(T, dtype=float)
    co = step_prefix == "CO"
    gas_a, gas_b = ("CO", "CO2") if co else ("H2", "H2O")
    D = fuller_diffusivity(gas_a, gas_b, T)
    De = D * eps_layer / tort
    f_core = np.clip(f_h, 0.0, 1.0)
    rh = r0 * np.cbrt(f_core)
    rm = r0 * np.cbrt(np.clip(f_h + f_m, 0.0, 1.0))
    rw = r0 * np.cbrt(np.clip(f_h + f_m + f_w, 0.0, 1.0))
    mult = kin.reduction_multiplier * (1.0 if co else kin.h2_rate_factor)
    k_h = arrhenius(kin.k0_hem_CO_m_s, kin.E_hem_CO_J_mol, T) * mult
    k_m = arrhenius(kin.k0_mag_CO_m_s, kin.E_mag_CO_J_mol, T) * mult
    k_w = arrhenius(kin.k0_wus_CO_m_s, kin.E_wus_CO_J_mol, T) * mult
    sfx = "_CO" if co else "_H2"
    Kh, Km, Kw = K_eq("hem" + sfx, T), K_eq("mag" + sfx, T), K_eq("wus" + sfx, T)
    Ceq_h, Ceq_m, Ceq_w = C_pool / (1 + Kh), C_pool / (1 + Km), C_pool / (1 + Kw)
    # bulk concentration enters only through the affine solve below
    four_pi = 4.0 * np.pi
    k_f = kin.sherwood * D / (2 * r0)
    a_f = four_pi * r0 * r0 * k_f
    big = 1e3 * a_f + 1e-30

    def shell_cond(r_out, r_in):
        """Spherical-shell diffusion conductance 4 pi De / (1/r_in - 1/r_out)."""
        inv = 1.0 / np.maximum(r_in, 1e-12) - 1.0 / np.maximum(r_out, 1e-12)
        cond = np.minimum(four_pi * De / np.maximum(inv, 1e-12), big)
        return np.where(r_in > 1e-9, cond, 0.0)

    d1 = shell_cond(r0, rw)
    d2 = shell_cond(rw, rm)
    d3 = shell_cond(rm, rh)
    g_w = np.where(rw > 1e-9, four_pi * rw * rw * k_w * (1 + 1 / Kw), 0.0) * (f_w + f_m + f_h > 1e-9)
    g_m = np.where(rm > 1e-9, four_pi * rm * rm * k_m * (1 + 1 / Km), 0.0) * (f_m + f_h > 1e-9)
    g_h = np.where(rh > 1e-9, four_pi * rh * rh * k_h * (1 + 1 / Kh), 0.0) * (f_h > 1e-9)
    # unknowns Cs, Cw, Cm, Ch ; tridiagonal rows.  The system is linear in the
    # bulk concentration Cb, so it is solved for Cb = 0 and Cb = 1 and the
    # rates are returned as an affine function of X (fast bisection on X).
    n = np.size(T)
    A = np.zeros((n, 4))
    B = np.zeros((n, 4))
    Cc = np.zeros((n, 4))
    B[:, 0] = a_f + d1
    Cc[:, 0] = -d1
    A[:, 1] = -d1
    B[:, 1] = d1 + g_w + d2
    Cc[:, 1] = -d2
    A[:, 2] = -d2
    B[:, 2] = d2 + g_m + d3
    Cc[:, 2] = -d3
    A[:, 3] = -d3
    B[:, 3] = d3 + g_h + 1e-30
    pinned = B < 1e-28
    B[pinned] = 1.0
    A[pinned] = 0.0
    Cc[pinned] = 0.0
    out = []
    for cb in (0.0, 1.0):
        Dd = np.zeros((n, 4))
        Dd[:, 0] = a_f * cb
        Dd[:, 1] = g_w * Ceq_w
        Dd[:, 2] = g_m * Ceq_m
        Dd[:, 3] = g_h * Ceq_h
        Dd[pinned] = cb
        sol = _tridiag4(A, B, Cc, Dd)
        out.append((g_h * (sol[:, 3] - Ceq_h), g_m * (sol[:, 2] - Ceq_m), g_w * (sol[:, 1] - Ceq_w)))
    base = np.array(out[0])
    slope = np.array(out[1]) - base  # per unit Cb (kmol/m3)

    def rates(X):
        r = base + slope * (C_pool * X)
        return np.maximum(r[0], 0.0), np.maximum(r[1], 0.0), r[2]

    if X is None:
        return rates
    return rates(X)


def boudouard_rate(n_C_kmol, T, p_co2_atm, p_co_atm, kin, reactivity, size_mm, K=None, k=None):
    """kmol C/s; Langmuir-Hinshelwood form with CO inhibition and reversibility."""
    if k is None:
        k = arrhenius(kin.boudouard_A_per_s_atm, kin.boudouard_E_J_mol, T) * kin.gasification_multiplier
        k = k * reactivity * (8.0 / max(size_mm, 0.5)) ** 0.5
    if K is None:
        K = K_BOUDOUARD(T)
    drive = p_co2_atm - p_co_atm ** 2 / K
    r = k * n_C_kmol * drive / (1.0 + kin.boudouard_K_CO_per_atm * p_co_atm)
    return np.where(r >= 0, r, kin.reverse_boudouard_factor * r)


def steam_gasification_rate(n_C_kmol, T, p_h2o_atm, p_co_atm, p_h2_atm, kin, reactivity, size_mm):
    k = arrhenius(kin.boudouard_A_per_s_atm, kin.boudouard_E_J_mol, T) * kin.gasification_multiplier
    k = k * kin.steam_gasif_factor * reactivity * (8.0 / max(size_mm, 0.5)) ** 0.5
    K = K_STEAM(T)
    drive = p_h2o_atm - p_co_atm * p_h2_atm / K
    return np.maximum(k * n_C_kmol * drive / (1.0 + kin.boudouard_K_CO_per_atm * p_co_atm), 0.0)


def devol_rate(m_vm_kg, T, kin):
    return m_vm_kg * arrhenius(kin.devol_A_per_s, kin.devol_E_J_mol, T)


def evaporation_rate(n_h2o_kmol, T, kin):
    return n_h2o_kmol * arrhenius(kin.evap_A_per_s, kin.evap_E_J_mol, T)


def calcination_rates(n_caco3, n_mgco3, T, p_co2_atm, kin):
    Kca = K_CALC_CA(T)  # = p_eq(atm)
    Kmg = K_CALC_MG(T)
    r_ca = n_caco3 * arrhenius(kin.calc_ca_A_per_s, kin.calc_ca_E_J_mol, T) * np.maximum(1 - p_co2_atm / Kca, 0.0)
    r_mg = n_mgco3 * arrhenius(kin.calc_mg_A_per_s, kin.calc_mg_E_J_mol, T) * np.maximum(1 - p_co2_atm / Kmg, 0.0)
    return r_ca, r_mg


def arthur_co_co2_ratio(T):
    """Primary CO/CO2 product ratio of carbon oxidation, Arthur J.R. (1951)
    Trans. Faraday Soc. 47:164: CO/CO2 = 2500 exp(-6240/T)."""
    return 2500.0 * np.exp(-6240.0 / np.asarray(T))
