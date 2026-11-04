"""Independent reaction set, stoichiometric matrix and reaction enthalpies.

Species vector ordering is [SOLIDS..., GASES...] (see species.py).  Extents are
kmol/s of reaction (DEVOL: kg VM/s).  Rate laws live in kinetics.py.  Each row
is atom-balanced (verified in tests/physics/test_reactions.py).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.physics.species import GASES, GI, NG, NS, SI, MaterialSystem

REACTIONS = [
    ("R01_HEM_CO", "3 Fe2O3 + CO -> 2 Fe3O4 + CO2", "bed", {"Fe2O3": -3, "CO": -1, "Fe3O4": 2, "CO2": 1}),
    ("R02_MAG_CO", "Fe3O4 + CO -> 3 FeO + CO2", "bed", {"Fe3O4": -1, "CO": -1, "FeO": 3, "CO2": 1}),
    ("R03_WUS_CO", "FeO + CO <-> Fe + CO2", "bed", {"FeO": -1, "CO": -1, "Fe": 1, "CO2": 1}),
    ("R04_HEM_H2", "3 Fe2O3 + H2 -> 2 Fe3O4 + H2O", "bed", {"Fe2O3": -3, "H2": -1, "Fe3O4": 2, "H2O": 1}),
    ("R05_MAG_H2", "Fe3O4 + H2 -> 3 FeO + H2O", "bed", {"Fe3O4": -1, "H2": -1, "FeO": 3, "H2O": 1}),
    ("R06_WUS_H2", "FeO + H2 <-> Fe + H2O", "bed", {"FeO": -1, "H2": -1, "Fe": 1, "H2O": 1}),
    ("R07_BOUDOUARD", "C + CO2 <-> 2 CO", "bed", {"C": -1, "CO2": -1, "CO": 2}),
    ("R08_STEAM_GASIF", "C + H2O <-> CO + H2", "bed", {"C": -1, "H2O": -1, "CO": 1, "H2": 1}),
    ("R09_WGS", "CO + H2O <-> CO2 + H2", "freeboard", {"CO": -1, "H2O": -1, "CO2": 1, "H2": 1}),
    ("R10_C_O2_CO2", "C + O2 -> CO2", "bed-surface", {"C": -1, "O2": -1, "CO2": 1}),
    ("R11_C_O2_CO", "2 C + O2 -> 2 CO", "bed-surface", {"C": -2, "O2": -1, "CO": 2}),
    ("R12_CO_OX", "CO + 0.5 O2 -> CO2", "freeboard", {"CO": -1, "O2": -0.5, "CO2": 1}),
    ("R13_H2_OX", "H2 + 0.5 O2 -> H2O", "freeboard", {"H2": -1, "O2": -0.5, "H2O": 1}),
    ("R14_CH4_OX", "CH4 + 2 O2 -> CO2 + 2 H2O", "freeboard", {"CH4": -1, "O2": -2, "CO2": 1, "H2O": 2}),
    ("R15_EVAP", "H2O(l) -> H2O(g)", "bed", {"H2O_l": -1, "H2O": 1}),
    ("R16_DEVOL", "VM (1 kg) -> CO, CO2, H2, H2O, CH4, N2 + soot C", "bed", None),
    ("R17_CALC_CA", "CaCO3 -> CaO + CO2", "bed", {"CaCO3": -1, "CaO": 1, "CO2": 1}),
    ("R18_CALC_MG", "MgCO3 -> MgO + CO2", "bed", {"MgCO3": -1, "MgO": 1, "CO2": 1}),
    ("R19_S_RELEASE", "S(coal) + H2 -> H2S", "bed", {"S": -1, "H2": -1, "H2S": 1}),
    ("R20_CAS_CAPTURE", "CaO + H2S -> CaS + H2O", "bed", {"CaO": -1, "H2S": -1, "CaS": 1, "H2O": 1}),
    ("R21_FES_PICKUP", "Fe + H2S -> FeS + H2", "bed", {"Fe": -1, "H2S": -1, "FeS": 1, "H2": 1}),
    ("R22_H2S_OX", "H2S + 1.5 O2 -> SO2 + H2O", "freeboard", {"H2S": -1, "O2": -1.5, "SO2": 1, "H2O": 1}),
    ("R23_REOX", "2 Fe + O2 -> 2 FeO", "bed-surface", {"Fe": -2, "O2": -1, "FeO": 2}),
]
RID = {r[0]: i for i, r in enumerate(REACTIONS)}
NR = len(REACTIONS)
REDUCTION_IDS = [RID[k] for k in ("R01_HEM_CO", "R02_MAG_CO", "R03_WUS_CO", "R04_HEM_H2", "R05_MAG_H2", "R06_WUS_H2")]


def _col(sp: str) -> int:
    return SI[sp] if sp in SI else NS + GI[sp]


@dataclass
class ReactionSystem:
    nu: np.ndarray  # (NR, NS+NG)
    dh298: np.ndarray  # J per unit extent at 298 K
    names: list
    equations: list
    location: list

    @property
    def nu_s(self):
        return self.nu[:, :NS]

    @property
    def nu_g(self):
        return self.nu[:, NS:]

    def element_residual(self, ms: MaterialSystem) -> np.ndarray:
        el = np.vstack([ms.el_s, ms.el_g])
        return self.nu @ el  # (NR, NE) must be ~0


def build_reaction_system(ms: MaterialSystem) -> ReactionSystem:
    nu = np.zeros((NR, NS + NG))
    for i, (_rid, _eq, _loc, st) in enumerate(REACTIONS):
        if st is None:  # devolatilisation, coal specific
            nu[i, SI["VM"]] = -1.0
            for g in GASES:
                nu[i, NS + GI[g]] = ms.vm_yield[g]
            nu[i, SI["C"]] = ms.vm_soot
        else:
            for sp, v in st.items():
                nu[i, _col(sp)] = v
    h298 = np.concatenate([ms.h_s(298.15), ms.h_g(298.15)])
    dh = nu @ h298
    return ReactionSystem(nu, dh, [r[0] for r in REACTIONS], [r[1] for r in REACTIONS], [r[2] for r in REACTIONS])
