"""Assemble traceable results (profiles, balances, quality, energy, emissions)
from a solved KilnModel.  Every KPI is derived from species inventories."""
from __future__ import annotations

import math

import numpy as np

from app.core.units import kmolps_to_nm3h
from app.physics import bed_transport as bt
from app.physics.balances import EnergyAccountant, element_audit, reaction_heat_summary
from app.physics.cooler import magnetic_separation, offgas_train, product_cooler, stream_chemistry
from app.physics.reactions import REDUCTION_IDS, RID
from app.physics.species import GASES, GI, SI, SOLIDS

MODEL_VERSION = "rk-dri-physics 1.0.0"


def _r(a, nd=4):
    a = np.asarray(a, dtype=float)
    a = np.where(np.isfinite(a), a, np.nan)
    return [None if not np.isfinite(x) else round(float(x), nd) for x in a.ravel()]


def smooth_labels(labels, min_cells: int = 3):
    """Majority filter (window 3) then merge runs shorter than min_cells into the preceding zone."""
    lab = list(labels)
    n = len(lab)
    sm = lab[:]
    for j in range(1, n - 1):
        if lab[j - 1] == lab[j + 1] != lab[j]:
            sm[j] = lab[j - 1]
    runs, start = [], 0
    for j in range(1, n + 1):
        if j == n or sm[j] != sm[start]:
            runs.append([sm[start], start, j])
            start = j
    merged = []
    for r in runs:
        if merged and (r[2] - r[1]) < min_cells and r is not runs[-1]:
            merged[-1][2] = r[2]
        elif merged and merged[-1][0] == r[0]:
            merged[-1][2] = r[2]
        else:
            merged.append(r)
    out = []
    for nm, a, b in merged:
        out += [nm] * (b - a)
    return out


def label_segments(labels, z_edges):
    segs, start = [], 0
    for j in range(1, len(labels) + 1):
        if j == len(labels) or labels[j] != labels[start]:
            segs.append({"zone": labels[start], "z_start_m": float(z_edges[start]), "z_end_m": float(z_edges[j])})
            start = j
    return segs


def infer_zones(model, st, d):
    """Zones inferred from state (not fixed positions)."""
    n = st.n
    N = model.N
    fe_t = 2 * n[SI["Fe2O3"]] + 3 * n[SI["Fe3O4"]] + n[SI["FeO"]] + n[SI["Fe"]]
    met = n[SI["Fe"]] / np.maximum(fe_t, 1e-12)
    red = d.rates[REDUCTION_IDS].sum(0)
    Tc = st.Ts - 273.15
    red_thr = 0.15 * max(float(red.max()), 1e-12)  # relative to peak rate (scale-independent)
    labels = []
    for j in range(N):
        if n[SI["H2O_l"], j] * 18.015 > 0.002 * (model.ms.mw_s @ n[:, j]):
            lab = "drying"
        elif Tc[j] < 700 and (d.rates[RID["R16_DEVOL"], j] > 1e-4 or n[SI["VM"], j] > 1.0):
            lab = "devolatilisation"
        elif red[j] > red_thr and Tc[j] >= 750 and met[j] < 0.995:
            lab = "reduction"
        elif met[j] < 0.05:
            lab = "preheating"
        else:
            lab = "discharge/soak"
        labels.append(lab)
    labels = smooth_labels(labels)
    segs = label_segments(labels, model.z_edges)
    return labels, segs


def accretion_risk(model, st, d):
    """Mechanistic accretion/ring-formation RISK PROXY (0-1).  Not a wall-growth
    model; it must not be presented as ring thickness.  Components: thermal
    margin to coal-ash initial deformation temperature, wustite availability
    (fayalite former), ash loading, basicity of non-pellet solids, fines/dust."""
    cfg = model.cfg
    n = st.n
    idt = cfg.coal.feed_coal.ash_initial_deformation_C + 273.15
    # bed/wall contact temperature (mean of covered-wall face and bed) vs ash fusion
    T_hot = 0.5 * (d.T_face_in + st.Ts)
    r_T = 1.0 / (1.0 + np.exp(-(T_hot - (idt - 120.0)) / 35.0))
    fe_t = 2 * n[SI["Fe2O3"]] + 3 * n[SI["Fe3O4"]] + n[SI["FeO"]] + n[SI["Fe"]]
    r_feo = np.clip(2.0 * n[SI["FeO"]] / np.maximum(fe_t, 1e-12), 0, 1)
    mass = model.ms.mw_s @ n
    r_ash = np.clip(n[SI["ASH"]] / np.maximum(mass, 1e-9) / 0.25, 0, 1)
    ash = model.ms.ash_comp
    acid = ash.get("SiO2", 0) + ash.get("Al2O3", 0)
    base_ash = ash.get("CaO", 0) + ash.get("MgO", 0)
    tot_ash = sum(ash.values()) or 1.0
    m_ash = n[SI["ASH"]]
    basic = (m_ash * base_ash / tot_ash + n[SI["CaO"]] * 56.077 + n[SI["MgO"]] * 40.304) / np.maximum(
        m_ash * acid / tot_ash, 1e-9)
    r_bas = np.clip(1.0 - basic, 0, 1)
    r_dust = np.clip(d.u_g / 6.0, 0, 1)
    chem = 0.4 * r_feo + 0.3 * r_ash + 0.2 * r_bas + 0.1 * r_dust
    risk = r_T * (0.35 + 0.65 * chem)
    return {"index": _r(risk, 3), "components": {"thermal": _r(r_T, 3), "wustite": _r(r_feo, 3), "ash": _r(r_ash, 3),
                                                  "low_basicity": _r(r_bas, 3), "dust": _r(r_dust, 3)},
            "max": float(risk.max()), "z_at_max_m": float(model.zc[int(np.argmax(risk))]),
            "band": "high" if risk.max() > 0.6 else "medium" if risk.max() > 0.3 else "low",
            "validation_status": "UNVALIDATED PROXY - requires plant ring/inspection history"}


def summarize(model, solver_status: dict | None = None, mode: str = "OFFLINE_SIMULATION") -> dict:
    cfg, ms, st, d = model.cfg, model.ms, model.state, model.diag
    N = model.N
    z = model.zc
    n = st.n
    acct = EnergyAccountant(ms)
    # ------------------------------------------------------------------ profiles
    fe_t = 2 * n[SI["Fe2O3"]] + 3 * n[SI["Fe3O4"]] + n[SI["FeO"]] + n[SI["Fe"]]
    fe_safe = np.maximum(fe_t, 1e-12)
    met = n[SI["Fe"]] / fe_safe * 100
    oxy_rem = 1 - (3 * n[SI["Fe2O3"]] + 4 * n[SI["Fe3O4"]] + n[SI["FeO"]]) / np.maximum(1.5 * fe_t, 1e-12)
    mass = ms.mw_s @ n
    wt = {sp: _r(n[SI[sp]] * ms.mw_s[SI[sp]] / np.maximum(mass, 1e-9) * 100, 3) for sp in SOLIDS}
    F = st.F
    Ft = F.sum(0)
    ywet = {g: _r(F[GI[g]] / np.maximum(Ft, 1e-12) * 100, 3) for g in GASES}
    dry = np.maximum(Ft - F[GI["H2O"]], 1e-12)
    ydry = {g: _r(F[GI[g]] / dry * 100, 3) for g in GASES if g != "H2O"}
    geo = d.geo
    u_s = np.maximum(d.u_s, 1e-7)
    res_cum = np.cumsum(model.dz / u_s) / 3600.0
    # pressure (draft at feed end, friction toward discharge)
    f_fric = 0.03
    dp = f_fric * model.dz / geo["D_e"] * 0.5 * geo["rho_g"] * geo["u_g"] ** 2
    p_rel = cfg.offgas.kiln_feed_end_draft_Pa + np.cumsum(dp)
    co_co2 = F[GI["CO"]] / np.maximum(F[GI["CO2"]], 1e-12)
    h2_h2o = F[GI["H2"]] / np.maximum(F[GI["H2O"]], 1e-12)
    labels, segs = infer_zones(model, st, d)
    acc = accretion_risk(model, st, d)
    R = d.rates
    prof = {
        "z_m": _r(z, 3),
        "T_bed_C": _r(st.Ts - 273.15, 2), "T_gas_C": _r(st.Tg - 273.15, 2),
        "T_wall_hot_face_C": _r(d.T_face_in - 273.15, 2), "T_shell_C": _r(d.T_shell - 273.15, 2),
        "metallization_pct": _r(met, 3), "oxygen_removal_pct": _r(oxy_rem * 100, 3),
        "Fe_phase_fraction": {"Fe2O3": _r(2 * n[SI["Fe2O3"]] / fe_safe, 4), "Fe3O4": _r(3 * n[SI["Fe3O4"]] / fe_safe, 4),
                              "FeO": _r(n[SI["FeO"]] / fe_safe, 4), "Fe": _r(n[SI["Fe"]] / fe_safe, 4)},
        "solids_wt_pct": wt,
        "gas_vol_pct_wet": ywet, "gas_vol_pct_dry": ydry,
        "bed_CO_fraction_X": _r(st.X, 4), "CO_CO2_ratio": _r(co_co2, 4), "H2_H2O_ratio": _r(h2_h2o, 4),
        "char_C_kg_per_m": _r(n[SI["C"]] * 12.011 / model.dz, 3),
        "bed_holdup_t_per_m": _r(mass / model.dz / 1000, 4),
        "bed_depth_m": _r(geo["h"], 4), "fill_pct": _r(geo["fill"] * 100, 3),
        "solids_velocity_mm_s": _r(u_s * 1000, 4), "cumulative_residence_h": _r(res_cum, 4),
        "gas_velocity_m_s": _r(geo["u_g"], 4), "gas_flow_Nm3h": _r(kmolps_to_nm3h(Ft), 1),
        "pressure_rel_Pa": _r(p_rel, 2),
        "gas_emissivity": _r(d.eps_g, 4), "h_gas_bed_conv_W_m2K": _r(d.h_gs, 3),
        "h_gas_wall_conv_W_m2K": _r(d.h_gw, 3), "h_wall_bed_contact_W_m2K": _r(d.h_cw, 3),
        "q_gas_to_bed_kW_m": _r(d.Q_gs / model.dz / 1e3, 4), "q_gas_to_wall_kW_m": _r(d.Q_gw / model.dz / 1e3, 4),
        "q_wall_to_bed_contact_kW_m": _r(d.Q_cw / model.dz / 1e3, 4),
        "q_wall_to_bed_rad_kW_m": _r(d.Q_wb / model.dz / 1e3, 4),
        "q_shell_loss_kW_m": _r(d.Q_shell / model.dz / 1e3, 4),
        "shell_heat_flux_kW_m2": _r(d.Q_shell / (model.dz * math.pi * 2 * model.wall.r_out) / 1e3, 4),
        "reduction_rate_kmolO_h_m": _r(R[REDUCTION_IDS].sum(0) * 3600 / model.dz, 4),
        "boudouard_rate_kmolC_h_m": _r(R[RID["R07_BOUDOUARD"]] * 3600 / model.dz, 4),
        "devol_rate_kg_h_m": _r(R[RID["R16_DEVOL"]] * 3600 / model.dz, 4),
        "evaporation_rate_kg_h_m": _r(R[RID["R15_EVAP"]] * 18.015 * 3600 / model.dz, 4),
        "freeboard_CO_burn_kmol_h_m": _r(d.fb_rates[RID["R12_CO_OX"]] * 3600 / model.dz, 4),
        "zone_label": labels,
        "accretion_risk": acc["index"],
    }
    rates_profile = {name: _r(R[k] * 3600 / model.dz, 5) for k, name in enumerate(model.rxn.names)
                     if model.rxn.location[k] != "freeboard"}
    rates_profile.update({name: _r(d.fb_rates[k] * 3600 / model.dz, 5) for k, name in enumerate(model.rxn.names)
                          if model.rxn.location[k] == "freeboard"})
    wall_T = (st.Tw - 273.15)
    # ----------------------------------------------------------------- products
    dis = d.out_flow  # kmol/s
    T_dis = float(st.Ts[-1])
    cool = product_cooler(model, dis, T_dis)
    mag, nonmag = magnetic_separation(model, cool["n_out"])
    dri = stream_chemistry(model, mag)
    nm = stream_chemistry(model, nonmag)
    kiln_out = stream_chemistry(model, dis)
    res_h = float(res_cum[-1])
    p = cfg.pellet
    fines_frac = float(np.clip(0.01 * (1.2 * p.abrasion_index_pct + 2.0 * (cfg.geometry.rpm / 0.4) * (res_h / 5.0)),
                               0.02, 0.30))
    dri_t_h = dri["mass_t_h"]
    # ----------------------------------------------------------------- off-gas
    dust_n = d.dust.sum(1)
    og = offgas_train(model, F[:, 0], float(st.Tg[0]), dust_n)
    # ----------------------------------------------------------------- energy ledger
    feed, inj = model.feed, model.inj.sum(1)
    T_f, T_a = model.T_feed, model.T_air
    air_tot = model.gas_boundary + model.air_src.sum(1)
    c_coal_f = acct.solids(model.coal_feed_vec, T_f)
    c_coal_i = acct.solids(inj, T_a)
    other_feed = feed - model.coal_feed_vec
    c_other = acct.solids(other_feed, T_f)
    c_air = acct.gas(air_tot, T_a)
    dis_c, dis_s = acct.solids(dis, T_dis)
    gas_c, gas_s = acct.gas(F[:, 0], float(st.Tg[0]))
    dust_c, dust_s = acct.solids(dust_n, T_dis)
    # split discharge chemical energy into metallic iron/oxides vs char
    fe_species = np.zeros_like(dis)
    for sp in ("Fe", "FeO", "Fe3O4", "FeS"):
        fe_species[SI[sp]] = dis[SI[sp]]
    fe_c, _ = acct.solids(fe_species, T_dis)
    Q_shell = float(d.Q_shell.sum())
    audit = element_audit(model.logs, ms, window=min(len(model.logs), 60))
    acc_W = 0.0
    if audit.get("available"):
        Lw = model.logs[-min(len(model.logs), 60):]
        span = sum(1 for _ in Lw)
        dt_log = (Lw[-1].t - Lw[0].t) / max(span - 1, 1)
        acc_W = audit["energy"]["accumulation_J"] / max(span * dt_log, 1e-9)
    inputs = {
        "feed_coal_chemical_kW": c_coal_f[0] / 1e3, "injection_coal_chemical_kW": c_coal_i[0] / 1e3,
        "pellet_flux_char_chemical_kW": c_other[0] / 1e3,
        "feed_sensible_kW": (c_coal_f[1] + c_other[1] + c_coal_i[1]) / 1e3, "air_sensible_kW": c_air[1] / 1e3,
    }
    outputs = {
        "reduced_iron_chemical_kW": fe_c / 1e3,
        "char_and_other_chemical_in_discharge_kW": (dis_c - fe_c) / 1e3,
        "discharge_sensible_kW": dis_s / 1e3,
        "offgas_chemical_kW": gas_c / 1e3, "offgas_sensible_kW": gas_s / 1e3,
        "dust_chemical_kW": dust_c / 1e3, "dust_sensible_kW": dust_s / 1e3,
        "shell_loss_kW": Q_shell / 1e3, "storage_rate_kW": acc_W / 1e3,
    }
    tot_in = sum(inputs.values())
    tot_out = sum(outputs.values())
    ledger = {"inputs_kW": inputs, "outputs_kW": outputs, "total_in_kW": tot_in, "total_out_kW": tot_out,
              "residual_kW": tot_in - tot_out, "relative_residual": abs(tot_in - tot_out) / max(abs(tot_in), 1e-9),
              "reference": "LHV-type: fully oxidised elements at 298.15 K (see balances.py)",
              "boundary": "kiln shell (solids feed chute -> discharge hood; gas discharge-end inlet -> feed-end outlet)"}
    # ----------------------------------------------------------------- KPIs
    coal_tph = cfg.coal.feed_coal_tph + cfg.coal.injection_coal_tph
    fe_met_t_h = dri["Fe_metallic_pct"] / 100 * dri_t_h
    coal_energy_kW = (c_coal_f[0] + c_coal_i[0]) / 1e3
    fc_in = (model.coal_feed_vec[SI["C"]] + inj[SI["C"]] + model.feed[SI["C"]] - model.coal_feed_vec[SI["C"]]) * 12.011
    c_out_dis = dis[SI["C"]] * 12.011
    # electrical estimate
    theta = geo["theta"]
    r_cg = 4 * model.R * np.sin(theta / 2) ** 3 / (3 * np.maximum(theta - np.sin(theta), 1e-9))
    beta = math.radians(cfg.geometry.dynamic_repose_angle_deg)
    omega = 2 * math.pi * cfg.geometry.rpm / 60
    # bed-lifting torque + empirical rolling/girth-gear/seal friction (mu_eff = 0.06) on shell+lining mass
    lin_mass = sum(math.pi * 2 * (model.R + 0.1) * lay.thickness_m * lay.rho_kg_m3 for lay in cfg.lining.layers) + \
        math.pi * 2 * model.wall.r_out * cfg.lining.shell_thickness_m * 7850.0
    m_rot = lin_mass * model.L + float(geo["mass_bed"].sum())
    v_tyre = math.pi * 2 * model.wall.r_out * cfg.geometry.rpm / 60.0
    drive_kW = float((geo["mass_bed"] * 9.81 * r_cg * math.sin(beta)).sum() * omega + 0.06 * m_rot * 9.81 * v_tyre) \
        / 0.80 / 1e3
    air_nm3h = kmolps_to_nm3h(air_tot.sum() - air_tot[GI["H2O"]])
    air_fan_kW = air_nm3h / 3600 * (273.15 + cfg.air.air_temperature_C) / 273.15 * 4500 / 0.7 / 1e3
    cooler_kW = 25.0 * (cfg.pellet.feed_tph / 6.8) ** 0.8
    aux_kW = 60.0 * (cfg.pellet.feed_tph / 6.8) ** 0.8
    elec_kW = drive_kW + air_fan_kW + og["idfan_kW"] + cooler_kW + aux_kW
    kpi = {
        "metallization_pct": dri["metallization_pct"], "Fe_total_pct": dri["Fe_total_pct"],
        "Fe_metallic_pct": dri["Fe_metallic_pct"], "FeO_pct": dri["FeO_pct"], "C_pct": dri["C_pct"],
        "S_pct": dri["S_pct"], "P_pct": dri["P_pct"],
        "dri_t_h": dri_t_h, "dri_tpd": dri_t_h * 24, "dri_lump_t_h": dri_t_h * (1 - fines_frac),
        "dri_fines_t_h": dri_t_h * fines_frac, "fines_fraction_pct": fines_frac * 100,
        "dri_yield_t_per_t_pellet": dri_t_h / max(cfg.pellet.feed_tph, 1e-9),
        "pellet_t_per_t_dri": cfg.pellet.feed_tph / max(dri_t_h, 1e-9),
        "coal_kg_per_t_dri": coal_tph * 1000 / max(dri_t_h, 1e-9),
        "coal_kg_per_t_Fe_met": coal_tph * 1000 / max(fe_met_t_h, 1e-9),
        "feed_coal_share_pct": cfg.coal.feed_coal_tph / max(coal_tph, 1e-9) * 100,
        "fixed_carbon_utilisation_pct": (1 - c_out_dis / max(fc_in, 1e-9)) * 100,
        "char_C_discharge_t_h": c_out_dis * 3.6,
        "nonmagnetic_t_h": nm.get("mass_t_h", 0.0),
        "coal_energy_GJ_per_t_dri": coal_energy_kW * 3.6 / max(dri_t_h, 1e-9) / 1e3 * 1e3 / 1e3,
        "net_energy_GJ_per_t_dri": (coal_energy_kW - og["whrb_duty_kW"]) * 3.6 / max(dri_t_h, 1e-9) / 1e3,
        "electrical_kWh_per_t_dri": elec_kW / max(dri_t_h, 1e-9),
        "electrical_kW": elec_kW, "kiln_drive_kW": drive_kW, "air_fans_kW": air_fan_kW,
        "shell_loss_kW": Q_shell / 1e3, "shell_loss_GJ_per_t_dri": Q_shell / 1e3 * 3.6 / max(dri_t_h, 1e-9) / 1e3,
        "exit_gas_T_C": float(st.Tg[0] - 273.15), "exit_gas_Nm3h_wet": kmolps_to_nm3h(F[:, 0].sum()),
        "exit_CO_vol_pct_dry": ydry["CO"][0], "exit_CO2_vol_pct_dry": ydry["CO2"][0], "exit_O2_vol_pct_dry": ydry["O2"][0],
        "peak_bed_T_C": float(st.Ts.max() - 273.15), "z_peak_bed_m": float(z[int(np.argmax(st.Ts))]),
        "peak_gas_T_C": float(st.Tg.max() - 273.15), "peak_shell_T_C": float(d.T_shell.max() - 273.15),
        "discharge_bed_T_C": T_dis - 273.15, "cooler_discharge_T_C": cool["T_out_K"] - 273.15,
        "residence_time_h": res_h, "holdup_over_feed_h": float(mass.sum() / max(float(ms.mw_s @ model.feed), 1e-9) / 3600),
        "holdup_t": float(mass.sum() / 1000), "mean_fill_pct": float(geo["fill"].mean() * 100),
        "sullivan_residence_h": bt.sullivan_residence_time_s(model.L, 2 * model.R, cfg.geometry.rpm, cfg.geometry.slope_pct,
                                                             cfg.geometry.dynamic_repose_angle_deg) / 3600,
        "kiln_draft_feed_end_Pa": float(cfg.offgas.kiln_feed_end_draft_Pa),
        "pressure_drop_Pa": float(p_rel[-1] - p_rel[0]),
        "steam_t_h": og["steam_t_h"], "power_potential_MWe": og["power_potential_MWe"],
        "CO2_t_per_t_dri": og["CO2_t_h"] / max(dri_t_h, 1e-9), "SO2_kg_h": og["SO2_kg_h"],
        "accretion_risk_max": acc["max"], "accretion_band": acc["band"],
    }
    eco = cfg.economics
    cost = (cfg.pellet.feed_tph * eco.pellet_INR_t + coal_tph * eco.coal_INR_t + cfg.flux.dolomite_tph * eco.dolomite_INR_t
            + elec_kW / 1e3 * eco.power_INR_kWh * 1e3 - og["power_potential_MWe"] * 1e3 * eco.power_INR_kWh)
    kpi["variable_cost_INR_per_t_dri"] = cost / max(dri_t_h, 1e-9)
    kpi["margin_INR_per_h"] = dri_t_h * eco.dri_INR_t - cost
    # ----------------------------------------------------------------- material balance table
    def s_t(nv):
        return float(ms.mw_s @ nv) * 3.6

    def g_t(fv):
        return float(ms.mw_g @ fv) * 3.6
    a = cfg.air
    rows_in = [
        {"stream": "Pellets (wet)", "t_h": cfg.pellet.feed_tph, "T_C": T_f - 273.15, "basis": "as fed"},
        {"stream": "Feed-end coal", "t_h": cfg.coal.feed_coal_tph, "T_C": T_f - 273.15, "basis": "as received"},
        {"stream": "Injection coal", "t_h": cfg.coal.injection_coal_tph, "T_C": T_a - 273.15, "basis": "as received"},
        {"stream": "Dolomite", "t_h": cfg.flux.dolomite_tph, "T_C": T_f - 273.15, "basis": "as fed"},
        {"stream": "Recycled char", "t_h": cfg.flux.recycle_char_tph, "T_C": T_f - 273.15, "basis": "as fed"},
        {"stream": "Primary + carrier + discharge-seal air", "t_h": g_t(model.gas_boundary), "T_C": T_a - 273.15,
         "Nm3h": a.primary_air_nm3h + a.injection_carrier_air_nm3h + a.leak_discharge_end_nm3h, "basis": "humid air"},
        {"stream": "Secondary air (all tubes) + feed-end leak", "t_h": g_t(model.air_src.sum(1)), "T_C": T_a - 273.15,
         "Nm3h": sum(t.flow_nm3h for t in a.secondary_tubes if t.available) + a.leak_feed_end_nm3h, "basis": "humid air"},
    ]
    rows_out = [
        {"stream": "DRI product (magnetic, after cooler)", "t_h": dri_t_h, "T_C": cool["T_out_K"] - 273.15,
         "composition": {k: v for k, v in dri.items() if k.endswith("_pct")}},
        {"stream": "Non-magnetic (char + ash + flux)", "t_h": nm.get("mass_t_h", 0.0), "T_C": cool["T_out_K"] - 273.15,
         "composition": {k: v for k, v in nm.items() if k.endswith("_pct")}},
        {"stream": "Dust entrained (to DSC/ESP)", "t_h": s_t(dust_n), "T_C": float(st.Tg[0] - 273.15)},
        {"stream": "Kiln off-gas (wet)", "t_h": g_t(F[:, 0]), "T_C": float(st.Tg[0] - 273.15),
         "Nm3h": kmolps_to_nm3h(F[:, 0].sum()), "composition_vol_pct_wet": {g: ywet[g][0] for g in GASES}},
    ]
    t_in = sum(r["t_h"] for r in rows_in)
    t_out = sum(r["t_h"] for r in rows_out)
    # input chemistry
    inputs_chem = {
        "pellet_species_dry_wt_pct": {k: v * 100 for k, v in model.pellet_species.items()},
        "pellet_gangue_wt_frac": model.ms.gangue_comp,
        "coal_blend_ar": {"FC": model.coal_blend.fc * 100, "VM": model.coal_blend.vm * 100, "ash": model.coal_blend.ash * 100,
                          "moisture": model.coal_blend.moisture * 100, "C": model.coal_blend.C * 100,
                          "H": model.coal_blend.H * 100, "O": model.coal_blend.O * 100, "N": model.coal_blend.N * 100,
                          "S": model.coal_blend.S * 100, "NCV_MJ_kg": model.coal_blend.ncv_J_per_kg / 1e6},
        "vm_products_kmol_per_kg": ms.vm_yield, "vm_soot_kmol_per_kg": ms.vm_soot, "vm_O_to_CO_split": ms.f_o_to_co,
        "ash_composition_kg": ms.ash_comp,
    }
    warnings = list(model.warnings) + list(set(d.warnings))
    if d.gas_clip > 1e-6:
        warnings.append(f"freeboard gas draw clipped by {d.gas_clip:.2e} kmol/s (bed demand exceeded supply)")
    if kpi["peak_bed_T_C"] > cfg.limits.max_bed_temperature_C:
        warnings.append(f"peak bed temperature {kpi['peak_bed_T_C']:.0f} C exceeds demo envelope "
                        f"{cfg.limits.max_bed_temperature_C:.0f} C")
    if kpi["metallization_pct"] < cfg.limits.min_metallization_pct:
        warnings.append(f"metallization {kpi['metallization_pct']:.1f} % below demo minimum {cfg.limits.min_metallization_pct} %")
    if acc["band"] == "high":
        warnings.append("accretion risk proxy HIGH (unvalidated)")
    return {
        "model_version": MODEL_VERSION, "mode": mode, "plant_config_version": cfg.meta.config_version,
        "plant": cfg.meta.model_dump(),
        "units": {"T": "C", "flow": "t/h", "gas": "Nm3/h (0 C, 101.325 kPa)", "energy": "kW / GJ per t DRI",
                  "composition": "wt % (solids, dry), vol % (gas, wet or dry as labelled)"},
        "geometry": {"length_m": model.L, "internal_radius_m": model.R, "shell_outer_radius_m": model.wall.r_out,
                     "n_cells": N, "dz_m": model.dz, "wall_node_radii_m": _r(model.wall.rm, 4),
                     "tube_positions": {t.tube_id: t.z_m for t in cfg.air.secondary_tubes},
                     "tube_flows_nm3h": {t.tube_id: t.flow_nm3h for t in cfg.air.secondary_tubes},
                     "injection_landing_weights": _r(model.inj_dist, 4)},
        "profiles": prof, "reaction_rates_kmol_h_m": rates_profile,
        "wall_temperature_field_C": [_r(row, 1) for row in wall_T],
        "zones": segs, "accretion": acc,
        "quality": {"dri": dri, "kiln_discharge": kiln_out, "nonmagnetic": nm},
        "cooler": {k: v for k, v in cool.items() if k != "n_out"},
        "offgas_train": og,
        "kpi": kpi,
        "material_balance": {"inputs": rows_in, "outputs": rows_out, "total_in_t_h": t_in, "total_out_t_h": t_out,
                             "closure_t_h": t_in - t_out,
                             "note": "air leaving as off-gas; small closure difference = in-kiln accumulation + "
                                     "cooler O2 pickup (reported separately in elemental audit)"},
        "elemental_balances": audit,
        "heat_balance": ledger,
        "reaction_summary": reaction_heat_summary(model, d.rates, d.fb_rates),
        "inputs_chemistry": inputs_chem,
        "solver_diagnostics": {**(solver_status or {}), "gas_newton_max_iter": d.gas_newton_max_iter,
                               "limiter_activations_last_step": d.limiter_active,
                               "transport_substeps": getattr(model, "_nsub", None)},
        "warnings": warnings,
        "labels": {"source": "PHYSICS-ESTIMATED (synthetic demo configuration)" if cfg.meta.provenance == "SYNTHETIC-DEMO"
                   else "PHYSICS-ESTIMATED", "validation": "model_not_validated"},
    }
