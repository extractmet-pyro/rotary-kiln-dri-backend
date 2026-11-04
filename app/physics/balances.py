"""Conservation audits and the energy ledger.

Energy ledger convention (LHV-type, reference = fully oxidised elements at
298.15 K: C->CO2, H->H2O(g), S->SO2, Fe->Fe2O3, Ca->CaO, Mg->MgO, Si->SiO2,
Al->Al2O3, Ti->TiO2, P->P2O5, N->N2, O->O2).  For every stream:

    E_chem = sum n_i [h_i(298) - h_ref,i]      (chemical energy vs. oxidised state)
    E_sens = sum n_i [h_i(T)   - h_i(298)]     (sensible enthalpy)

Because every non-oxygen element is conserved and O2 has zero formation
enthalpy, sum_in(E_chem+E_sens) - sum_out(E_chem+E_sens) - Q_loss - dH_store
equals the exact absolute-enthalpy residual.  Ledger categories therefore close
without any normalisation; the residual is displayed, never forced to zero.
"""
from __future__ import annotations

import numpy as np

from app.physics.species import EL, ELEMENTS, GASES, NS, SOLIDS
from app.physics.thermo import THERMO_DB

T298 = 298.15

_REF = {  # (reference oxide, atoms of element per formula unit)
    "Fe": ("Fe2O3", 2), "C": ("CO2", 1), "H": ("H2O", 2), "S": ("SO2", 1), "Ca": ("CaO", 1), "Mg": ("MgO", 1),
    "Si": ("SiO2", 1), "Al": ("Al2O3", 2), "Ti": ("TiO2", 1), "P": ("P2O5", 2),
}


def element_reference_enthalpy() -> np.ndarray:
    """J per kmol of element in its oxidised reference state."""
    href = np.zeros(len(ELEMENTS))
    for el, (ox, k) in _REF.items():
        href[EL[el]] = THERMO_DB[ox].hf298 * 1000.0 / k
    return href


class EnergyAccountant:
    def __init__(self, ms):
        self.ms = ms
        href = element_reference_enthalpy()
        self.chem_s = ms.h_s(T298) - ms.el_s @ href  # J per unit (kmol or kg for pseudo)
        self.chem_g = ms.h_g(T298) - ms.el_g @ href
        self.chem_s[[SOLIDS.index(k) for k in ("GANGUE", "ASH")]] = 0.0  # oxide mixtures by definition

    def solids(self, n, T):
        """(chemical, sensible) J for solids amounts n (NS,) at T."""
        h = self.ms.h_s(T)
        return float(self.chem_s @ n), float((h - self.ms.h_s(T298)) @ n)

    def gas(self, f, T):
        h = self.ms.h_g(T)
        return float(self.chem_g @ f), float((h - self.ms.h_g(T298)) @ f)


def element_audit(logs, ms, window: int | None = None) -> dict:
    """Integrated element, mass and enthalpy balances over the logged steps."""
    if not logs:
        return {"available": False}
    L = logs[-window:] if window else logs
    e_in = sum(lg.el_in for lg in L)
    e_out = sum(lg.el_out for lg in L)
    e_acc = sum(lg.el_accum for lg in L)
    m_in = sum(lg.mass_in for lg in L)
    m_out = sum(lg.mass_out for lg in L)
    m_acc = sum(lg.accum for lg in L)
    H_in = sum(lg.H_in for lg in L)
    H_out = sum(lg.H_out for lg in L)
    Q_l = sum(lg.Q_loss for lg in L)
    H_acc = sum(lg.H_accum for lg in L)
    rows = []
    aw = {e: w for e, w in zip(ELEMENTS, [55.845, 15.999, 12.011, 1.008, 14.007, 32.06, 40.078, 24.305, 28.085,
                                          26.982, 47.867, 30.974])}
    for i, e in enumerate(ELEMENTS):
        res = e_in[i] - e_out[i] - e_acc[i]
        rows.append({"element": e, "in_kg": float(e_in[i] * aw[e]), "out_kg": float(e_out[i] * aw[e]),
                     "accumulation_kg": float(e_acc[i] * aw[e]), "residual_kg": float(res * aw[e]),
                     "relative_residual": float(abs(res) / max(e_in[i], 1e-12)) if e_in[i] > 0 else 0.0})
    span = L[-1].t - (L[0].t - (L[1].t - L[0].t if len(L) > 1 else 0))
    # The energy denominator is the gross enthalpy throughput |H_in| + |H_out|.
    return {
        "available": True,
        "steps": len(L),
        "elements": rows,
        "mass": {"in_kg": m_in, "out_kg": m_out, "accumulation_kg": m_acc, "residual_kg": m_in - m_out - m_acc,
                 "relative_residual": abs(m_in - m_out - m_acc) / max(m_in, 1e-12)},
        "energy": {"in_J": H_in, "out_J": H_out, "shell_loss_J": Q_l, "accumulation_J": H_acc,
                   "residual_J": H_in - H_out - Q_l - H_acc,
                   "relative_residual": abs(H_in - H_out - Q_l - H_acc) / max(abs(H_in) + abs(H_out), 1e-12)},
        "logged_steps_note": "audit integrates the per-step logs (every logged solver step)",
        "span_note": float(span),
    }


def reaction_heat_summary(model, R, fbR) -> list:
    """Integrated reaction extents (kmol/h) and heat at 298 K (kW, + = endothermic)."""
    rs = model.rxn
    tot = R.sum(1) + fbR.sum(1)
    out = []
    for k, name in enumerate(rs.names):
        out.append({"reaction": name, "equation": rs.equations[k], "location": rs.location[k],
                    "extent_kmol_h": float(tot[k] * 3600), "heat_kW": float(tot[k] * rs.dh298[k] / 1e3)})
    return out


__all__ = ["EnergyAccountant", "element_audit", "reaction_heat_summary", "GASES", "NS"]
