"""Solids transport: bed geometry, Kramers-Croockewit/Saeman bed-depth profile,
residence time and residence-time distribution.

Kramers H.; Croockewit P. (1952) Chem. Eng. Sci. 1:259-265.
Saeman W.C. (1951) Chem. Eng. Prog. 47:508-514.
Sullivan J.D.; Maier C.G.; Ralston O.C. (1927) US Bureau of Mines Tech.
Paper 384 (empirical mean residence time) - used only as a cross-check.

Coordinate: z = 0 at feed end, z = L at discharge. The ODE is integrated from
the discharge dam (boundary condition h(L) = dam height, or the normal depth if
the dam is lower) toward the feed end.
"""
from __future__ import annotations

import numpy as np


def segment_from_height(h, R):
    """Bed central angle theta (rad), cross-section area, chord, covered arc."""
    h = np.clip(np.asarray(h, dtype=float), 1e-6, 2 * R - 1e-6)
    theta = 2.0 * np.arccos(1.0 - h / R)
    area = 0.5 * R * R * (theta - np.sin(theta))
    chord = 2.0 * R * np.sin(theta / 2.0)
    covered = R * theta
    exposed = R * (2 * np.pi - theta)
    return theta, area, chord, covered, exposed


def height_from_area(area, R, iters=40):
    """Invert segment area -> height by bisection (vectorised)."""
    area = np.asarray(area, dtype=float)
    lo = np.zeros_like(area)
    hi = np.full_like(area, 2 * R)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        a_mid = segment_from_height(mid, R)[1]
        lo = np.where(a_mid < area, mid, lo)
        hi = np.where(a_mid >= area, mid, hi)
    return 0.5 * (lo + hi)


def normal_depth(Qv, R, n_rps, slope_rad, beta_rad):
    """Uniform-flow bed depth from Saeman's relation (bisection)."""
    def flow(h):
        x = 2 * h / R - (h / R) ** 2
        return 4.0 / 3.0 * np.pi * n_rps * R ** 3 * np.tan(slope_rad) / np.sin(beta_rad) * x ** 1.5
    lo, hi = 1e-5, R
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if flow(mid) < Qv:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def saeman_profile(z_edges, Qv_cells, R, n_rpm, slope_pct, beta_deg, dam_h):
    """Bed depth at cell centres from the Kramers-Croockewit ODE.

    dh/dz' = tan(beta) * [ 3 Qv/(4 pi n R^3) * (2h/R - h^2/R^2)^(-3/2) - tan(alpha)/sin(beta) ]
    with z' measured from the discharge end toward the feed end.
    Qv_cells: local volumetric solids flow (m3/s) per cell (decreases along the
    kiln as coal is consumed).
    """
    n = n_rpm / 60.0
    alpha = np.arctan(slope_pct / 100.0)
    beta = np.radians(beta_deg)
    nc = len(Qv_cells)
    L = z_edges[-1]
    zc = 0.5 * (z_edges[1:] + z_edges[:-1])
    h_n_end = normal_depth(max(Qv_cells[-1], 1e-9), R, n, alpha, beta)
    h = max(dam_h, h_n_end)
    out = np.zeros(nc)
    # march from discharge (z=L) to feed (z=0) with sub-steps
    z_prev = L
    for j in range(nc - 1, -1, -1):
        target = zc[j]
        Qv = max(Qv_cells[j], 1e-9)
        hn = normal_depth(Qv, R, n, alpha, beta)
        nsub = 8
        dz = (z_prev - target) / nsub
        for _ in range(nsub):
            x = max(2 * h / R - (h / R) ** 2, 1e-6)
            dh = np.tan(beta) * (3 * Qv / (4 * np.pi * n * R ** 3) * x ** -1.5 - np.tan(alpha) / np.sin(beta))
            h_new = h + dh * dz
            # the profile relaxes monotonically toward normal depth; prevent overshoot
            if (h - hn) * (h_new - hn) < 0:
                h_new = hn
            h = float(np.clip(h_new, 1e-4, 1.2 * R))
        out[j] = h
        z_prev = target
    return out


def sullivan_residence_time_s(L, D, n_rpm, slope_pct, beta_deg):
    """Sullivan et al. (1927) t = 1.77 L sqrt(beta_deg) / (alpha_deg * D * n) [min]."""
    alpha_deg = np.degrees(np.arctan(slope_pct / 100.0))
    t_min = 1.77 * L * np.sqrt(beta_deg) / (alpha_deg * D * n_rpm)
    return 60.0 * t_min


def rtd_axial_dispersion(t, tau, peclet):
    """Open-open axial dispersion RTD E(t) (1/s); used to align lab samples."""
    t = np.maximum(np.asarray(t, dtype=float), 1e-9)
    th = t / tau
    return (1.0 / tau) * np.sqrt(peclet / (4 * np.pi * th)) * np.exp(-peclet * (1 - th) ** 2 / (4 * th))


def solids_peclet(L, n_rpm, D, mean_velocity):
    """Empirical estimate of the solids axial Peclet number (order 100-1000
    for industrial kilns); D_ax ~ 0.1 * (n D) * d -> simplified to a
    configurable form used only for RTD alignment, flagged CALIBRATION_REQUIRED."""
    d_ax = 1.0e-4 * (n_rpm / 60.0 * D) ** 0.5 + 1e-6
    return mean_velocity * L / d_ax
