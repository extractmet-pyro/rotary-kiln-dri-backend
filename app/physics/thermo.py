"""Temperature-dependent thermochemistry (self-contained offline fallback).

Heat capacity form (Maier-Kelley):  Cp(T) = a + b*T + c/T**2   [J/(mol K)]
with up to two temperature segments per species.  Enthalpy is absolute
(formation enthalpy at 298.15 K + sensible integral), so reaction heats follow
automatically from species enthalpies and are never added a second time.

Data provenance (see docs/MODEL_EQUATIONS.md, Table T1):
  * dHf(298) and S(298): NIST-JANAF / NIST Chemistry WebBook standard values.
  * Cp coefficients: Maier-Kelley fits as tabulated in standard metallurgical
    thermochemistry compilations (Kubaschewski, Alcock & Spencer, "Materials
    Thermochemistry", 6th ed., Pergamon 1993).  Coefficients were entered by
    the developer and are checked in tests/physics/test_thermo.py against the
    NIST Cp(298) values to within 6 %.  They MUST be re-verified against the
    licensed primary source before site calibration.
  * Validity range: 298-1600 K.  Outside this range values are extrapolated
    and a warning flag is raised by `check_range`.
  * Simplifications: wustite is represented by stoichiometric FeO (Fe(1-x)O
    non-stoichiometry ignored in the mass balance); SiO2 alpha/beta and the Fe
    alpha/gamma transitions (<1 kJ/mol) are smoothed into the Cp fit.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.core.units import R_J_PER_MOL_K, T_REF

T_MIN_VALID = 250.0
T_MAX_VALID = 1600.0


@dataclass(frozen=True)
class ThermoEntry:
    name: str
    phase: str  # 's', 'l', 'g'
    mw: float  # kg/kmol
    elements: dict
    hf298: float  # J/mol
    s298: float  # J/(mol K)
    seg1: tuple  # (a, b, c)
    t_break: float = float("inf")
    seg2: tuple = (0.0, 0.0, 0.0)
    source: str = "NIST-JANAF (Hf,S); Kubaschewski-Alcock-Spencer 1993 (Cp)"


# fmt: off
THERMO_DB: dict[str, ThermoEntry] = {
    # ---- gases ----
    "CO":   ThermoEntry("CO", "g", 28.010, {"C": 1, "O": 1}, -110530.0, 197.66, (28.41, 4.10e-3, -0.46e5)),
    "CO2":  ThermoEntry("CO2", "g", 44.010, {"C": 1, "O": 2}, -393510.0, 213.79, (44.14, 9.04e-3, -8.54e5)),
    "H2":   ThermoEntry("H2", "g", 2.016, {"H": 2}, 0.0, 130.68, (27.28, 3.26e-3, 0.50e5)),
    "H2O":  ThermoEntry("H2O", "g", 18.015, {"H": 2, "O": 1}, -241826.0, 188.84, (30.00, 10.71e-3, 0.33e5)),
    "O2":   ThermoEntry("O2", "g", 31.999, {"O": 2}, 0.0, 205.15, (29.96, 4.18e-3, -1.67e5)),
    "N2":   ThermoEntry("N2", "g", 28.013, {"N": 2}, 0.0, 191.61, (27.87, 4.27e-3, 0.0)),
    "CH4":  ThermoEntry("CH4", "g", 16.043, {"C": 1, "H": 4}, -74873.0, 186.25, (23.64, 47.86e-3, -1.92e5)),
    "H2S":  ThermoEntry("H2S", "g", 34.081, {"H": 2, "S": 1}, -20600.0, 205.81, (29.37, 15.40e-3, 0.0)),
    "SO2":  ThermoEntry("SO2", "g", 64.066, {"S": 1, "O": 2}, -296840.0, 248.22, (43.43, 10.63e-3, -5.94e5)),
    # ---- condensed ----
    "Fe2O3": ThermoEntry("Fe2O3", "s", 159.688, {"Fe": 2, "O": 3}, -824200.0, 87.40, (98.28, 77.82e-3, -14.85e5)),
    "Fe3O4": ThermoEntry("Fe3O4", "s", 231.533, {"Fe": 3, "O": 4}, -1118400.0, 146.40, (91.55, 201.67e-3, 0.0), 900.0, (200.83, 0.0, 0.0)),
    "FeO":   ThermoEntry("FeO", "s", 71.844, {"Fe": 1, "O": 1}, -272000.0, 57.49, (50.80, 8.61e-3, -3.31e5)),
    "Fe":    ThermoEntry("Fe", "s", 55.845, {"Fe": 1}, 0.0, 27.28, (17.49, 24.77e-3, 0.0)),
    "C":     ThermoEntry("C", "s", 12.011, {"C": 1}, 0.0, 5.74, (17.15, 4.27e-3, -8.79e5)),
    "H2O_l": ThermoEntry("H2O_l", "l", 18.015, {"H": 2, "O": 1}, -285830.0, 69.95, (75.30, 0.0, 0.0)),
    "CaCO3": ThermoEntry("CaCO3", "s", 100.087, {"Ca": 1, "C": 1, "O": 3}, -1207600.0, 91.70, (104.52, 21.92e-3, -25.94e5)),
    "MgCO3": ThermoEntry("MgCO3", "s", 84.314, {"Mg": 1, "C": 1, "O": 3}, -1113300.0, 65.70, (77.91, 57.74e-3, -17.41e5)),
    "CaO":   ThermoEntry("CaO", "s", 56.077, {"Ca": 1, "O": 1}, -635090.0, 38.10, (49.62, 4.52e-3, -6.95e5)),
    "MgO":   ThermoEntry("MgO", "s", 40.304, {"Mg": 1, "O": 1}, -601600.0, 26.95, (42.59, 7.28e-3, -6.19e5)),
    "S":     ThermoEntry("S", "s", 32.06, {"S": 1}, 0.0, 32.07, (14.98, 26.11e-3, 0.0)),
    "FeS":   ThermoEntry("FeS", "s", 87.91, {"Fe": 1, "S": 1}, -100000.0, 60.29, (51.0, 9.9e-3, 0.0)),
    "CaS":   ThermoEntry("CaS", "s", 72.14, {"Ca": 1, "S": 1}, -473200.0, 56.5, (42.68, 15.9e-3, 0.0)),
    # oxide components used to build lumped gangue/ash pseudo-species
    "SiO2":  ThermoEntry("SiO2", "s", 60.084, {"Si": 1, "O": 2}, -910700.0, 41.46, (46.94, 34.31e-3, -11.30e5)),
    "Al2O3": ThermoEntry("Al2O3", "s", 101.961, {"Al": 2, "O": 3}, -1675700.0, 50.92, (117.49, 10.38e-3, -37.11e5)),
    "TiO2":  ThermoEntry("TiO2", "s", 79.866, {"Ti": 1, "O": 2}, -944000.0, 50.62, (75.19, 1.17e-3, -18.2e5)),
    "P2O5":  ThermoEntry("P2O5", "s", 141.945, {"P": 2, "O": 5}, -1492000.0, 114.4, (106.0, 0.0, 0.0),
                         source="P4O10/2 (NIST); Cp approximate constant - trace species"),
}
# fmt: on

NIST_CP298 = {  # J/(mol K), NIST WebBook, used only for verification tests
    "CO": 29.14, "CO2": 37.13, "H2": 28.84, "H2O": 33.58, "O2": 29.38, "N2": 29.12,
    "CH4": 35.69, "Fe2O3": 103.9, "Fe3O4": 143.4, "FeO": 49.9, "Fe": 25.1, "C": 8.52,
    "CaCO3": 83.5, "CaO": 42.0, "MgO": 37.2, "SiO2": 44.4, "Al2O3": 79.0, "TiO2": 55.0,
    "SO2": 39.9, "H2S": 34.2, "MgCO3": 75.5,
}


def _seg_h(a, b, c, t1, t2):
    return a * (t2 - t1) + 0.5 * b * (t2 * t2 - t1 * t1) + c * (1.0 / t1 - 1.0 / t2)


def _seg_s(a, b, c, t1, t2):
    return a * np.log(t2 / t1) + b * (t2 - t1) - 0.5 * c * (1.0 / (t2 * t2) - 1.0 / (t1 * t1))


@dataclass
class CoeffArrays:
    """Vectorised coefficient arrays for a species list (per kmol, SI)."""

    names: list
    hf: np.ndarray  # J/kmol
    s298: np.ndarray  # J/(kmol K)
    a1: np.ndarray
    b1: np.ndarray
    c1: np.ndarray
    tb: np.ndarray
    a2: np.ndarray
    b2: np.ndarray
    c2: np.ndarray
    extra: dict = field(default_factory=dict)

    def h(self, T):
        """Absolute enthalpy J/kmol; T scalar or array (N,) -> (S,) or (S,N)."""
        T = np.asarray(T, dtype=float)
        Tc = T[None, ...] if T.ndim else T
        sh = (slice(None),) + (None,) * T.ndim
        a1, b1, c1, tb = self.a1[sh], self.b1[sh], self.c1[sh], self.tb[sh]
        a2, b2, c2 = self.a2[sh], self.b2[sh], self.c2[sh]
        t_low = np.minimum(Tc, tb)
        hv = self.hf[sh] + _seg_h(a1, b1, c1, T_REF, t_low)
        tbf = np.where(np.isfinite(tb), tb, T_REF)
        t_high = np.where(np.isfinite(tb), np.maximum(Tc, tbf), tbf)
        hv = hv + np.where(np.isfinite(tb), _seg_h(a2, b2, c2, tbf, t_high), 0.0)
        return hv

    def cp(self, T):
        T = np.asarray(T, dtype=float)
        sh = (slice(None),) + (None,) * T.ndim
        Tc = T[None, ...] if T.ndim else T
        lo = self.a1[sh] + self.b1[sh] * Tc + self.c1[sh] / (Tc * Tc)
        hi = self.a2[sh] + self.b2[sh] * Tc + self.c2[sh] / (Tc * Tc)
        return np.where(Tc <= self.tb[sh], lo, hi)

    def s(self, T):
        T = np.asarray(T, dtype=float)
        sh = (slice(None),) + (None,) * T.ndim
        Tc = T[None, ...] if T.ndim else T
        a1, b1, c1, tb = self.a1[sh], self.b1[sh], self.c1[sh], self.tb[sh]
        t_low = np.minimum(Tc, tb)
        sv = self.s298[sh] + _seg_s(a1, b1, c1, T_REF, t_low)
        tbf = np.where(np.isfinite(tb), tb, T_REF)
        t_high = np.where(np.isfinite(tb), np.maximum(Tc, tbf), tbf)
        sv = sv + np.where(np.isfinite(tb), _seg_s(self.a2[sh], self.b2[sh], self.c2[sh], tbf, t_high), 0.0)
        return sv


def entry_arrays(entries: list[ThermoEntry]) -> CoeffArrays:
    k = 1000.0  # J/mol -> J/kmol
    return CoeffArrays(
        names=[e.name for e in entries],
        hf=np.array([e.hf298 * k for e in entries]),
        s298=np.array([e.s298 * k for e in entries]),
        a1=np.array([e.seg1[0] * k for e in entries]),
        b1=np.array([e.seg1[1] * k for e in entries]),
        c1=np.array([e.seg1[2] * k for e in entries]),
        tb=np.array([e.t_break for e in entries]),
        a2=np.array([e.seg2[0] * k for e in entries]),
        b2=np.array([e.seg2[1] * k for e in entries]),
        c2=np.array([e.seg2[2] * k for e in entries]),
    )


def species_h(name: str, T) -> np.ndarray:
    return entry_arrays([THERMO_DB[name]]).h(T)[0]


def species_g(name: str, T) -> np.ndarray:
    arr = entry_arrays([THERMO_DB[name]])
    return arr.h(T)[0] - np.asarray(T) * arr.s(T)[0]


def delta_g(stoich: dict, T) -> np.ndarray:
    """Standard Gibbs energy change J/kmol-of-extent for {species: nu}."""
    return sum(nu * species_g(sp, T) for sp, nu in stoich.items())


def delta_h(stoich: dict, T) -> np.ndarray:
    return sum(nu * species_h(sp, T) for sp, nu in stoich.items())


def equilibrium_K(stoich: dict, T) -> np.ndarray:
    """Equilibrium constant (activities of pure condensed phases = 1, gases in atm)."""
    return np.exp(-delta_g(stoich, T) / (R_J_PER_MOL_K * 1000.0 * np.asarray(T)))


def check_range(T) -> list[str]:
    T = np.atleast_1d(T)
    w = []
    if np.any(T < T_MIN_VALID):
        w.append(f"thermo: T below validated range ({T.min():.0f} K < {T_MIN_VALID} K) - extrapolated")
    if np.any(T > T_MAX_VALID):
        w.append(f"thermo: T above validated range ({T.max():.0f} K > {T_MAX_VALID} K) - extrapolated")
    return w


class FastK:
    """Pre-combined equilibrium constant for single-segment species (hot path).
    Mathematically identical to equilibrium_K (verified in tests)."""

    def __init__(self, stoich: dict):
        ents = [THERMO_DB[k] for k in stoich]
        if any(np.isfinite(e.t_break) for e in ents):
            raise ValueError("FastK supports single-segment species only")
        nu = np.array(list(stoich.values()), dtype=float)
        k = 1000.0
        self.dhf = float(nu @ np.array([e.hf298 for e in ents])) * k
        self.ds = float(nu @ np.array([e.s298 for e in ents])) * k
        self.da = float(nu @ np.array([e.seg1[0] for e in ents])) * k
        self.db = float(nu @ np.array([e.seg1[1] for e in ents])) * k
        self.dc = float(nu @ np.array([e.seg1[2] for e in ents])) * k

    def __call__(self, T):
        T = np.asarray(T, dtype=float)
        dh = self.dhf + _seg_h(self.da, self.db, self.dc, T_REF, T)
        ds = self.ds + _seg_s(self.da, self.db, self.dc, T_REF, T)
        return np.exp(-(dh - T * ds) / (R_J_PER_MOL_K * 1000.0 * T))


K_BOUDOUARD = FastK({"C": -1, "CO2": -1, "CO": 2})
K_STEAM = FastK({"C": -1, "H2O": -1, "CO": 1, "H2": 1})
K_WGS = FastK({"CO": -1, "H2O": -1, "CO2": 1, "H2": 1})
K_CALC_CA = FastK({"CaCO3": -1, "CaO": 1, "CO2": 1})
K_CALC_MG = FastK({"MgCO3": -1, "MgO": 1, "CO2": 1})
