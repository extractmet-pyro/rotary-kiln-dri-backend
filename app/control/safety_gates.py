"""Safety gates applied before any recommendation is shown as actionable.

Default operating mode is SAFE_ADVISORY_ONLY.  These gates never bypass or
modify site interlocks, SIS, burner management or local PID loops; they only
decide whether an analytic recommendation may be *displayed as actionable*.
"""
from __future__ import annotations

from datetime import datetime, timezone

MODES = ["DEMO_SYNTHETIC", "OFFLINE_SIMULATION", "HISTORICAL_REPLAY", "SHADOW", "ADVISORY", "SITE_SUPERVISORY"]
SUPERVISORY_ENABLED = False  # hard-coded: no cloud-to-PLC path exists in this codebase


def evaluate_gates(mode: str, mpc_result: dict, data_timestamp_utc: str | None, max_data_age_s: float = 900.0,
                   model_confidence_min: float = 0.5, surrogate_met_rmse_max_pp: float = 3.0) -> dict:
    reasons = []
    checks = []

    def chk(name, ok, detail):
        checks.append({"gate": name, "pass": bool(ok), "detail": detail})
        if not ok:
            reasons.append(f"{name}: {detail}")

    chk("mode", mode in MODES and mode != "SITE_SUPERVISORY" or SUPERVISORY_ENABLED,
        f"mode {mode}; site supervisory is disabled by design (no write path)")
    sol = mpc_result.get("solver", {})
    chk("optimiser", sol.get("success", False), sol.get("message", "unknown"))
    viol = mpc_result.get("constraint_check", {}).get("end_point_violations", [])
    chk("predicted_envelope", not viol, "; ".join(viol) if viol else "end point within demo envelopes")
    dom = mpc_result.get("constraint_check", {}).get("domain_final", {"in_domain": True})
    chk("model_domain", dom.get("in_domain", False), f"surrogate domain check: {dom}")
    rm = mpc_result.get("model_error_95", {}).get("metallization_pct", 0.0) / 1.96
    loc = (mpc_result.get("local_predictive_sd_end_point") or {}).get("metallization_pct")
    if loc is not None:
        chk("model_fidelity", loc <= surrogate_met_rmse_max_pp,
            f"local surrogate sd (metallization) {loc:.2f} pp at recommended point; global CV RMSE {rm:.2f} pp")
    else:
        chk("model_fidelity", rm <= surrogate_met_rmse_max_pp, f"surrogate CV RMSE (metallization) {rm:.2f} pp")
    if mode in ("SHADOW", "ADVISORY", "SITE_SUPERVISORY", "HISTORICAL_REPLAY"):
        if data_timestamp_utc is None:
            chk("data_freshness", False, "no data timestamp")
        else:
            ts = datetime.fromisoformat(data_timestamp_utc.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            chk("data_freshness", age <= max_data_age_s or mode == "HISTORICAL_REPLAY", f"data age {age:.0f} s")
    else:
        chk("data_freshness", True, "simulation mode (synthetic/offline data)")
    actionable = not reasons
    return {
        "actionable": actionable,
        "status": "RECOMMENDATION_AVAILABLE" if actionable else "ADVISORY_ALARM_NO_RECOMMENDATION",
        "reasons": reasons, "checks": checks,
        "write_authority": "NONE - advisory only; approval records a decision, never an actuator write",
        "label": "SAFE_ADVISORY_ONLY",
    }
