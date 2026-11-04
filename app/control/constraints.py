"""MPC variable definitions, bounds, ramp limits and soft-constraint policy.

All numeric limits here are DEMO placeholders derived from the plant
configuration; site alarm/trip limits are external, authoritative and immutable
to the optimiser.  Hard constraints = actuator bounds and ramp rates (never
relaxed).  Process constraints (bed/shell/exit-gas temperature envelopes,
minimum metallization) are soft with large slack penalties ranked above any
economic term.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class MVSpec:
    name: str
    unit: str
    lo: float
    hi: float
    ramp_per_interval: float
    commandable: bool = True
    locked: bool = False


@dataclass
class ProcessLimits:
    met_min: float
    met_target: float
    bed_T_max: float
    shell_T_max: float
    exit_T_min: float
    exit_T_max: float
    accretion_max: float = 0.6


@dataclass
class MPCSettings:
    interval_min: float = 30.0
    Np: int = 16  # prediction steps (8 h at 30 min) - covers solids transport
    Nc: int = 4
    weights: dict = field(default_factory=dict)
    scenario: str = "multiobjective"


SCENARIO_WEIGHTS = {
    # dimensionless weights on normalised terms (see MPC_SPECIFICATION.md)
    "maximize_metallization": {"met": 6.0, "temp": 0.5, "coal": 0.2, "energy": 0.1, "co2": 0.0, "risk": 1.0, "move": 1.5,
                               "throughput": 0.0},
    "minimize_specific_coal": {"met": 2.0, "temp": 0.5, "coal": 4.0, "energy": 1.0, "co2": 0.5, "risk": 1.0, "move": 1.5,
                               "throughput": 0.5},
    "maximize_throughput": {"met": 2.0, "temp": 0.5, "coal": 0.5, "energy": 0.3, "co2": 0.0, "risk": 1.0, "move": 1.5,
                            "throughput": 4.0},
    "minimize_thermal_risk": {"met": 1.5, "temp": 4.0, "coal": 0.3, "energy": 0.2, "co2": 0.0, "risk": 5.0, "move": 1.5,
                              "throughput": 0.0},
    "multiobjective": {"met": 3.0, "temp": 1.0, "coal": 1.5, "energy": 0.5, "co2": 0.3, "risk": 2.0, "move": 1.5,
                       "throughput": 1.0},
}
SOFT_PENALTY = 1.0e3


def default_mvs(cfg, base_u: np.ndarray) -> list[MVSpec]:
    g = cfg.geometry
    p0, c0, i0, a0, r0 = base_u[:5]
    return [
        MVSpec("pellet_tph", "t/h", 0.85 * p0, 1.12 * p0, 0.03 * p0),
        MVSpec("feed_coal_tph", "t/h", 0.85 * c0, 1.12 * c0, 0.03 * c0),
        MVSpec("injection_coal_tph", "t/h", 0.75 * i0, 1.25 * i0, 0.05 * i0),
        MVSpec("secondary_air_scale", "-", 0.90, 1.10, 0.02),
        MVSpec("rpm", "rev/min", max(g.rpm_min, 0.88 * r0), min(g.rpm_max, 1.12 * r0), 0.02),
    ]


def limits_from_config(cfg) -> ProcessLimits:
    L = cfg.limits
    return ProcessLimits(met_min=L.min_metallization_pct, met_target=L.target_metallization_pct,
                         bed_T_max=L.max_bed_temperature_C, shell_T_max=L.max_shell_temperature_C,
                         exit_T_min=L.min_exit_gas_temperature_C, exit_T_max=L.max_exit_gas_temperature_C)
