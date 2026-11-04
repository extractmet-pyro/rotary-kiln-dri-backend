"""Downstream units at aggregate fidelity: rotary product cooler, magnetic
separation and screening, and the off-gas train (dust settling chamber,
after-burning chamber, waste-heat recovery boiler, ESP, ID fan, stack).

These are lumped steady models.  System boundaries are declared in each result.
"""
from __future__ import annotations

import math

import numpy as np

from app.core.units import NTP, P_ATM, R_J_PER_KMOL_K, C_to_K, kmolps_to_nm3h, nm3h_to_kmolps
from app.physics.species import AW, EL, GI, NG, SI, SOLIDS


def _air_vec(nm3h, y_h2o):
    v = np.zeros(NG)
    k = nm3h_to_kmolps(nm3h, NTP)
    v[GI["O2"]], v[GI["N2"]] = 0.2095 * k, 0.7905 * k
    v[GI["H2O"]] = k * y_h2o / (1 - y_h2o)
    return v


def _solve_T(ms, F, H_target, T0=1200.0):
    T = T0
    for _ in range(60):
        f = float(ms.h_g(T) @ F) - H_target
        d = float(ms.cp_g(T) @ F)
        dT = -f / max(d, 1e-12)
        T = min(max(T + max(min(dT, 400), -400), 250.0), 3000.0)
        if abs(dT) < 1e-6:
            break
    return T


def product_cooler(model, n_in, T_in):
    """Rotary cooler (indirect water spray on shell).  Exponential approach:
    T_out = T_w + (T_in - T_w) exp(-UA / (m cp)).  Optional O2 ingress
    re-oxidises metallic Fe to FeO (2Fe + O2 -> 2FeO) before cooling."""
    cfg, ms = model.cfg, model.ms
    c = cfg.cooler
    n = n_in.copy()
    o2 = nm3h_to_kmolps(c.O2_ingress_nm3h, NTP) * 0.2095
    reox = min(o2, 0.5 * n[SI["Fe"]])
    n[SI["Fe"]] -= 2 * reox
    n[SI["FeO"]] += 2 * reox
    m = float(ms.mw_s @ n)
    cp = float(ms.cp_s(0.5 * (T_in + 373.0)) @ n) / max(m, 1e-9)
    Tw = C_to_K(c.water_inlet_C)
    UA = c.UA_kW_K * 1e3
    T_out = Tw + (T_in - Tw) * math.exp(-UA / max(m * cp, 1e-9))
    Q = float((ms.h_s(T_in) - ms.h_s(T_out)) @ n)
    m_w = c.water_flow_m3h * 1000 / 3600
    dT_w = Q / max(m_w * 4186.0, 1e-9)
    return {"n_out": n, "T_out_K": T_out, "duty_W": Q, "water_outlet_C": c.water_inlet_C + dT_w,
            "water_dT_K": dT_w, "reoxidised_Fe_kmol_s": 2 * reox,
            "boundary": "kiln discharge -> cooler discharge (solids only)",
            "warnings": (["cooling water temperature rise > 25 K: check water flow"] if dT_w > 25 else []) +
                        (["O2 ingress into cooler re-oxidises DRI"] if reox > 0 else [])}


def magnetic_separation(model, n):
    """Split cooler discharge into magnetic DRI and non-magnetic char/ash."""
    s = model.cfg.separation
    mag = np.zeros_like(n)
    for sp in ("Fe2O3", "Fe3O4", "FeO", "Fe", "GANGUE", "FeS"):
        mag[SI[sp]] = n[SI[sp]] * (1 - s.dri_to_nonmagnetic_frac)
    for sp in ("C", "VM", "S"):
        mag[SI[sp]] = n[SI[sp]] * s.char_to_magnetic_frac
    for sp in ("ASH", "CaO", "MgO", "CaS", "CaCO3", "MgCO3"):
        mag[SI[sp]] = n[SI[sp]] * s.ash_to_magnetic_frac
    nonmag = n - mag
    return mag, nonmag


def stream_chemistry(model, n) -> dict:
    """Mass-based chemistry of a solids stream with traceable Fe accounting."""
    ms = model.ms
    mass = float(ms.mw_s @ n)
    if mass <= 0:
        return {"mass_kg_s": 0.0}
    fe_hem = 2 * AW["Fe"] * n[SI["Fe2O3"]]
    fe_mag = 3 * AW["Fe"] * n[SI["Fe3O4"]]
    fe_wus = AW["Fe"] * n[SI["FeO"]]
    fe_met = AW["Fe"] * n[SI["Fe"]]
    fe_s = AW["Fe"] * n[SI["FeS"]]
    el = ms.el_s.T @ n  # kmol elements (includes ash Fe)
    fe_ash = el[EL["Fe"]] * AW["Fe"] - (fe_hem + fe_mag + fe_wus + fe_met + fe_s)
    fe_tot = fe_hem + fe_mag + fe_wus + fe_met + fe_s + max(fe_ash, 0.0)
    gangue_w = model.ms.gangue_comp
    gsum = sum(gangue_w.values()) or 1.0
    m_g = n[SI["GANGUE"]]
    comp = {sp: float(n[SI[sp]] * ms.mw_s[SI[sp]] / mass * 100) for sp in SOLIDS}
    res = {
        "mass_kg_s": mass, "mass_t_h": mass * 3.6,
        "Fe_total_pct": fe_tot / mass * 100, "Fe_metallic_pct": fe_met / mass * 100,
        "metallization_pct": fe_met / fe_tot * 100 if fe_tot > 0 else 0.0,
        "FeO_pct": comp["FeO"], "Fe3O4_pct": comp["Fe3O4"], "Fe2O3_pct": comp["Fe2O3"],
        "C_pct": el[EL["C"]] * AW["C"] / mass * 100,
        "S_pct": el[EL["S"]] * AW["S"] / mass * 100,
        "P_pct": el[EL["P"]] * AW["P"] / mass * 100,
        "SiO2_pct": (m_g * gangue_w.get("SiO2", 0) / gsum) / mass * 100,
        "Al2O3_pct": (m_g * gangue_w.get("Al2O3", 0) / gsum) / mass * 100,
        "CaO_pct": (m_g * gangue_w.get("CaO", 0) / gsum + n[SI["CaO"]] * 56.077) / mass * 100,
        "MgO_pct": (m_g * gangue_w.get("MgO", 0) / gsum + n[SI["MgO"]] * 40.304) / mass * 100,
        "gangue_pct": comp["GANGUE"], "ash_pct": comp["ASH"], "char_C_pct": comp["C"],
        "species_wt_pct": comp,
        "fe_accounting_kg_s": {"Fe_in_Fe2O3": fe_hem, "Fe_in_Fe3O4": fe_mag, "Fe_in_FeO": fe_wus, "Fe_metal": fe_met,
                               "Fe_in_FeS": fe_s, "Fe_in_ash": max(fe_ash, 0.0)},
        "basis": "dry, solids only",
    }
    return res


def offgas_train(model, F_exit, T_exit_K, dust_n):
    """Dust settling chamber -> after-burning chamber (complete combustion with
    trim air to target O2) -> WHRB -> ESP -> ID fan -> stack."""
    cfg, ms = model.cfg, model.ms
    og = cfg.offgas
    y_air = model.y_air_h2o
    dust = dust_n * (1 - og.dsc_capture_efficiency)
    dsc_catch = dust_n * og.dsc_capture_efficiency
    F = F_exit.copy()
    H_in = float(ms.h_g(T_exit_K) @ F)
    # carbon in fine dust burns in the ABC (char fines)
    c_dust = dust[SI["C"]]
    # air needed so that dry O2 after combustion = target
    prod = F.copy()
    burn_co = F[GI["CO"]] * (1 - og.abc_co_slip_frac)
    prod[GI["CO"]] -= burn_co
    prod[GI["CO2"]] += burn_co + F[GI["CH4"]] + c_dust
    prod[GI["H2O"]] += F[GI["H2"]] + 2 * F[GI["CH4"]] + F[GI["H2S"]]
    prod[GI["SO2"]] += F[GI["H2S"]]
    prod[GI["H2"]] = 0.0
    prod[GI["CH4"]] = 0.0
    prod[GI["H2S"]] = 0.0
    o2_used = 0.5 * burn_co + 0.5 * F[GI["H2"]] + 2 * F[GI["CH4"]] + 1.5 * F[GI["H2S"]] + c_dust
    prod[GI["O2"]] -= o2_used
    target = og.abc_target_O2_dry_pct / 100.0
    dry = prod.sum() - prod[GI["H2O"]]
    # add air a (kmol/s): (O2 + 0.2095 a)/(dry + a(1)) = target  (air humidity small)
    a = max((target * dry - prod[GI["O2"]]) / (0.2095 - target), 0.0)
    air = np.zeros(NG)
    air[GI["O2"]], air[GI["N2"]] = 0.2095 * a, 0.7905 * a
    air[GI["H2O"]] = a * y_air / (1 - y_air)
    prod = prod + air
    if prod[GI["O2"]] < -1e-12:
        prod[GI["O2"]] = 0.0
    T_amb = model.T_amb
    H_dust_c = c_dust * float(ms.h_s(T_exit_K)[SI["C"]])
    H_tot = H_in + float(ms.h_g(T_amb) @ air) + H_dust_c
    H_abc = H_tot * 1.0
    T_ad = _solve_T(ms, prod, H_abc, T_exit_K)
    Q_abc_loss = og.abc_heat_loss_frac * float((ms.h_g(T_ad) - ms.h_g(298.15)) @ prod)
    T_abc = _solve_T(ms, prod, H_abc - Q_abc_loss, T_ad)
    res = {"kiln_exit_T_C": T_exit_K - 273.15, "abc_air_nm3h": kmolps_to_nm3h(a), "abc_T_C": T_abc - 273.15,
           "abc_adiabatic_T_C": T_ad - 273.15, "abc_heat_loss_kW": Q_abc_loss / 1e3}
    if og.whrb_enabled:
        T_w = C_to_K(og.whrb_exit_gas_C)
        Q_whrb = float((ms.h_g(T_abc) - ms.h_g(T_w)) @ prod) * og.whrb_efficiency if T_abc > T_w else 0.0
        steam = Q_whrb / (og.steam_enthalpy_rise_kJ_kg * 1e3)
        power = steam * 3600 / og.steam_to_power_kg_per_kWh
        T_stack_in = T_w
    else:
        Q_whrb, steam, power = 0.0, 0.0, 0.0
        T_stack_in = T_abc
    Vact = prod.sum() * R_J_PER_KMOL_K * T_stack_in / P_ATM
    fan_kW = Vact * og.idfan_pressure_rise_Pa / og.idfan_efficiency / 1e3
    dust_mass = float(ms.mw_s @ dust)
    stack_dust = dust_mass * (1 - og.esp_efficiency)
    nm3 = kmolps_to_nm3h(prod.sum())
    dry_nm3 = kmolps_to_nm3h(prod.sum() - prod[GI["H2O"]])
    y = prod / prod.sum()
    ydry = prod / (prod.sum() - prod[GI["H2O"]])
    res.update({
        "whrb_duty_kW": Q_whrb / 1e3, "steam_t_h": steam * 3.6, "power_potential_MWe": power / 1e3,
        "idfan_kW": fan_kW, "stack_flow_Nm3h_wet": nm3, "stack_flow_Nm3h_dry": dry_nm3,
        "stack_T_C": T_stack_in - 273.15,
        "stack_composition_vol_pct_wet": {g: float(y[GI[g]] * 100) for g in GI},
        "stack_composition_vol_pct_dry": {g: float(ydry[GI[g]] * 100) for g in GI if g != "H2O"},
        "dust_to_esp_kg_h": dust_mass * 3600, "esp_catch_kg_h": dust_mass * og.esp_efficiency * 3600,
        "dsc_catch_kg_h": float(ms.mw_s @ dsc_catch) * 3600,
        "stack_dust_mg_Nm3": stack_dust * 1e6 / max(dry_nm3 / 3600, 1e-9),
        "CO2_t_h": prod[GI["CO2"]] * 44.01 * 3.6, "SO2_kg_h": prod[GI["SO2"]] * 64.066 * 3600,
        "CO_slip_kg_h": prod[GI["CO"]] * 28.01 * 3600,
        "boundary": "kiln feed-end gas outlet -> stack (gas side); dust catch reported separately",
        "notes": "NOx not modelled (no defensible formation sub-model); SO2 from H2S oxidation only.",
    })
    return res
