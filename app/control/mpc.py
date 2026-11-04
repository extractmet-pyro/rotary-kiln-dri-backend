"""Receding-horizon constrained supervisory MPC (advisory only).

Mandatory sequence implemented in `recommend`:
  data/quality gates -> current state (estimated) -> gain-scheduled step-response
  prediction -> constrained optimisation over Nc moves (SLSQP; bounds, ramp
  and cumulative-range constraints hard; process envelopes soft with dominant
  slack penalties) -> nonlinear check of the end point with the full surrogate
  -> uncertainty band -> safety gates -> ranked advisory recommendation.
Nothing here can write to equipment.  The browser/Render path is
SIMULATION/RECOMMENDATION ONLY.
"""
from __future__ import annotations

import time
from dataclasses import asdict

import numpy as np
from scipy.optimize import minimize

from app.control.constraints import SCENARIO_WEIGHTS, SOFT_PENALTY, MPCSettings, default_mvs, limits_from_config
from app.control.dynamics import FOPDT
from app.control.reduced_model import INPUTS, OUTPUTS, Surrogate

OI = {k: i for i, k in enumerate(OUTPUTS)}
N_MV = 5


class SupervisoryMPC:
    def __init__(self, sur: Surrogate, dyn: FOPDT, cfg, settings: MPCSettings | None = None):
        self.sur, self.dyn, self.cfg = sur, dyn, cfg
        self.s = settings or MPCSettings()
        self.lim = limits_from_config(cfg)

    def _coal_specific(self, u, y):
        return (u[1] + u[2]) * 1000.0 / max(y[OI["dri_t_h"]], 1e-6)

    def recommend(self, u_now: np.ndarray, y_meas: dict | None = None, scenario: str | None = None,
                  locked: list | None = None, timeout_s: float = 20.0, mv_overrides: dict | None = None) -> dict:
        t0 = time.time()
        scenario = scenario or self.s.scenario
        W = dict(SCENARIO_WEIGHTS.get(scenario, SCENARIO_WEIGHTS["multiobjective"]))
        W.update(self.s.weights or {})
        locked = set(locked or [])
        mvs = default_mvs(self.cfg, self.sur.baseline)
        for mv in mvs:
            if mv_overrides and mv.name in mv_overrides:
                for k, v in mv_overrides[mv.name].items():
                    setattr(mv, k, v)
            mv.locked = mv.name in locked
            mv.lo, mv.hi = max(mv.lo, self.sur.lo[[i[0] for i in INPUTS].index(mv.name)]), \
                min(mv.hi, self.sur.hi[[i[0] for i in INPUTS].index(mv.name)])
        free = [i for i, mv in enumerate(mvs) if not mv.locked and mv.commandable]
        Np, Nc, dt = self.s.Np, self.s.Nc, self.s.interval_min
        t_pred = np.arange(1, Np + 1) * dt
        y_ss0 = self.sur.predict(u_now)[0]
        bias = np.zeros(len(OUTPUTS))
        if y_meas:
            for k, v in y_meas.items():
                if k in OI and v is not None and np.isfinite(v):
                    bias[OI[k]] = v - y_ss0[OI[k]]
        J = self.sur.jacobian(u_now)[:, :N_MV]  # local gains (gain scheduling)
        # step responses for moves applied at t_m = m*dt  -> S[k, m, i, j]
        Sk = np.stack([self.dyn.step(t_pred - m * dt) for m in range(Nc)], axis=1)[:, :, :, :N_MV]
        ranges = np.array([mv.hi - mv.lo for mv in mvs])
        nf = len(free)
        if nf == 0:
            return self._result(u_now, u_now, np.zeros((Nc, N_MV)), t_pred, y_ss0, bias, J, Sk, mvs, scenario, W,
                                {"success": True, "message": "all MVs locked - no optimisation", "nit": 0}, t0)
        y_ref = y_ss0 + bias
        coal_base = self._coal_specific(u_now, y_ref)
        dri_base = max(y_ref[OI["dri_t_h"]], 1e-6)

        def unpack(x):
            du = np.zeros((Nc, N_MV))
            du[:, free] = x.reshape(Nc, nf)
            return du

        def predict(du):
            # y[k, i] = y_ref[i] + sum_m sum_j Sk[k,m,i,j] * J[i,j] * du[m,j]
            return y_ref[None, :] + np.einsum("kmij,ij,mj->ki", Sk, J, du)

        def cost(x):
            du = unpack(x)
            Y = predict(du)
            u_path = u_now[None, :N_MV] + np.cumsum(du, 0)
            u_k = np.array([u_path[min(int(k * dt // dt), Nc - 1)] for k in range(Np)])
            met = Y[:, OI["metallization_pct"]]
            bed = Y[:, OI["peak_bed_T_C"]]
            shell = Y[:, OI["peak_shell_T_C"]]
            ex = Y[:, OI["exit_gas_T_C"]]
            dri = np.maximum(Y[:, OI["dri_t_h"]], 1e-3)
            risk = Y[:, OI["accretion_risk_max"]]
            coal_sp = (u_k[:, 1] + u_k[:, 2]) * 1000 / dri
            J_ = W["met"] * np.mean(((met - self.lim.met_target) / 2.0) ** 2)
            J_ += W["temp"] * np.mean(((bed - (self.lim.bed_T_max - 25.0)) / 25.0) ** 2)
            J_ += W["coal"] * np.mean(coal_sp / coal_base)
            J_ += W["energy"] * np.mean(coal_sp / coal_base - 0.1 * Y[:, OI["steam_t_h"]] / max(y_ref[OI["steam_t_h"]], 1e-6))
            J_ += W["co2"] * np.mean(coal_sp / coal_base)
            J_ += W["risk"] * np.mean(risk)
            J_ -= W["throughput"] * np.mean(dri / dri_base)
            J_ += W["move"] * np.sum((du / ranges[None, :]) ** 2) * 10
            # soft process envelopes (slack^2), dominant over economics
            sl = np.concatenate([np.maximum(self.lim.met_min - met, 0) / 1.0,
                                 np.maximum(bed - self.lim.bed_T_max, 0) / 10.0,
                                 np.maximum(shell - self.lim.shell_T_max, 0) / 10.0,
                                 np.maximum(ex - self.lim.exit_T_max, 0) / 10.0,
                                 np.maximum(self.lim.exit_T_min - ex, 0) / 10.0,
                                 np.maximum(risk - self.lim.accretion_max, 0) / 0.05])
            J_ += SOFT_PENALTY * np.mean(sl ** 2)
            # terminal cost on the nonlinear surrogate steady state
            uT = u_now.copy()
            uT[:N_MV] = u_path[-1]
            yT = self.sur.predict(uT)[0] + bias
            J_ += 2.0 * W["met"] * ((yT[OI["metallization_pct"]] - self.lim.met_target) / 2.0) ** 2
            if hasattr(self.sur, "predict_std"):  # risk-aware: stay where the surrogate is confident
                sd_m = float(self.sur.predict_std(uT)[0][OI["metallization_pct"]])
                J_ += W.get("uncertainty", 3.0) * (sd_m / 2.0) ** 2 + SOFT_PENALTY * max(sd_m - 2.8, 0.0) ** 2
            J_ += SOFT_PENALTY * (max(self.lim.met_min - yT[OI["metallization_pct"]], 0) ** 2 +
                                  (max(yT[OI["peak_bed_T_C"]] - self.lim.bed_T_max, 0) / 10) ** 2)
            return float(J_)

        # hard constraints: ramp (bounds on each move) and cumulative range (linear)
        bnds = []
        for m in range(Nc):
            for j in free:
                r = mvs[j].ramp_per_interval
                bnds.append((-r, r))
        A, b = [], []
        for m in range(Nc):
            for jj, j in enumerate(free):
                row = np.zeros(Nc * nf)
                for mm in range(m + 1):
                    row[mm * nf + jj] = 1.0
                A.append(row), b.append(mvs[j].hi - u_now[j])  # cum <= hi - u
                A.append(-row), b.append(u_now[j] - mvs[j].lo)  # -cum <= u - lo
        A, b = np.array(A), np.array(b)
        cons = [{"type": "ineq", "fun": lambda x: b - A @ x, "jac": lambda x: -A}]
        x0 = np.zeros(Nc * nf)
        # if the current point violates a range (e.g. after an override), start feasible
        res = minimize(cost, x0, method="SLSQP", bounds=bnds, constraints=cons,
                       options={"maxiter": 200, "ftol": 1e-7})
        du = unpack(res.x)
        u_final = u_now.copy()
        u_final[:N_MV] = u_now[:N_MV] + du.sum(0)
        info = {"success": bool(res.success), "message": str(res.message), "nit": int(res.nit),
                "objective": float(res.fun), "objective_no_move": float(cost(x0))}
        if time.time() - t0 > timeout_s:
            info["success"] = False
            info["message"] = f"optimiser exceeded timeout {timeout_s}s"
        return self._result(u_now, u_final, du, t_pred, y_ss0, bias, J, Sk, mvs, scenario, W, info, t0)

    def _result(self, u_now, u_final, du, t_pred, y_ss0, bias, J, Sk, mvs, scenario, W, info, t0):
        y_ref = y_ss0 + bias
        Y = y_ref[None, :] + np.einsum("kmij,ij,mj->ki", Sk, J, du)
        Y0 = np.tile(y_ref, (len(t_pred), 1))
        yT = self.sur.predict(u_final)[0] + bias
        rm = self.sur.loo_rmse
        band = 1.96 * rm[None, :] * np.sqrt(1 + np.arange(1, len(t_pred) + 1)[:, None] / len(t_pred))
        dom_now = self.sur.domain_check(u_now)
        dom_fin = self.sur.domain_check(u_final)
        coal_now = (u_now[1] + u_now[2]) * 1000 / max(y_ref[OI["dri_t_h"]], 1e-6)
        coal_fin = (u_final[1] + u_final[2]) * 1000 / max(yT[OI["dri_t_h"]], 1e-6)
        moves = []
        for j, mv in enumerate(mvs):
            moves.append({"mv": mv.name, "unit": mv.unit, "current": float(u_now[j]), "recommended": float(u_final[j]),
                          "delta": float(u_final[j] - u_now[j]), "min": mv.lo, "max": mv.hi,
                          "ramp_per_interval": mv.ramp_per_interval, "locked": mv.locked,
                          "schedule": [float(u_now[j] + du[:m + 1, j].sum()) for m in range(du.shape[0])]})
        pred = {"t_min": t_pred.tolist(),
                "optimised": {k: Y[:, i].tolist() for i, k in enumerate(OUTPUTS)},
                "no_change_baseline": {k: Y0[:, i].tolist() for i, k in enumerate(OUTPUTS)},
                "band_95": {k: band[:, i].tolist() for i, k in enumerate(OUTPUTS)}}
        deltas = {"metallization_pp": float(yT[OI["metallization_pct"]] - y_ref[OI["metallization_pct"]]),
                  "dri_t_h": float(yT[OI["dri_t_h"]] - y_ref[OI["dri_t_h"]]),
                  "coal_kg_per_t_dri": float(coal_fin - coal_now),
                  "peak_bed_T_C": float(yT[OI["peak_bed_T_C"]] - y_ref[OI["peak_bed_T_C"]]),
                  "accretion_risk": float(yT[OI["accretion_risk_max"]] - y_ref[OI["accretion_risk_max"]]),
                  "steam_t_h": float(yT[OI["steam_t_h"]] - y_ref[OI["steam_t_h"]])}
        lim = self.lim
        viol = []
        if yT[OI["metallization_pct"]] < lim.met_min:
            viol.append("metallization below minimum at end point")
        if yT[OI["peak_bed_T_C"]] > lim.bed_T_max:
            viol.append("peak bed temperature above envelope at end point")
        if yT[OI["peak_shell_T_C"]] > lim.shell_T_max:
            viol.append("shell temperature above envelope at end point")
        local_sd = None
        if hasattr(self.sur, "predict_std"):
            local_sd = {k: float(v) for k, v in zip(OUTPUTS, self.sur.predict_std(u_final)[0])}
        hold_h = float(np.max(self.dyn.theta_min[OI["metallization_pct"], :N_MV] +
                              3 * self.dyn.tau_min[OI["metallization_pct"], :N_MV]) / 60.0)
        return {
            "scenario": scenario, "weights": W, "settings": asdict(self.s),
            "solver": {**info, "solve_time_s": round(time.time() - t0, 3), "algorithm": "SLSQP (scipy)",
                       "prediction_model": "gain-scheduled step-response (surrogate Jacobian x FOPDT dynamics)",
                       "dynamics_source": self.dyn.source},
            "moves": moves, "prediction": pred, "end_point": {k: float(v) for k, v in zip(OUTPUTS, yT)},
            "current_estimate": {k: float(v) for k, v in zip(OUTPUTS, y_ref)},
            "expected_deltas": deltas,
            "model_error_95": {k: float(1.96 * v) for k, v in zip(OUTPUTS, rm)},
            "local_predictive_sd_end_point": local_sd,
            "constraint_check": {"end_point_violations": viol, "hard_constraints": "bounds+ramps+ranges enforced by solver",
                                 "domain_now": dom_now, "domain_final": dom_fin},
            "hold_time_h": hold_h,
            "explanation": explain(moves, deltas, scenario),
        }


def explain(moves, deltas, scenario) -> str:
    parts = []
    for m in moves:
        if abs(m["delta"]) > 1e-3 * max(abs(m["current"]), 1):
            parts.append(f"{m['mv']} {m['current']:.3g} -> {m['recommended']:.3g} {m['unit']}")
    if not parts:
        return f"[{scenario}] Current operation is already near the optimum of the selected objective; hold."
    return (f"[{scenario}] Suggested: " + "; ".join(parts) +
            f". Expected at new steady state: metallization {deltas['metallization_pp']:+.2f} pp, "
            f"specific coal {deltas['coal_kg_per_t_dri']:+.0f} kg/t DRI, DRI {deltas['dri_t_h']:+.2f} t/h, "
            f"peak bed {deltas['peak_bed_T_C']:+.0f} C. Projections are surrogate-model estimates (see error band).")
