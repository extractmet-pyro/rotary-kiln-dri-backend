"""Coupled quasi-1D finite-volume rotary-kiln model (counter-current).

Topology (z = 0 feed end, z = L discharge end, solids move +z, gas moves -z):

  cell j : solids bed (transient species kmol + enthalpy J)
           freeboard gas (quasi-steady; residence ~ seconds << solids hours)
           wall: refractory layers + steel shell (transient radial conduction)

Per time step (operator split, all fluxes conservative):
  1. Bed temperature from enthalpy inversion  H_s = sum n_i h_i(T_s).
  2. Bed chemistry: interstitial CO/CO2 pool fraction X solved per cell by
     bisection so that CO2 produced by pellet reduction balances Boudouard
     consumption plus out-gassing; three-interface pellet kinetics; char
     gasification; drying; devolatilisation; calcination; S reactions;
     O2 attack on bed surface (char burn-off / re-oxidation).  A positivity
     limiter scales reaction extents (stoichiometry preserved).
  3. Wall: implicit radial conduction with linearised exchange to gas/bed and
     shell -> ambient.
  4. Freeboard gas marched from z = L to z = 0 (counter-current boundary at the
     discharge end): air sources, bed release, mixing-limited combustion,
     water-gas-shift relaxation; Newton solution of the gas energy balance
     with implicit gas-bed and gas-wall exchange.  Wall receives the exact
     gas-side flux (difference posted to the hot-face node) -> exact energy
     bookkeeping.
  5. Solids upwind advection with velocity from the Kramers-Croockewit bed
     profile; species/enthalpy update; dust entrainment.
Every step logs inflow/outflow/accumulation of mass, elements and enthalpy.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from app.core.exceptions import InputValidationError
from app.core.units import NTP, P_ATM, R_J_PER_KMOL_K, SIGMA, C_to_K, nm3h_to_kmolps, tph_to_kgps
from app.physics import bed_transport as bt
from app.physics import heat_transfer as ht
from app.physics import kinetics as kn
from app.physics.properties import bed_effective_conductivity, gas_conductivity, gas_viscosity
from app.physics.reactions import NR, RID, build_reaction_system
from app.physics.species import (
    AW,
    ELEMENTS,
    GASES,
    GI,
    NG,
    NS,
    SI,
    SOLIDS,
    CoalProps,
    build_material_system,
    coal_from_assay,
    pellet_assay_to_species,
)
from app.physics.thermo import K_BOUDOUARD, K_WGS, THERMO_DB
from app.schemas.plant import PlantConfig

T298 = 298.15


def _blend_coal(c1: CoalProps, w1: float, c2: CoalProps, w2: float) -> CoalProps:
    tot = w1 + w2
    if tot <= 0:
        return c1
    a, b = w1 / tot, w2 / tot
    f = {k: a * getattr(c1, k) + b * getattr(c2, k) for k in
         ("fc", "vm", "ash", "moisture", "C", "H", "O", "N", "S", "ncv_J_per_kg", "vm_carbon", "vm_no_s")}
    return CoalProps(**f, warnings=list(set(c1.warnings + c2.warnings)))


def _coal(ca) -> CoalProps:
    return coal_from_assay(ca.proximate_ar_wt_pct, ca.ultimate_daf_wt_pct, ca.ncv_MJ_kg_ar, ca.gcv_MJ_kg_ar)


def _ash_map(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        base = k.replace("_ash", "")
        if base not in THERMO_DB:
            base = "SiO2"
        out[base] = out.get(base, 0.0) + v
    return out


@dataclass
class StepLog:
    t: float
    mass_in: float
    mass_out: float
    accum: float
    el_in: np.ndarray
    el_out: np.ndarray
    el_accum: np.ndarray
    H_in: float
    H_out: float
    Q_loss: float
    H_accum: float


@dataclass
class KilnState:
    n: np.ndarray  # (NS, N) kmol
    Hs: np.ndarray  # (N,) J
    Ts: np.ndarray  # (N,) K
    Tw: np.ndarray  # (N, M) K
    Tg: np.ndarray  # (N,) K
    F: np.ndarray  # (NG, N) gas outflow from cell j toward j-1, kmol/s
    X: np.ndarray  # (N,) bed CO/(CO+CO2)
    yH: np.ndarray  # (N,) H-pair fraction of bed gas
    t: float = 0.0


@dataclass
class StepDiagnostics:
    rates: np.ndarray = None  # (NR, N) kmol/s
    fb_rates: np.ndarray = None  # freeboard extents (NR, N)
    Q_gs: np.ndarray = None
    Q_gw: np.ndarray = None
    Q_cw: np.ndarray = None
    Q_wb: np.ndarray = None
    Q_shell: np.ndarray = None
    T_face_in: np.ndarray = None
    T_shell: np.ndarray = None
    eps_g: np.ndarray = None
    h_gs: np.ndarray = None
    h_gw: np.ndarray = None
    h_cw: np.ndarray = None
    u_g: np.ndarray = None
    dust: np.ndarray = None
    limiter_active: int = 0
    gas_newton_max_iter: int = 0
    gas_clip: float = 0.0
    warnings: list = field(default_factory=list)


class KilnModel:
    def __init__(self, cfg: PlantConfig):
        self.cfg = cfg
        g, lin = cfg.geometry, cfg.lining
        self.N = cfg.numerics.n_cells
        self.L = g.length_m
        self.z_edges = np.linspace(0.0, self.L, self.N + 1)
        self.zc = 0.5 * (self.z_edges[1:] + self.z_edges[:-1])
        self.dz = self.L / self.N
        t_lin = sum(layer.thickness_m * ((1 - lin.wear_fraction) if i == 0 else 1.0)
                    for i, layer in enumerate(lin.layers))
        self.R_shell_out = g.shell_diameter_m / 2.0
        r_wall_in = self.R_shell_out - lin.shell_thickness_m - t_lin
        self.R = r_wall_in - g.accretion_thickness_m  # effective free radius
        if self.R < 0.3:
            raise InputValidationError("effective internal radius < 0.3 m")
        self.wall = ht.WallModel(r_wall_in, lin.layers, lin.shell_thickness_m, lin.shell_k_W_mK,
                                 lin.shell_rho_kg_m3, lin.shell_cp_J_kgK, lin.wear_fraction)
        self.M = self.wall.M
        self._build_materials()
        self.rxn = build_reaction_system(self.ms)
        self.nu_s = self.rxn.nu_s.T.copy()  # (NS, NR)
        self.nu_g = self.rxn.nu_g.T.copy()  # (NG, NR)
        th = self.ms.th_g
        self._g_hf, self._g_a, self._g_b, self._g_c = th.hf, th.a1, th.b1, th.c1
        self._build_boundary()
        self.state: KilnState | None = None
        self.diag = StepDiagnostics()
        self.logs: list[StepLog] = []
        self._u = None
        self._transport_counter = 0
        self.warnings: list[str] = list(self.ms.warnings) + list(self.pellet_warn)

    # ------------------------------------------------------------------ setup
    def _build_materials(self):
        cfg = self.cfg
        c1, c2 = _coal(cfg.coal.feed_coal), _coal(cfg.coal.injection_coal)
        w1, w2 = cfg.coal.feed_coal_tph, cfg.coal.injection_coal_tph
        self.coal_feed, self.coal_inj = c1, c2
        coal = _blend_coal(c1, max(w1, 1e-9), c2, max(w2, 1e-9))
        ash1, ash2 = _ash_map(cfg.coal.feed_coal.ash_oxides_wt_pct), _ash_map(cfg.coal.injection_coal.ash_oxides_wt_pct)
        ash = {}
        m_ash1, m_ash2 = w1 * c1.ash, w2 * c2.ash
        dol_inert = cfg.flux.dolomite_tph * cfg.flux.dolomite_wt_pct.get("SiO2", 0.0) / 100.0
        char_ash = cfg.flux.recycle_char_tph * (1 - cfg.flux.recycle_char_C_pct / 100.0)
        for comp, m in ((ash1, m_ash1), (ash2, m_ash2), ({"SiO2": 100.0}, dol_inert + char_ash)):
            s = sum(comp.values()) or 1.0
            for k, v in comp.items():
                ash[k] = ash.get(k, 0.0) + m * v / s
        if sum(ash.values()) <= 0:
            ash = {"SiO2": 1.0}
        sp, gangue, warn = pellet_assay_to_species(cfg.pellet.assay_dry_wt_pct)
        self.pellet_species, self.pellet_warn = sp, warn
        self.ms = build_material_system(gangue, ash, coal, cfg.kinetics.vm_O_to_CO_frac)
        self.coal_blend = coal

    def _build_boundary(self):
        """Feed vectors (kmol/s) and air sources from the current configuration."""
        cfg, ms = self.cfg, self.ms
        N = self.N
        feed = np.zeros(NS)
        # pellets
        m_pel = tph_to_kgps(cfg.pellet.feed_tph)
        moist = cfg.pellet.moisture_wt_pct / 100.0
        m_dry = m_pel * (1 - moist)
        for k, w in self.pellet_species.items():
            feed[SI[k]] += m_dry * w / ms.mw_s[SI[k]]
        feed[SI["H2O_l"]] += m_pel * moist / 18.015
        self.pellet_dry_kgps = m_dry
        # coal (feed end)
        self.coal_feed_vec = self._coal_vec(self.coal_feed, tph_to_kgps(cfg.coal.feed_coal_tph))
        feed += self.coal_feed_vec
        # dolomite
        m_dol = tph_to_kgps(cfg.flux.dolomite_tph)
        dm = cfg.flux.dolomite_moisture_pct / 100.0
        dw = cfg.flux.dolomite_wt_pct
        s = sum(dw.values()) or 1.0
        feed[SI["CaCO3"]] += m_dol * (1 - dm) * dw.get("CaCO3", 0) / s / 100.087
        feed[SI["MgCO3"]] += m_dol * (1 - dm) * dw.get("MgCO3", 0) / s / 84.314
        feed[SI["ASH"]] += m_dol * (1 - dm) * dw.get("SiO2", 0) / s
        feed[SI["H2O_l"]] += m_dol * dm / 18.015
        # recycled char
        m_rc = tph_to_kgps(cfg.flux.recycle_char_tph)
        feed[SI["C"]] += m_rc * cfg.flux.recycle_char_C_pct / 100.0 / 12.011
        feed[SI["ASH"]] += m_rc * (1 - cfg.flux.recycle_char_C_pct / 100.0)
        self.feed = feed
        self.T_feed = C_to_K(cfg.air.ambient_temperature_C)
        # injection coal distributed over landing zone
        inj = self._coal_vec(self.coal_inj, tph_to_kgps(cfg.coal.injection_coal_tph))
        z_lo = self.L - cfg.coal.injection_throw_max_m
        z_hi = self.L - cfg.coal.injection_throw_min_m
        w = np.clip(np.minimum(self.z_edges[1:], z_hi) - np.maximum(self.z_edges[:-1], z_lo), 0, None)
        if w.sum() <= 0:
            w[-1] = 1.0
        w = w / w.sum()
        self.inj_dist = w
        self.inj = inj[:, None] * w[None, :]  # (NS, N)
        # air
        a = cfg.air
        T_amb = C_to_K(a.ambient_temperature_C)
        self.T_air = C_to_K(a.air_temperature_C)
        self.T_amb = T_amb
        # humidity: Magnus saturation pressure
        psat = 610.94 * math.exp(17.625 * a.ambient_temperature_C / (a.ambient_temperature_C + 243.04))
        y_h2o = min(a.relative_humidity_pct / 100.0 * psat / P_ATM, 0.2)
        self.y_air_h2o = y_h2o

        def air(nm3h_dry):
            v = np.zeros(NG)
            k = nm3h_to_kmolps(nm3h_dry, NTP)
            v[GI["O2"]] = 0.2095 * k
            v[GI["N2"]] = 0.7905 * k
            v[GI["H2O"]] = k * y_h2o / (1 - y_h2o)
            return v

        self._air = air
        self.gas_boundary = air(a.primary_air_nm3h + a.injection_carrier_air_nm3h + a.leak_discharge_end_nm3h)
        self.air_src = np.zeros((NG, N))
        self.tube_cells = {}
        for t in a.secondary_tubes:
            if not t.available or t.flow_nm3h <= 0:
                continue
            j = min(int(t.z_m / self.dz), N - 1)
            self.air_src[:, j] += air(min(t.flow_nm3h, t.max_nm3h))
            self.tube_cells[t.tube_id] = j
        self.air_src[:, 0] += air(a.leak_feed_end_nm3h)
        # pellet geometry
        p = cfg.pellet
        self.r0 = p.diameter_mm / 2000.0
        m_pellet = p.apparent_density_kg_m3 * math.pi / 6 * (p.diameter_mm / 1000.0) ** 3
        fe_frac = cfg.pellet.assay_dry_wt_pct["Fe_total"] / 100.0
        self.fe_per_pellet = m_pellet * fe_frac / AW["Fe"]  # kmol Fe per pellet
        self.vbulk_per_kmol_fe = AW["Fe"] / (fe_frac * p.bulk_density_kg_m3)
        vc = np.zeros(NS)
        vf = self.vbulk_per_kmol_fe
        vc[SI["Fe2O3"]], vc[SI["Fe3O4"]], vc[SI["FeO"]], vc[SI["Fe"]], vc[SI["FeS"]] = 2 * vf, 3 * vf, vf, vf, vf
        rc = self.cfg.coal.feed_coal.bulk_density_kg_m3
        mix = 0.85  # coal partly fills pellet interstices (documented assumption)
        vc[SI["C"]] = 12.011 * mix / rc
        vc[SI["VM"]] = mix / rc
        vc[SI["ASH"]] = mix / rc
        vc[SI["S"]] = 32.06 * mix / rc
        for k in ("CaCO3", "MgCO3", "CaO", "MgO", "CaS"):
            vc[SI[k]] = self.ms.mw_s[SI[k]] / 1500.0
        self.vol_coeff = vc

    def _coal_vec(self, c: CoalProps, m_kgps: float) -> np.ndarray:
        v = np.zeros(NS)
        v[SI["C"]] = m_kgps * c.fc / 12.011
        v[SI["VM"]] = m_kgps * c.vm_no_s
        v[SI["ASH"]] = m_kgps * c.ash
        v[SI["H2O_l"]] = m_kgps * c.moisture / 18.015
        v[SI["S"]] = m_kgps * c.S / AW["S"]
        return v

    def refresh_inputs(self):
        """Re-read time-varying operating inputs (feeds, air, rpm) without resetting state.
        Feed chemistry changes that alter pseudo-species require a new model."""
        self._build_boundary()
        self._u = None

    # -------------------------------------------------------------- geometry
    def bed_volume(self, n):
        vc = self.vol_coeff
        V = vc @ n
        pel = [SI[k] for k in ("Fe2O3", "Fe3O4", "FeO", "Fe", "FeS")]
        coal = [SI[k] for k in ("C", "VM", "ASH", "S")]
        return V, vc[pel] @ n[pel], (vc[coal] @ n[coal]) / 0.85

    def _kramers_flux(self, h_left, h_right, dzf):
        """Volumetric solids flow (m3/s) across a face from Kramers-Croockewit:
        Q = (4 pi n R^3 / 3) X^(3/2) [tan(a)/sin(b) - (dh/dz)/tan(b)],  X = 2h/R - (h/R)^2."""
        g = self.cfg.geometry
        R = self.R
        n_rps = g.rpm / 60.0
        a = math.atan(g.slope_pct / 100.0)
        b = math.radians(g.dynamic_repose_angle_deg)
        hf = 0.5 * (h_left + h_right)
        X = np.clip(2 * hf / R - (hf / R) ** 2, 0.0, 1.0)
        drive = math.tan(a) / math.sin(b) - (h_right - h_left) / dzf / math.tan(b)
        return 4.0 / 3.0 * math.pi * n_rps * R ** 3 * X ** 1.5 * drive, X

    def _advect(self, n, Ts, dt):
        """Sub-cycled conservative solids transport.  Returns post-advection
        inventory, enthalpy moved (J per cell, net in), discharge (kmol), and
        mean axial velocity per cell."""
        N = self.N
        g = self.cfg.geometry
        vc = self.vol_coeff
        hs = self.ms.h_s(Ts)  # (NS, N) - temperature frozen over the step
        n = n.copy()
        Hnet = np.zeros(N)
        dis = np.zeros(NS)
        moved = np.zeros(N + 1)
        # stable sub-step from the effective diffusivity of the depth equation
        V = np.maximum(vc @ n, 1e-9)
        A = np.clip(V / self.dz, 1e-5, 0.6 * math.pi * self.R ** 2)
        h = bt.height_from_area(A, self.R, iters=30)
        _, _, chord, _, _ = bt.segment_from_height(h, self.R)
        K = 4.0 / 3.0 * math.pi * (g.rpm / 60.0) * self.R ** 3 * np.clip(2 * h / self.R - (h / self.R) ** 2, 0, 1) ** 1.5
        D = K / math.tan(math.radians(g.dynamic_repose_angle_deg)) / np.maximum(chord, 0.05)
        dt_sub = min(dt, 0.35 * self.dz ** 2 / max(D.max(), 1e-9))
        nsub = int(math.ceil(dt / dt_sub))
        nsub = min(nsub, 200)
        ds = dt / nsub
        feed_ds = self.feed * ds
        inj_ds = self.inj * ds
        H_feed = float(self.ms.h_s(self.T_feed) @ self.feed) * ds
        H_inj = (self.ms.h_s(self.T_air)[:, None] * self.inj).sum(0) * ds
        dam = g.discharge_dam_height_m
        for _ in range(nsub):
            V = np.maximum(vc @ n, 1e-12)
            A = np.clip(V / self.dz, 1e-6, 0.6 * math.pi * self.R ** 2)
            h = bt.height_from_area(A, self.R, iters=28)
            Q = np.zeros(N + 1)
            Q[1:N], _ = self._kramers_flux(h[:-1], h[1:], self.dz)
            # outlet over the dam: Kramers boundary condition h(L) = dam height
            q_out, _ = self._kramers_flux(h[-1:], np.array([max(dam, 1e-4)]), self.dz / 2)
            Q[N] = max(float(q_out[0]), 0.0) if h[-1] > 1e-4 else 0.0
            # cap each face by 90 % of the upwind cell volume per sub-step
            frac = np.zeros(N + 1)
            up = np.where(Q[1:N] >= 0, np.arange(0, N - 1), np.arange(1, N))
            frac[1:N] = np.clip(np.abs(Q[1:N]) * ds / V[up], 0, 0.9)
            frac[N] = np.clip(Q[N] * ds / V[-1], 0, 0.9)
            flux = np.zeros((NS, N + 1))
            flux[:, 1:N] = n[:, up] * frac[1:N] * np.sign(Q[1:N])
            flux[:, N] = n[:, -1] * frac[N]
            Hf = np.zeros(N + 1)
            Hf[1:N] = (hs[:, up] * n[:, up]).sum(0) * frac[1:N] * np.sign(Q[1:N])
            Hf[N] = (hs[:, -1] * n[:, -1]).sum() * frac[N]
            n = n + flux[:, :-1] - flux[:, 1:]
            Hnet += Hf[:-1] - Hf[1:]
            dis += flux[:, N]
            moved += Q * ds
            n[:, 0] += feed_ds
            Hnet[0] += H_feed
            n += inj_ds
            Hnet += H_inj
        u = (0.5 * (moved[:-1] + moved[1:]) / dt) / np.maximum(A, 1e-6)
        self._u = u
        self._h_bed = h
        self._nsub = nsub
        return n, Hnet, dis, u

    # ---------------------------------------------------------------- state
    def initial_state(self, template: dict | None = None) -> KilnState:
        """Staged initial inventory resembling an operating kiln (dried and
        devolatilised early, progressive reduction from ~40 % length, char
        consumption along the kiln).  Optionally overlay a normalised template
        (z/L, T_bed_C, T_gas_C, metallization) from a previous solution.
        Element balance of the *initial inventory* is not required; audits
        account for its accumulation."""
        N, M = self.N, self.M
        tau = bt.sullivan_residence_time_s(self.L, 2 * self.R, self.cfg.geometry.rpm, self.cfg.geometry.slope_pct,
                                           self.cfg.geometry.dynamic_repose_angle_deg)
        u = self.L / tau
        zf = self.zc / self.L
        n = np.zeros((NS, N))
        inj_cum = np.cumsum(self.inj, axis=1)
        if template is not None:
            met = np.interp(zf, template["zf"], template["met"]) / 100.0
            Ts = np.interp(zf, template["zf"], template["Ts_C"]) + 273.15
            Tg = np.interp(zf, template["zf"], template["Tg_C"]) + 273.15
        else:
            met = np.clip((zf - 0.40) / 0.55, 0, 1) * 0.9
            Ts = 330.0 + (1320.0 - 330.0) * np.clip(zf / 0.45, 0, 1)
            Tg = Ts + 120.0
        for j in range(N):
            v = self.feed + inj_cum[:, j]
            v = v.copy()
            fe = 2 * v[SI["Fe2O3"]] + 3 * v[SI["Fe3O4"]] + v[SI["FeO"]] + v[SI["Fe"]]
            m = met[j]
            v[SI["Fe2O3"]], v[SI["Fe3O4"]] = 0.0, 0.0
            if zf[j] < 0.40 and template is None:
                v[SI["Fe2O3"]] = fe / 2 * (1 - m)
            else:
                v[SI["FeO"]] = fe * (1 - m)
            v[SI["Fe"]] = fe * m
            if zf[j] > 0.10:
                v[SI["H2O_l"]] = 0.0
            if zf[j] > 0.25:
                v[SI["VM"]] *= 0.0
                v[SI["CaCO3"]] *= 0.0
                v[SI["MgCO3"]] *= 0.0
            v[SI["C"]] *= (1.0 - 0.45 * zf[j])
            n[:, j] = v * self.dz / u
        Tw = np.zeros((N, M))
        frac = np.linspace(0, 1, M)
        for i in range(M):
            Tw[:, i] = (Ts + 60) * (1 - frac[i]) + 520.0 * frac[i]
        Hs = (self.ms.h_s(Ts) * n).sum(0)
        F = np.tile(self.gas_boundary[:, None], (1, N)) + np.cumsum(self.air_src[:, ::-1], axis=1)[:, ::-1]
        st = KilnState(n=n, Hs=Hs, Ts=Ts, Tw=Tw, Tg=Tg, F=F, X=np.full(N, 0.7), yH=np.full(N, 0.1))
        self.state = st
        self._u = None
        self._T_face = None
        return st

    # ----------------------------------------------------------- utilities
    def _hg(self, T):
        return self._g_hf + self._g_a * (T - T298) + 0.5 * self._g_b * (T * T - T298 * T298) + self._g_c * (
            1.0 / T298 - 1.0 / T)

    def _hg_vec(self, T):
        """(NG, N) gas enthalpies for an array of temperatures."""
        T = np.asarray(T)[None, :]
        return (self._g_hf[:, None] + self._g_a[:, None] * (T - T298) + 0.5 * self._g_b[:, None] * (T * T - T298 * T298)
                + self._g_c[:, None] * (1.0 / T298 - 1.0 / T))

    def _cpg(self, T):
        return self._g_a + self._g_b * T + self._g_c / (T * T)

    def _invert_T(self, n, H, T0):
        T = T0.copy()
        for _ in range(8):
            f = (self.ms.h_s(T) * n).sum(0) - H
            d = (self.ms.cp_s(T) * n).sum(0)
            dT = -f / np.maximum(d, 1e-9)
            T = np.clip(T + np.clip(dT, -300, 300), 250.0, 2500.0)
            if np.max(np.abs(dT)) < 1e-6:
                break
        return T

    # ----------------------------------------------------------- chemistry
    def bed_rates(self, st: KilnState, Ts, geo, dt, n_adv=None):
        """Reaction extents (kmol/s) using the post-advection inventory n_adv
        (advect-then-react splitting).  Fast first-order processes (drying,
        devolatilisation, calcination, S release) use the backward-Euler form
        r = k n/(1 + k dt), which is unconditionally positive and smooth."""
        cfg, kin = self.cfg, self.cfg.kinetics
        n = st.n if n_adv is None else n_adv
        N = self.N
        P = P_ATM
        Ctot = P / (R_J_PER_KMOL_K * Ts)
        yH = np.clip(st.yH, 0.0, 0.6)
        fe_tot = 2 * n[SI["Fe2O3"]] + 3 * n[SI["Fe3O4"]] + n[SI["FeO"]] + n[SI["Fe"]]
        fe_safe = np.maximum(fe_tot, 1e-12)
        f_h = 2 * n[SI["Fe2O3"]] / fe_safe
        f_m = 3 * n[SI["Fe3O4"]] / fe_safe
        f_w = n[SI["FeO"]] / fe_safe
        n_pel = fe_tot / self.fe_per_pellet
        # product-layer porosity rises with oxygen removal
        conv = 1.0 - (3 * n[SI["Fe2O3"]] + 4 * n[SI["Fe3O4"]] + n[SI["FeO"]]) / np.maximum(1.5 * fe_tot, 1e-12)
        eps = np.clip(cfg.pellet.porosity + (kin.product_layer_porosity - cfg.pellet.porosity) * np.clip(conv, 0, 1)
                      + 0.05, 0.05, 0.9)
        tort = cfg.pellet.tortuosity
        coal = cfg.coal.feed_coal
        R = np.zeros((NR, N))
        # sources to the CO/CO2 pool independent of X (devolatilisation, calcination)
        k_dev = kn.arrhenius(kin.devol_A_per_s, kin.devol_E_J_mol, Ts)
        r_dev = n[SI["VM"]] * k_dev / (1.0 + k_dev * dt)
        y = self.ms.vm_yield
        S_CO = r_dev * y["CO"]
        S_CO2_dev = r_dev * y["CO2"]
        p_co2_guess = (1 - yH) * (1 - st.X)
        r_ca, r_mg = kn.calcination_rates(np.ones(N), np.ones(N), Ts, p_co2_guess, kin)  # per kmol
        r_ca = n[SI["CaCO3"]] * r_ca / (1.0 + r_ca * dt)
        r_mg = n[SI["MgCO3"]] * r_mg / (1.0 + r_mg * dt)
        S_CO2 = S_CO2_dev + r_ca + r_mg
        nC = n[SI["C"]]
        Kw = K_WGS(Ts)
        KB = K_BOUDOUARD(Ts)
        kB = kn.arrhenius(kin.boudouard_A_per_s_atm, kin.boudouard_E_J_mol, Ts) * kin.gasification_multiplier * \
            coal.reactivity_factor * (8.0 / max(coal.size_mm, 0.5)) ** 0.5
        X_fb = st.F[GI["CO"]] / np.maximum(st.F[GI["CO"]] + st.F[GI["CO2"]], 1e-12)
        G_ex = 1.0e-3 * geo["A_bs"] * Ctot * (1 - yH)  # bed-freeboard COx exchange (kmol/s)

        co_aff = kn.three_interface_rates(f_h, f_m, f_w, self.r0, Ts, Ctot * (1 - yH), None, "CO", kin, eps, tort)

        def co_red(X):
            r_h, r_m, r_w = co_aff(X)
            return r_h * n_pel, r_m * n_pel, r_w * n_pel

        def resid(X):
            rh, rm, rw = co_red(X)
            Rc = rh + rm + rw
            pco, pco2 = (1 - yH) * X, (1 - yH) * (1 - X)
            Rb = kn.boudouard_rate(nC, Ts, pco2, pco, kin, coal.reactivity_factor, coal.size_mm, KB, kB)
            return Rc + S_CO2 + G_ex * (1 - X_fb) - Rb - (1 - X) * (Rb + S_CO + S_CO2 + G_ex)

        lo = np.zeros(N)
        hi = np.ones(N)
        for _ in range(28):
            mid = 0.5 * (lo + hi)
            r = resid(mid)
            lo = np.where(r < 0, mid, lo)
            hi = np.where(r >= 0, mid, hi)
        X = 0.5 * (lo + hi)
        rh, rm, rw = co_red(X)
        pco, pco2 = (1 - yH) * X, (1 - yH) * (1 - X)
        R[RID["R01_HEM_CO"]], R[RID["R02_MAG_CO"]], R[RID["R03_WUS_CO"]] = rh, rm, rw
        R[RID["R07_BOUDOUARD"]] = kn.boudouard_rate(nC, Ts, pco2, pco, kin, coal.reactivity_factor, coal.size_mm, KB, kB)
        # hydrogen pair, equilibrated with CO pair through water-gas shift
        ratio = Kw * X / np.maximum(1 - X, 1e-9)
        XH = ratio / (1 + ratio)
        rhH, rmH, rwH = kn.three_interface_rates(f_h, f_m, f_w, self.r0, Ts, Ctot * yH, XH, "H2", kin, eps, tort)
        R[RID["R04_HEM_H2"]], R[RID["R05_MAG_H2"]], R[RID["R06_WUS_H2"]] = rhH * n_pel, rmH * n_pel, rwH * n_pel
        ph2, ph2o = yH * XH, yH * (1 - XH)
        R[RID["R08_STEAM_GASIF"]] = kn.steam_gasification_rate(nC, Ts, ph2o, pco, ph2, kin, coal.reactivity_factor,
                                                               coal.size_mm)
        k_ev = kn.arrhenius(kin.evap_A_per_s, kin.evap_E_J_mol, Ts)
        R[RID["R15_EVAP"]] = n[SI["H2O_l"]] * k_ev / (1.0 + k_ev * dt)
        R[RID["R16_DEVOL"]] = r_dev
        R[RID["R17_CALC_CA"]], R[RID["R18_CALC_MG"]] = r_ca, r_mg
        # sulfur: released with volatiles (first-order, same rate constant)
        k_s = 0.5 * k_dev
        r_s = n[SI["S"]] * k_s / (1.0 + k_s * dt)
        h2_avail = r_dev * y["H2"] + 0.3 * st.F[GI["H2"]]
        r_s = np.minimum(r_s, 0.9 * h2_avail)
        R[RID["R19_S_RELEASE"]] = r_s
        ca_frac = n[SI["CaO"]] / np.maximum(n[SI["CaO"]] + 0.05 * n_pel * self.fe_per_pellet + 1e-12, 1e-12)
        R[RID["R20_CAS_CAPTURE"]] = r_s * kin.h2s_capture_efficiency * ca_frac
        fe_met = n[SI["Fe"]] / fe_safe
        R[RID["R21_FES_PICKUP"]] = r_s * (1 - kin.h2s_capture_efficiency * ca_frac) * kin.fes_pickup_frac * fe_met
        # O2 attack on bed surface (mass-transfer limited, heat/mass analogy)
        yO2_fb = st.F[GI["O2"]] / np.maximum(st.F.sum(0), 1e-12)
        k_m = geo["h_gs_conv"] / np.maximum(geo["rho_g"] * 1150.0, 1e-6) * 0.85 ** (-2 / 3)
        o2_flux = k_m * geo["A_bs"] * Ctot * yO2_fb
        o2_flux = np.minimum(o2_flux, 0.25 * st.F[GI["O2"]])
        V, Vp, Vc = self.bed_volume(n)
        phi_c = (0.85 * Vc) / np.maximum(V, 1e-9) * (nC > 1e-9)
        phi_fe = Vp / np.maximum(V, 1e-9) * fe_met
        tot_phi = np.maximum(phi_c + phi_fe, 1e-9)
        o2_c = o2_flux * phi_c / tot_phi * (phi_c + phi_fe > 1e-6)
        o2_fe = o2_flux * phi_fe / tot_phi * (phi_c + phi_fe > 1e-6)
        rho = kn.arthur_co_co2_ratio(Ts)
        f_co = rho / (1 + rho)
        nC_burn = o2_c / (f_co / 2 + 1 - f_co)
        R[RID["R11_C_O2_CO"]] = nC_burn * f_co / 2
        R[RID["R10_C_O2_CO2"]] = nC_burn * (1 - f_co)
        R[RID["R23_REOX"]] = o2_fe
        # bed H-pair fraction for next step (lagged): H2+H2O released / total released
        gas_rel = self.nu_g @ R
        h_rel = np.maximum(gas_rel[GI["H2"]], 0) + np.maximum(gas_rel[GI["H2O"]], 0)
        tot_rel = np.maximum(np.clip(gas_rel, 0, None).sum(0), 1e-12)
        yH_new = np.clip(h_rel / tot_rel, 0.0, 0.6)
        R = self._limit(R, n, st, dt)  # n is post-advection inventory here
        return R, X, yH_new

    def _limit(self, R, n, st, dt):
        """Positivity limiter: scale reaction extents so that no species inventory
        (solids) or freeboard supply (gas drawn by the bed) becomes negative."""
        active = 0
        for _ in range(3):
            pos = np.clip(R, 0, None)
            neg = np.clip(R, None, 0)
            prod_s = np.clip(self.nu_s, 0, None) @ pos + np.clip(-self.nu_s, 0, None) @ (-neg)
            cons_s = np.clip(-self.nu_s, 0, None) @ pos + np.clip(self.nu_s, 0, None) @ (-neg)
            avail_s = n / dt + 0.5 * prod_s
            ratio_s = np.where(cons_s > avail_s * 0.95, 0.95 * avail_s / np.maximum(cons_s, 1e-30), 1.0)
            prod_g = np.clip(self.nu_g, 0, None) @ pos + np.clip(-self.nu_g, 0, None) @ (-neg)
            cons_g = np.clip(-self.nu_g, 0, None) @ pos + np.clip(self.nu_g, 0, None) @ (-neg)
            F_in = np.zeros_like(st.F)
            F_in[:, :-1] = st.F[:, 1:]
            F_in[:, -1] = self.gas_boundary
            F_in += self.air_src
            avail_g = prod_g + 0.5 * np.maximum(F_in, 0)
            ratio_g = np.where(cons_g > avail_g, avail_g / np.maximum(cons_g, 1e-30), 1.0)
            # per-reaction scale = min over its reactant species
            scale = np.ones_like(R)
            for k in range(NR):
                for direction, msk_s, msk_g in ((1, self.nu_s[:, k] < 0, self.nu_g[:, k] < 0),
                                                (-1, self.nu_s[:, k] > 0, self.nu_g[:, k] > 0)):
                    m = np.ones(R.shape[1])
                    if msk_s.any():
                        m = np.minimum(m, ratio_s[msk_s].min(0))
                    if msk_g.any():
                        m = np.minimum(m, ratio_g[msk_g].min(0))
                    sel = (R[k] >= 0) if direction == 1 else (R[k] < 0)
                    scale[k] = np.where(sel, m, scale[k])
            if np.all(scale >= 1.0 - 1e-12):
                break
            active += int((scale < 1.0 - 1e-12).sum())
            R = R * scale
        self.diag.limiter_active = active
        return R

    # ------------------------------------------------------------ geometry
    def geometry(self, st: KilnState, Ts, u_s):
        n = st.n
        V, _, _ = self.bed_volume(n)
        A_bed = np.clip(V / self.dz, 1e-4, 0.45 * math.pi * self.R ** 2)
        h = bt.height_from_area(A_bed, self.R)
        theta, A, chord, cov, exp_ = bt.segment_from_height(h, self.R)
        A_gas = math.pi * self.R ** 2 - A
        P_gas = exp_ + chord
        D_e = 4 * A_gas / P_gas
        Ftot = np.maximum(st.F.sum(0), 1e-9)
        y = st.F / Ftot
        mw = (self.ms.mw_g[:, None] * y).sum(0)
        Tg = st.Tg
        rho_g = P_ATM * mw / (R_J_PER_KMOL_K * Tg)
        Vg = Ftot * R_J_PER_KMOL_K * Tg / P_ATM
        u_g = Vg / A_gas
        mu = gas_viscosity(Tg, y[GI["H2O"]], y[GI["CO2"]])
        kg = gas_conductivity(Tg, y[GI["H2O"]], y[GI["CO2"]])
        omega = 2 * math.pi * self.cfg.geometry.rpm / 60.0
        fill = A / (math.pi * self.R ** 2)
        h_gs, h_gw, Re = ht.tscheng_watkinson(rho_g, u_g, D_e, mu, kg, omega, fill)
        hm = self.cfg.heat
        h_gs *= hm.h_gs_multiplier
        h_gw *= hm.h_gw_multiplier
        Lm = 0.95 * D_e
        eps_g = ht.gas_emissivity(y[GI["CO2"]], y[GI["H2O"]], Lm, hm.gas_absorption_coeff_per_atm_m,
                                  hm.particle_absorption_coeff_per_m)
        mass_bed = self.ms.mw_s @ n
        cp_bed = (self.ms.cp_s(Ts) * n).sum(0) / np.maximum(mass_bed, 1e-9)
        rho_b = mass_bed / np.maximum(V, 1e-9)
        k_b = bed_effective_conductivity(Ts, hm.bed_conductivity_W_mK, self.r0 * 2)
        h_cw = ht.contact_wall_bed(k_b, rho_b, cp_bed, theta, self.cfg.geometry.rpm / 60.0, self.r0 * 2, kg)
        h_cw *= hm.h_cw_multiplier
        return dict(h=h, theta=theta, A_bed=A, chord=chord, A_bs=chord * self.dz, A_ew=exp_ * self.dz,
                    A_cw=cov * self.dz, A_gas=A_gas, D_e=D_e, rho_g=rho_g, u_g=u_g, Re=Re, h_gs_conv=h_gs,
                    h_gw_conv=h_gw, eps_g=eps_g, h_cw=h_cw, fill=fill, mu=mu, mass_bed=mass_bed, V_bed=V,
                    cp_bed=cp_bed, rho_bulk=rho_b)

    # ---------------------------------------------------------------- step
    def step(self, dt: float, cap_factor: float = 1.0, log: bool = True) -> KilnState:
        st = self.state
        cfg = self.cfg
        N = self.N
        ms = self.ms
        Ts = self._invert_T(st.n, st.Hs, st.Ts)
        u_s = self._u if self._u is not None else np.full(N, 1e-3)
        geo = self.geometry(st, Ts, u_s)
        # ---------------- solids transport first (advect-then-react splitting)
        n = st.n
        n_adv, H_adv_net, discharge, u_s = self._advect(n, Ts, dt)
        R, X, yH_new = self.bed_rates(st, Ts, geo, dt, n_adv)
        # ---------------- exchange coefficients (hot face from previous step)
        eps_w = cfg.geometry.wall_emissivity
        eps_s = cfg.geometry.bed_emissivity
        T_face = self._T_face if getattr(self, "_T_face", None) is not None else st.Tw[:, 0].copy()
        eps_ws = 1.0 / (1.0 / eps_w + 1.0 / eps_s - 1.0)
        eg = geo["eps_g"]
        Tg = st.Tg
        Hwb = (1 - eg) * eps_ws * SIGMA * (T_face ** 2 + Ts ** 2) * (T_face + Ts) * geo["A_bs"]
        Hcw = geo["h_cw"] * geo["A_cw"]
        Hb = Hwb + Hcw
        T_sh = st.Tw[:, -1]
        D_out = 2 * self.wall.r_out
        h_sh = ht.shell_htc(T_sh, self.T_amb, D_out, cfg.air.wind_speed_m_s, cfg.geometry.rpm / 60.0)
        h_sh_tot = (h_sh + ht.rad_h(T_sh, self.T_amb, cfg.lining.shell_emissivity)) * cfg.heat.shell_loss_multiplier
        Hout = h_sh_tot * math.pi * D_out  # W/(m K)
        w_alpha, w_beta, w_T0, w_T1 = self.wall.affine(st.Tw, dt, Hb / self.dz, Ts, Hout, self.T_amb, cap_factor)
        beta_cell = w_beta / self.dz  # K per W of cell gas-wall flux
        # ---------------- freeboard gas march (z = L -> 0)
        rel = self.nu_g @ R  # (NG, N) bed net gas production
        F = np.zeros((NG, N))
        Tg_new = np.zeros(N)
        Q_gs = np.zeros(N)
        Q_gw = np.zeros(N)
        fbR = np.zeros((NR, N))
        mix = cfg.air.freeboard_mixing_efficiency
        Kw_g = K_WGS(Tg)
        F_in = self.gas_boundary.copy()
        T_in = self.T_air
        h_air = self._hg(self.T_air)
        A_bs, A_ew = geo["A_bs"], geo["A_ew"]
        hgs_c, hgw_c = geo["h_gs_conv"], geo["h_gw_conv"]
        clip = 0.0
        max_it = 0
        for j in range(N - 1, -1, -1):
            pos = np.clip(rel[:, j], 0, None)
            neg = np.clip(rel[:, j], None, 0)
            Fj = F_in + self.air_src[:, j] + pos + neg
            if np.any(Fj < 0):
                clip += float(-Fj[Fj < 0].sum())
                neg = neg - np.minimum(Fj, 0)  # cannot draw more than available (logged)
                Fj = np.maximum(Fj, 0)
            # mixing-limited combustion of H2, CO, CH4, H2S
            o2 = Fj[GI["O2"]]
            dem = 0.5 * Fj[GI["H2"]] + 0.5 * Fj[GI["CO"]] + 2 * Fj[GI["CH4"]] + 1.5 * Fj[GI["H2S"]]
            if dem > 1e-14 and o2 > 1e-14:
                burn = min(mix * o2, dem) / dem
                e12, e13, e14, e22 = (burn * Fj[GI["CO"]], burn * Fj[GI["H2"]], burn * Fj[GI["CH4"]],
                                      burn * Fj[GI["H2S"]])
                fbR[RID["R12_CO_OX"], j], fbR[RID["R13_H2_OX"], j] = e12, e13
                fbR[RID["R14_CH4_OX"], j], fbR[RID["R22_H2S_OX"], j] = e14, e22
            # water-gas shift relaxation (50 % approach to equilibrium at previous T)
            Fc = Fj + self.nu_g[:, [RID["R12_CO_OX"], RID["R13_H2_OX"], RID["R14_CH4_OX"], RID["R22_H2S_OX"]]] @ \
                fbR[[RID["R12_CO_OX"], RID["R13_H2_OX"], RID["R14_CH4_OX"], RID["R22_H2S_OX"]], j]
            Kw = float(Kw_g[j])
            a_, b_, c_, d_ = Fc[GI["CO"]], Fc[GI["H2O"]], Fc[GI["CO2"]], Fc[GI["H2"]]
            # solve (c+x)(d+x) = K (a-x)(b-x) for x in [-min(c,d), min(a,b)]
            A2 = 1 - Kw
            B2 = c_ + d_ + Kw * (a_ + b_)
            C2 = c_ * d_ - Kw * a_ * b_
            if abs(A2) < 1e-12:
                x = -C2 / B2 if B2 != 0 else 0.0
            else:
                disc = max(B2 * B2 - 4 * A2 * C2, 0.0)
                r1 = (-B2 + math.sqrt(disc)) / (2 * A2)
                r2 = (-B2 - math.sqrt(disc)) / (2 * A2)
                lo_, hi_ = -min(c_, d_), min(a_, b_)
                x = r1 if lo_ - 1e-15 <= r1 <= hi_ + 1e-15 else r2
                x = min(max(x, lo_), hi_)
            fbR[RID["R09_WGS"], j] = 0.5 * x
            Fout = Fc + self.nu_g[:, RID["R09_WGS"]] * fbR[RID["R09_WGS"], j]
            Fout = np.maximum(Fout, 0.0)
            # energy: sum Fout h(Tg) - neg h(Tg) + Qgs(Tg) + Qgw(Tg) = H_in + H_air + pos h(Ts)
            Hrhs = F_in @ self._hg(T_in) + self.air_src[:, j] @ h_air + pos @ self._hg(Ts[j])
            Tsj = Ts[j]
            eg_j = eg[j]
            al, be = w_alpha[j], beta_cell[j]
            cw_ = hgw_c[j] * A_ew[j]
            rw_ = SIGMA * eg_j * 0.5 * (1 + eps_w) * A_ew[j]
            cs_ = hgs_c[j] * A_bs[j]
            rs_ = SIGMA * eg_j * 0.5 * (1 + eps_s) * A_bs[j]
            T = max(Tg[j], 400.0)
            Tf = T_face[j]
            for it in range(40):
                # hot face consistent with wall response: Tf = al + be*Qgw(T, Tf)
                for _k in range(20):
                    qw = cw_ * (T - Tf) + rw_ * (T ** 4 - Tf ** 4)
                    g_ = Tf - al - be * qw
                    dg = 1.0 + be * (cw_ + 4 * rw_ * Tf ** 3)
                    dTf = -g_ / dg
                    Tf += dTf
                    if abs(dTf) < 1e-8:
                        break
                hT = self._hg(T)
                cpT = self._cpg(T)
                qgs = cs_ * (T - Tsj) + rs_ * (T ** 4 - Tsj ** 4)
                qgw = cw_ * (T - Tf) + rw_ * (T ** 4 - Tf ** 4)
                f = Fout @ hT + (-neg) @ hT + qgs + qgw - Hrhs
                dq_dT = cw_ + 4 * rw_ * T ** 3
                dq_dTf = -(cw_ + 4 * rw_ * Tf ** 3)
                dTf_dT = be * dq_dT / (1.0 - be * dq_dTf)
                df = Fout @ cpT + (-neg) @ cpT + cs_ + 4 * rs_ * T ** 3 + dq_dT + dq_dTf * dTf_dT
                dT = -f / df
                dT = max(min(dT, 300.0), -300.0)
                T = min(max(T + dT, 250.0), 2600.0)
                if abs(dT) < 1e-7:
                    break
            max_it = max(max_it, it + 1)
            Tg_new[j] = T
            Q_gs[j] = cs_ * (T - Tsj) + rs_ * (T ** 4 - Tsj ** 4)
            Q_gw[j] = cw_ * (T - Tf) + rw_ * (T ** 4 - Tf ** 4)
            F[:, j] = Fout
            rel[:, j] = pos + neg  # actual (possibly clipped) exchange
            F_in = Fout
            T_in = T
        # ---------------- wall: implicit, exact gas-side flux (affine reconstruction)
        Tw_new, T_face_new, T_shell_face, q_bed, q_out = self.wall.finish(
            w_T0, w_T1, Q_gw / self.dz, Hb / self.dz, Ts, w_alpha, w_beta, Hout, self.T_amb, st.Tw)
        Q_cw = q_bed * self.dz * Hcw / Hb
        Q_wb = q_bed * self.dz * Hwb / Hb
        Q_shell = q_out * self.dz
        self._T_face = T_face_new
        T_face = T_face_new
        # ---------------- solids advection + reactions + energy
        hs = ms.h_s(Ts)
        # dust entrainment of coal fines (C, ASH) by gas velocity
        dust = np.zeros_like(n)
        kd = cfg.kinetics.dust_entrainment_coeff
        for sp in ("C", "ASH"):
            dust[SI[sp]] = np.minimum(kd * geo["u_g"] ** 2 * n_adv[SI[sp]] * dt, 0.2 * n_adv[SI[sp]])
        rxn_dt = (self.nu_s @ R) * dt
        n_new = n_adv + rxn_dt - dust
        rel_pos = np.clip(rel, 0, None)
        rel_neg = np.clip(rel, None, 0)
        hg_s = self._hg_vec(Ts)
        hg_g = self._hg_vec(Tg_new)
        H_gas_exch = -(rel_pos * hg_s).sum(0) - (rel_neg * hg_g).sum(0)  # J/s into bed
        H_dust = (hs * dust).sum(0)
        Hs_new = st.Hs + H_adv_net + dt * (H_gas_exch + Q_gs + Q_cw + Q_wb) - H_dust
        if np.any(n_new < -1e-9 * (np.abs(n).max() + 1)):
            self.diag.warnings.append("negative solids inventory after step (limiter insufficient)")
        n_new = np.maximum(n_new, 0.0)
        # ---------------- audit (per step, whole kiln)
        if log:
            el_s, el_g = ms.el_s, ms.el_g
            m_in = (ms.mw_s @ (self.feed + self.inj.sum(1))) * dt + ms.mw_g @ (
                self.gas_boundary + self.air_src.sum(1)) * dt
            m_out = (ms.mw_s @ discharge) + ms.mw_s @ dust.sum(1) + (ms.mw_g @ F[:, 0]) * dt
            m_acc = float(ms.mw_s @ (n_new.sum(1) - n.sum(1)))
            e_in = el_s.T @ (self.feed + self.inj.sum(1)) * dt + el_g.T @ (self.gas_boundary + self.air_src.sum(1)) * dt
            e_out = el_s.T @ (discharge + dust.sum(1)) + el_g.T @ F[:, 0] * dt
            e_acc = el_s.T @ (n_new.sum(1) - n.sum(1))
            H_in = dt * (float(ms.h_s(self.T_feed) @ self.feed) + float((ms.h_s(self.T_air)[:, None] * self.inj).sum())
                         + self.gas_boundary @ self._hg(self.T_air) + self.air_src.sum(1) @ h_air)
            H_out = float(hs[:, -1] @ discharge) + float(H_dust.sum()) + dt * float(F[:, 0] @ self._hg(Tg_new[0]))
            wall_E_old = (st.Tw * self.wall.cap[None, :]).sum() * self.dz * cap_factor
            wall_E_new = (Tw_new * self.wall.cap[None, :]).sum() * self.dz * cap_factor
            H_acc = float(Hs_new.sum() - st.Hs.sum()) + (wall_E_new - wall_E_old)
            self.logs.append(StepLog(st.t + dt, float(m_in), float(m_out), m_acc, e_in, e_out, e_acc, H_in, H_out,
                                     float(Q_shell.sum()) * dt, H_acc))
            if len(self.logs) > 400:
                self.logs = self.logs[-400:]
        Ts_new = self._invert_T(n_new, Hs_new, Ts)
        self.state = KilnState(n=n_new, Hs=Hs_new, Ts=Ts_new, Tw=Tw_new, Tg=Tg_new, F=F, X=X, yH=yH_new,
                               t=st.t + dt)
        d = self.diag
        d.rates, d.fb_rates = R, fbR
        d.Q_gs, d.Q_gw, d.Q_cw, d.Q_wb, d.Q_shell = Q_gs, Q_gw, Q_cw, Q_wb, Q_shell
        d.T_face_in, d.T_shell = T_face, T_shell_face
        d.eps_g, d.h_gs, d.h_gw, d.h_cw, d.u_g = eg, hgs_c, hgw_c, geo["h_cw"], geo["u_g"]
        d.dust = dust / dt
        d.gas_newton_max_iter = max_it
        d.gas_clip = clip
        d.geo = geo
        d.out_flow = discharge / dt
        d.rel = rel
        d.u_s = u_s
        return self.state

    # ------------------------------------------------------------- outputs
    def element_names(self):
        return ELEMENTS

    def discharge_flow(self):
        return self.diag.out_flow

    def offgas_flow(self):
        return self.state.F[:, 0], self.state.Tg[0]

    def species_names(self):
        return SOLIDS, GASES
