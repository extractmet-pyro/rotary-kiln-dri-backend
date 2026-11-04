"""Heat-transfer closures for the freeboard gas, bed, wall and shell.

Paths (per axial cell, all in W):
  Q_gs   gas -> exposed bed surface        convection + gray-gas radiation
  Q_gw   gas -> exposed wall               convection + gray-gas radiation
  Q_ws_r exposed wall -> bed surface        radiation through gas (1-eps_g)
  Q_cw   covered wall -> bed                regenerative contact (penetration theory)
  Q_sh   shell -> ambient                   natural/forced convection + radiation
  Radial conduction through refractory layers and shell (transient, implicit).

Correlations (verify coefficients against originals before site use):
  * Tscheng S.H.; Watkinson A.P. (1979) "Convective heat transfer in a rotary
    kiln", Can. J. Chem. Eng. 57:433-443  (gas-wall, gas-bed convection).
  * Covered-wall contact: Higbie penetration theory with a gas-film contact
    resistance ~0.1 d_p/k_g (cf. Wes, Drinkenburg & Stemerding 1976, Powder
    Technol. 13:185; Li, Chang, Wang 2005 review).  Configurable multiplier.
  * Gray-gas emissivity: eps = 1 - exp(-kappa (pCO2+pH2O) L_m) combined with a
    dust/char particle cloud term; engineering approximation of Hottel charts.
  * Shell: Churchill & Chu (1975) natural convection and Churchill & Bernstein
    (1977) cross-flow correlations for cylinders, combined as a cube-root sum.
"""
from __future__ import annotations

import numpy as np

from app.core.units import SIGMA
from app.physics.properties import gas_conductivity, gas_viscosity


def tscheng_watkinson(rho_g, u_g, D_e, mu, k_g, omega_rad_s, fill):
    Re = np.maximum(rho_g * np.abs(u_g) * D_e / mu, 1.0)
    Re_w = np.maximum(rho_g * omega_rad_s * D_e ** 2 / mu, 1.0)
    h_gw = 1.54 * k_g / D_e * Re ** 0.575 * Re_w ** -0.292
    h_gs = 0.46 * k_g / D_e * Re ** 0.535 * Re_w ** 0.104 * np.maximum(fill, 0.02) ** -0.341
    return h_gs, h_gw, Re


def contact_wall_bed(k_bed, rho_bulk, cp_bed, theta, n_rps, d_p, k_gas):
    t_c = np.maximum(theta / (2 * np.pi * max(n_rps, 1e-6)), 1.0)
    h_pen = 2.0 * np.sqrt(k_bed * rho_bulk * cp_bed / (np.pi * t_c))
    r_c = 0.1 * d_p / k_gas
    return 1.0 / (1.0 / h_pen + r_c)


def gas_emissivity(p_co2_atm, p_h2o_atm, L_m, kappa_g, kappa_p):
    eps_g = 1.0 - np.exp(-kappa_g * np.maximum(p_co2_atm + p_h2o_atm, 0.0) * L_m)
    eps_p = 1.0 - np.exp(-kappa_p * L_m)
    return np.clip(1.0 - (1.0 - eps_g) * (1.0 - eps_p), 0.01, 0.95)


def _air_props(T):
    mu = gas_viscosity(T, 0.0, 0.0)
    k = gas_conductivity(T, 0.0, 0.0)
    rho = 101325 * 28.96 / (8314.46 * T)
    return mu / rho, k, 0.70


def shell_htc(T_shell, T_amb, D_out, wind_m_s, n_rps):
    """Convective htc (W/m2K) for the rotating kiln shell."""
    T_shell = np.asarray(T_shell, dtype=float)
    Tf = 0.5 * (T_shell + T_amb)
    nu, k, Pr = _air_props(Tf)
    beta = 1.0 / Tf
    dT = np.maximum(np.abs(T_shell - T_amb), 0.1)
    Ra = 9.80665 * beta * dT * D_out ** 3 / (nu * nu) * Pr
    Nu_n = (0.60 + 0.387 * Ra ** (1 / 6) / (1 + (0.559 / Pr) ** (9 / 16)) ** (8 / 27)) ** 2
    u_eff = np.sqrt(wind_m_s ** 2 + (np.pi * D_out * n_rps) ** 2)
    Re = np.maximum(u_eff * D_out / nu, 1.0)
    Nu_f = 0.3 + 0.62 * Re ** 0.5 * Pr ** (1 / 3) / (1 + (0.4 / Pr) ** (2 / 3)) ** 0.25 * (1 + (Re / 282000) ** 0.625) ** 0.8
    Nu = (Nu_n ** 3 + Nu_f ** 3) ** (1 / 3)
    return Nu * k / D_out


def rad_h(T1, T2, eps):
    """Linearised radiative htc: eps*sigma*(T1^2+T2^2)(T1+T2)."""
    return eps * SIGMA * (T1 * T1 + T2 * T2) * (T1 + T2)


def thomas(a, b, c, d):
    """Vectorised tridiagonal solve along last axis. a: sub, b: diag, c: super."""
    n = b.shape[-1]
    cp = np.zeros_like(b)
    dp = np.zeros_like(b)
    cp[..., 0] = c[..., 0] / b[..., 0]
    dp[..., 0] = d[..., 0] / b[..., 0]
    for i in range(1, n):
        m = b[..., i] - a[..., i] * cp[..., i - 1]
        cp[..., i] = c[..., i] / m if i < n - 1 else 0.0
        dp[..., i] = (d[..., i] - a[..., i] * dp[..., i - 1]) / m
    x = np.zeros_like(b)
    x[..., -1] = dp[..., -1]
    for i in range(n - 2, -1, -1):
        x[..., i] = dp[..., i] - cp[..., i] * x[..., i + 1]
    return x


class WallModel:
    """Radial multi-layer wall per axial cell (per metre of kiln length).

    Node 0 is the refractory hot face (half-thickness node); the last node is
    the steel shell (lumped).  k(T) = k0 (1 + c (T - 298)).
    """

    def __init__(self, r_inner: float, layers: list, shell_t: float, shell_k: float, shell_rho: float,
                 shell_cp: float, wear_fraction: float = 0.0):
        radii = [r_inner]
        k0, kc, rc = [], [], []
        for li, lay in enumerate(layers):
            th = lay.thickness_m * ((1.0 - wear_fraction) if li == 0 else 1.0)
            n = lay.nodes
            for _ in range(n):
                radii.append(radii[-1] + th / n)
                k0.append(lay.k_W_mK)
                kc.append(lay.k_T_coeff_per_K)
                rc.append(lay.rho_kg_m3 * lay.cp_J_kgK)
        radii.append(radii[-1] + shell_t)
        k0.append(shell_k)
        kc.append(0.0)
        rc.append(shell_rho * shell_cp)
        self.r = np.array(radii)  # node boundaries, len M+1
        self.M = len(k0)
        self.k0 = np.array(k0)
        self.kc = np.array(kc)
        self.rhoc = np.array(rc)
        self.r_out = self.r[-1]
        self.r_in = r_inner
        rm = 0.5 * (self.r[1:] + self.r[:-1])
        self.rm = rm
        self.cap = self.rhoc * np.pi * (self.r[1:] ** 2 - self.r[:-1] ** 2)  # J/(m K) per node

    def conductances(self, T):
        """Node-to-node conductance (W/(m K)) from series half-shell resistances."""
        k = self.k0[None, :] * (1.0 + self.kc[None, :] * (T - 298.15))
        k = np.maximum(k, 0.02)
        # resistance from node centre to outer boundary and from inner boundary to centre
        r_lo, r_hi, rm = self.r[:-1], self.r[1:], self.rm
        R_out = np.log(r_hi / rm)[None, :] / (2 * np.pi * k)
        R_in = np.log(rm / r_lo)[None, :] / (2 * np.pi * k)
        G = 1.0 / (R_out[:, :-1] + R_in[:, 1:])  # between node i and i+1
        R_face_in = R_in[:, 0]  # hot face -> node 0 centre
        R_face_out = R_out[:, -1]  # shell centre -> outer surface
        return G, R_face_in, R_face_out

    def step(self, T, dt, h_bed, T_bed, q_fix, h_out, T_env_out, cap_factor=1.0):
        """Implicit (backward Euler) radial conduction.

        Inner face: fixed gas-side flux q_fix (W/m, exact value lost by the gas)
        plus linearised exchange h_bed (W/(m K)) with the bed at T_bed.
        Outer face: h_out (W/(m K)) to T_env_out.
        Returns T_new (N, M), hot-face T, shell-face T, bed flux (W/m), shell loss (W/m).
        """
        Tn, T_face_in, T_face_out, q_bed, q_out, _ = self._solve(T, dt, h_bed, T_bed, q_fix, h_out, T_env_out,
                                                                cap_factor)
        return Tn, T_face_in, T_face_out, q_bed, q_out

    def affine(self, T, dt, h_bed, T_bed, h_out, T_env_out, cap_factor=1.0):
        """Wall response is affine in the gas-side flux q (W/m) per cell:
        T_face(q) = alpha + beta*q ;  T_nodes(q) = T0 + q*T1.  Used for implicit
        gas-wall coupling inside the freeboard Newton iteration."""
        z = np.zeros(T.shape[0])
        Ta, fa, *_ = self._solve(T, dt, h_bed, T_bed, z, h_out, T_env_out, cap_factor)
        Tb_, fb, *_ = self._solve(T, dt, h_bed, T_bed, z + 1.0, h_out, T_env_out, cap_factor)
        return fa, fb - fa, Ta, Tb_ - Ta

    def finish(self, T0, T1, q, h_bed, T_bed, alpha, beta, h_out, T_env_out, T_old):
        Tn = T0 + q[:, None] * T1
        G, Rfi, Rfo = self.conductances(T_old)
        T_face_in = alpha + beta * q
        q_bed = np.maximum(h_bed, 1e-9) * (T_face_in - T_bed)
        Gout = 1.0 / (1.0 / np.maximum(h_out, 1e-9) + Rfo)
        q_out = Gout * (Tn[:, -1] - T_env_out)
        T_face_out = Tn[:, -1] - q_out * Rfo
        return Tn, T_face_in, T_face_out, q_bed, q_out

    def _solve(self, T, dt, h_bed, T_bed, q_fix, h_out, T_env_out, cap_factor=1.0):
        N, M = T.shape
        G, Rfi, Rfo = self.conductances(T)
        hb = np.maximum(h_bed, 1e-9)
        den = 1.0 + hb * Rfi
        Gin = hb / den
        Gout = 1.0 / (1.0 / np.maximum(h_out, 1e-9) + Rfo)
        C = self.cap[None, :] * cap_factor / dt
        a = np.zeros((N, M))
        b = np.zeros((N, M))
        c = np.zeros((N, M))
        d = C * T
        b += C
        b[:, :-1] += G
        b[:, 1:] += G
        c[:, :-1] = -G
        a[:, 1:] = -G
        b[:, 0] += Gin
        d[:, 0] += Gin * T_bed + q_fix / den
        b[:, -1] += Gout
        d[:, -1] += Gout * T_env_out
        Tn = thomas(a, b, c, d)
        T_face_in = (q_fix + hb * T_bed + Tn[:, 0] / Rfi) / (hb + 1.0 / Rfi)
        q_bed = hb * (T_face_in - T_bed)
        q_out = Gout * (Tn[:, -1] - T_env_out)
        T_face_out = Tn[:, -1] - q_out * Rfo
        return Tn, T_face_in, T_face_out, q_bed, q_out, Rfi
