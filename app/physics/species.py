"""Auditable species list, atom matrices and feed-assay -> species conversion.

Internal amounts are kmol for real species.  Lumped pseudo-species (GANGUE,
ASH, VM) carry amounts in kg (nominal MW = 1 kg/"kmol"), with composition-
specific element vectors and thermochemistry built from their assays, so the
element matrix stays exact.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.core.exceptions import InputValidationError
from app.physics.thermo import THERMO_DB, CoeffArrays, entry_arrays

ELEMENTS = ["Fe", "O", "C", "H", "N", "S", "Ca", "Mg", "Si", "Al", "Ti", "P"]
EL = {e: i for i, e in enumerate(ELEMENTS)}
AW = {"Fe": 55.845, "O": 15.999, "C": 12.011, "H": 1.008, "N": 14.007, "S": 32.06,
      "Ca": 40.078, "Mg": 24.305, "Si": 28.085, "Al": 26.982, "Ti": 47.867, "P": 30.974}

SOLIDS = ["Fe2O3", "Fe3O4", "FeO", "Fe", "GANGUE", "C", "VM", "ASH", "H2O_l",
          "CaCO3", "MgCO3", "CaO", "MgO", "S", "FeS", "CaS"]
GASES = ["CO", "CO2", "H2", "H2O", "O2", "N2", "CH4", "H2S", "SO2"]
PSEUDO = {"GANGUE", "ASH", "VM"}
SI = {s: i for i, s in enumerate(SOLIDS)}
GI = {g: i for i, g in enumerate(GASES)}
NS, NG = len(SOLIDS), len(GASES)

MAGNETIC = ["Fe2O3", "Fe3O4", "FeO", "Fe", "GANGUE", "FeS"]  # reports to DRI
NON_MAGNETIC = ["C", "VM", "ASH", "H2O_l", "CaCO3", "MgCO3", "CaO", "MgO", "S", "CaS"]


def _formula_vec(name: str) -> np.ndarray:
    v = np.zeros(len(ELEMENTS))
    for el, n in THERMO_DB[name].elements.items():
        v[EL[el]] = n
    return v


def oxide_mix_to_pseudo(wt_frac: dict) -> tuple[np.ndarray, CoeffArrays]:
    """Per-kg element vector (kmol/kg) and thermo coefficients for an oxide mix."""
    tot = sum(wt_frac.values())
    if tot <= 0:
        wt_frac, tot = {"SiO2": 1.0}, 1.0
    el = np.zeros(len(ELEMENTS))
    ents = []
    weights = []
    for ox, w in wt_frac.items():
        e = THERMO_DB[ox]
        if np.isfinite(e.t_break):
            raise InputValidationError(f"oxide {ox} with Cp break not allowed in lumped pseudo-species")
        n = (w / tot) / e.mw  # kmol oxide per kg
        el += n * _formula_vec(ox)
        ents.append(e)
        weights.append(n)
    arr = entry_arrays(ents)
    wv = np.array(weights)
    pseudo = CoeffArrays(
        names=["pseudo"], hf=np.array([wv @ arr.hf]), s298=np.array([wv @ arr.s298]),
        a1=np.array([wv @ arr.a1]), b1=np.array([wv @ arr.b1]), c1=np.array([wv @ arr.c1]),
        tb=np.array([np.inf]), a2=np.zeros(1), b2=np.zeros(1), c2=np.zeros(1))
    return el, pseudo


@dataclass
class CoalProps:
    """Coal on as-received basis with consistent proximate/ultimate closure."""
    fc: float  # kg/kg ar
    vm: float
    ash: float
    moisture: float
    C: float  # total C kg/kg ar (from daf ultimate)
    H: float
    O: float
    N: float
    S: float
    ncv_J_per_kg: float
    vm_carbon: float  # kg volatile carbon / kg ar
    vm_no_s: float  # VM mass excluding sulfur (kg/kg ar)
    warnings: list = field(default_factory=list)


def coal_from_assay(prox: dict, ult_daf: dict, ncv_MJ_kg_ar: float | None = None,
                    gcv_MJ_kg_ar: float | None = None, tol: float = 0.015) -> CoalProps:
    """Reconcile proximate (as-received %) and ultimate (daf %) analyses.

    Prevents double counting: moisture and ash are excluded from the daf
    ultimate analysis; organic H excludes moisture H.
    """
    fc, vm, ash, m = (prox[k] / 100.0 for k in ("fixed_carbon", "volatile_matter", "ash", "moisture"))
    s_prox = fc + vm + ash + m
    if abs(s_prox - 1.0) > tol:
        raise InputValidationError(f"coal proximate analysis sums to {100*s_prox:.2f} % (ar), expected 100 +/- {100*tol:.1f}")
    fc, vm, ash, m = (x / s_prox for x in (fc, vm, ash, m))
    u = {k: ult_daf[k] / 100.0 for k in ("C", "H", "O", "N", "S")}
    s_ult = sum(u.values())
    if abs(s_ult - 1.0) > tol:
        raise InputValidationError(f"coal ultimate analysis (daf) sums to {100*s_ult:.2f} %, expected 100")
    u = {k: v / s_ult for k, v in u.items()}
    daf = 1.0 - ash - m
    C, H, O, N, S = (u[k] * daf for k in ("C", "H", "O", "N", "S"))
    warnings = []
    if C < fc - 1e-9:
        raise InputValidationError(
            f"inconsistent coal bases: total carbon {100*C:.2f} % ar < fixed carbon {100*fc:.2f} % ar")
    vm_c = C - fc
    vm_no_s = vm - S
    closure = vm - (vm_c + H + O + N + S)
    if abs(closure) > tol:
        raise InputValidationError(f"VM closure error {100*closure:.2f} % between proximate and ultimate analyses")
    if ncv_MJ_kg_ar is None:
        if gcv_MJ_kg_ar is None:
            raise InputValidationError("coal requires NCV or GCV (as-received)")
        ncv_MJ_kg_ar = gcv_MJ_kg_ar - 2.442 * (9.0 * H + m)  # latent heat at 25 C, MJ/kg water
        warnings.append("NCV derived from GCV using 2.442 MJ/kg water latent heat")
    return CoalProps(fc, vm, ash, m, C, H, O, N, S, ncv_MJ_kg_ar * 1e6, vm_c, vm_no_s, warnings)


def vm_products(cp: CoalProps, f_o_to_co: float = 0.5, cp_vm: float = 1500.0):
    """Element-exact devolatilisation yields per kg VM (S excluded; S separate).

    Returns dict of gas kmol per kg VM plus soot carbon kmol per kg VM, and
    the VM formation enthalpy (J/kg) back-calculated from the coal NCV so the
    coal heating value is honoured exactly.
    """
    m_vm = cp.vm_no_s
    if m_vm <= 1e-9:
        return {g: 0.0 for g in GASES}, 0.0, 0.0, np.zeros(len(ELEMENTS))
    C = cp.vm_carbon / AW["C"] / m_vm
    H = cp.H / AW["H"] / m_vm
    O = cp.O / AW["O"] / m_vm
    N = cp.N / AW["N"] / m_vm
    y = {g: 0.0 for g in GASES}
    y["N2"] = N / 2.0
    n_co = min(f_o_to_co * O, C)
    o_rem = O - n_co
    n_h2o = min(o_rem, H / 2.0)
    o_rem -= n_h2o
    n_co2 = 0.0
    if o_rem > 1e-12:
        n_co2 = min(o_rem / 2.0, C - n_co)
        o_rem -= 2 * n_co2
    if o_rem > 1e-9:
        raise InputValidationError("coal VM oxygen cannot be closed with available C/H; check ultimate analysis")
    c_rem = C - n_co - n_co2
    h_rem = H - 2.0 * n_h2o
    n_ch4 = min(c_rem, h_rem / 4.0)
    c_rem -= n_ch4
    h_rem -= 4.0 * n_ch4
    y.update(CO=n_co, CO2=n_co2, H2O=n_h2o, CH4=n_ch4, H2=h_rem / 2.0)
    soot = c_rem
    el = np.zeros(len(ELEMENTS))
    el[EL["C"]], el[EL["H"]], el[EL["O"]], el[EL["N"]] = C, H, O, N
    # formation enthalpy of VM from NCV (products CO2, H2O(g), SO2, N2; ash inert)
    hf = {k: THERMO_DB[k].hf298 * 1000.0 for k in ("CO2", "H2O", "SO2", "H2O_l")}
    prod = (cp.C / AW["C"]) * hf["CO2"] + (cp.H / 2.0 / AW["H"] + cp.moisture / 18.015) * hf["H2O"] \
        + (cp.S / AW["S"]) * hf["SO2"]
    react_known = (cp.moisture / 18.015) * hf["H2O_l"]  # graphite C and S have Hf=0
    # NCV = -(H_products - H_reactants) per kg coal
    hf_vm_total = prod + cp.ncv_J_per_kg - react_known
    hf_vm = hf_vm_total / m_vm
    return y, soot, hf_vm, el


@dataclass
class MaterialSystem:
    """Species metadata for one plant/feed configuration."""
    mw_s: np.ndarray
    mw_g: np.ndarray
    el_s: np.ndarray  # (NS, NE) element kmol per species unit
    el_g: np.ndarray  # (NG, NE)
    th_s: CoeffArrays
    th_g: CoeffArrays
    vm_yield: dict
    vm_soot: float
    gangue_comp: dict
    ash_comp: dict
    coal: CoalProps
    cp_vm: float = 1500.0
    warnings: list = field(default_factory=list)
    f_o_to_co: float = 0.5

    def h_s(self, T):
        return self.th_s.h(T)

    def h_g(self, T):
        return self.th_g.h(T)

    def cp_s(self, T):
        return self.th_s.cp(T)

    def cp_g(self, T):
        return self.th_g.cp(T)

    def solids_mass(self, n):
        """n: (NS,) or (NS,N) -> kg."""
        return (self.mw_s[:, None] * n).sum(0) if np.ndim(n) == 2 else float(self.mw_s @ n)

    def elements_solids(self, n):
        return self.el_s.T @ n

    def elements_gas(self, f):
        return self.el_g.T @ f


def dulong_hhv_MJ_kg(cp: CoalProps) -> float:
    """Dulong estimate of HHV (as-received) - plausibility check only."""
    return 33.8 * cp.C + 144.2 * (cp.H - cp.O / 8.0) + 9.4 * cp.S


def devol_heat_J_per_kg(cp: CoalProps, f_o_to_co: float) -> float:
    """Heat of devolatilisation at 298 K (J/kg VM, + = endothermic)."""
    y, soot, hf_vm, _ = vm_products(cp, f_o_to_co)
    h = sum(y[g] * THERMO_DB[g].hf298 * 1000.0 for g in GASES)
    return h - hf_vm


def auto_vm_partition(cp: CoalProps, target_J_per_kg: float = 3.0e5) -> float:
    """Choose the O->CO split in [0,1] so devolatilisation heat is closest to a
    slightly endothermic target (documented assumption; real volatiles include
    tars and C2+ hydrocarbons not resolved here)."""
    best, best_err = 0.5, float("inf")
    for f in np.linspace(0.0, 1.0, 41):
        try:
            err = abs(devol_heat_J_per_kg(cp, f) - target_J_per_kg)
        except InputValidationError:
            continue
        if err < best_err:
            best, best_err = f, err
    return float(best)


def build_material_system(gangue_wt: dict, ash_wt: dict, coal: CoalProps,
                          f_o_to_co: float | None = None, cp_vm: float = 1500.0) -> MaterialSystem:
    ents_s, el_rows, mws = [], [], []
    g_el, g_th = oxide_mix_to_pseudo(gangue_wt)
    a_el, a_th = oxide_mix_to_pseudo(ash_wt)
    warn_extra = []
    hhv_d = dulong_hhv_MJ_kg(coal)
    ncv_d = hhv_d - 2.442 * (9 * coal.H + coal.moisture)
    dev = (coal.ncv_J_per_kg / 1e6 - ncv_d) / max(ncv_d, 1e-6)
    if abs(dev) > 0.07:
        warn_extra.append(f"coal NCV deviates {100*dev:+.1f} % from Dulong estimate ({ncv_d:.2f} MJ/kg) - check assay basis")
    if f_o_to_co is None:
        f_o_to_co = auto_vm_partition(coal)
    dh_dev = devol_heat_J_per_kg(coal, f_o_to_co)
    if abs(dh_dev) > 1.5e6:
        warn_extra.append(f"devolatilisation heat {dh_dev/1e6:+.2f} MJ/kg VM is implausible; NCV and ultimate "
                          "analysis are likely inconsistent")
    y, soot, hf_vm, vm_el = vm_products(coal, f_o_to_co, cp_vm)
    pseudo = {
        "GANGUE": (g_el, g_th),
        "ASH": (a_el, a_th),
        "VM": (vm_el, CoeffArrays(["VM"], np.array([hf_vm]), np.array([0.0]), np.array([cp_vm]),
                                  np.zeros(1), np.zeros(1), np.array([np.inf]), np.zeros(1), np.zeros(1), np.zeros(1))),
    }
    hf, s298, a1, b1, c1, tb, a2, b2, c2 = ([] for _ in range(9))
    for sp in SOLIDS:
        if sp in pseudo:
            el, th = pseudo[sp]
            mws.append(1.0)
        else:
            el = _formula_vec(sp)
            th = entry_arrays([THERMO_DB[sp]])
            mws.append(THERMO_DB[sp].mw)
        el_rows.append(el)
        for lst, arr in zip((hf, s298, a1, b1, c1, tb, a2, b2, c2),
                            (th.hf, th.s298, th.a1, th.b1, th.c1, th.tb, th.a2, th.b2, th.c2)):
            lst.append(arr[0])
        ents_s.append(sp)
    th_s = CoeffArrays(SOLIDS, *(np.array(x) for x in (hf, s298, a1, b1, c1, tb, a2, b2, c2)))
    th_g = entry_arrays([THERMO_DB[g] for g in GASES])
    el_g = np.array([_formula_vec(g) for g in GASES])
    # element-closure check of devolatilisation yields
    prod_el = sum(y[g] * el_g[GI[g]] for g in GASES) + soot * _formula_vec("C")
    if np.max(np.abs(prod_el - vm_el)) > 1e-9:
        raise InputValidationError("devolatilisation yield element closure failed")
    return MaterialSystem(
        mw_s=np.array(mws), mw_g=np.array([THERMO_DB[g].mw for g in GASES]),
        el_s=np.array(el_rows), el_g=el_g, th_s=th_s, th_g=th_g, vm_yield=y, vm_soot=soot,
        gangue_comp=gangue_wt, ash_comp=ash_wt, coal=coal, cp_vm=cp_vm, warnings=list(coal.warnings) + warn_extra, f_o_to_co=f_o_to_co)


def pellet_assay_to_species(assay: dict, tol_pct: float = 2.5) -> tuple[dict, dict, list]:
    """Pellet chemical assay (dry wt %) -> kg of each species per kg dry pellet.

    Required: Fe_total, FeO.  Optional: Fe_metal, Fe3O4 (if given, FeO is
    interpreted as free wustite), SiO2, Al2O3, CaO, MgO, TiO2, P, S, LOI.
    Remaining Fe is assigned to Fe2O3.  Closure must be within tol.
    """
    warn = []
    fe_t = assay["Fe_total"] / 100.0
    feo = assay.get("FeO", 0.0) / 100.0
    fe_m = assay.get("Fe_metal", 0.0) / 100.0
    fe3o4 = assay.get("Fe3O4", 0.0) / 100.0
    fe_in_feo = feo * AW["Fe"] / THERMO_DB["FeO"].mw
    fe_in_m = fe3o4 * 3 * AW["Fe"] / THERMO_DB["Fe3O4"].mw
    fe_hem = fe_t - fe_in_feo - fe_m - fe_in_m
    if fe_hem < -1e-6:
        raise InputValidationError("pellet assay: FeO/Fe3O4/metallic Fe exceed total Fe")
    fe2o3 = max(fe_hem, 0.0) * THERMO_DB["Fe2O3"].mw / (2 * AW["Fe"])
    gangue = {k: assay.get(k, 0.0) / 100.0 for k in ("SiO2", "Al2O3", "CaO", "MgO", "TiO2")}
    p2o5 = assay.get("P", 0.0) / 100.0 * THERMO_DB["P2O5"].mw / (2 * AW["P"])
    gangue["P2O5"] = p2o5
    s = assay.get("S", 0.0) / 100.0
    total = fe2o3 + fe3o4 + feo + fe_m + sum(gangue.values()) + s + assay.get("LOI", 0.0) / 100.0
    other = 1.0 - total
    if abs(other) * 100 > tol_pct:
        raise InputValidationError(f"pellet assay closure {100*total:.2f} % (tolerance +/-{tol_pct} %)")
    if other > 0:
        gangue["SiO2"] += other
        warn.append(f"pellet assay: {100*other:.2f} % unassigned mass lumped into SiO2-equivalent gangue")
    else:
        warn.append(f"pellet assay over-closes by {-100*other:.2f} %; gangue scaled")
        sc = max(0.0, 1 + other / max(sum(gangue.values()), 1e-9))
        gangue = {k: v * sc for k, v in gangue.items()}
    species = {"Fe2O3": fe2o3, "Fe3O4": fe3o4, "FeO": feo, "Fe": fe_m, "GANGUE": sum(gangue.values()), "FeS": 0.0}
    if s > 0:  # pellet sulfur carried as FeS; Fe drawn from hematite
        n_s = s / AW["S"]
        species["FeS"] = n_s * THERMO_DB["FeS"].mw
        species["Fe2O3"] = max(0.0, species["Fe2O3"] - n_s / 2 * THERMO_DB["Fe2O3"].mw)
    tot = sum(species.values())
    species = {k: v / tot for k, v in species.items()}  # exact 1 kg basis
    return species, gangue, warn
