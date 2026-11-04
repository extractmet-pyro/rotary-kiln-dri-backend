"""MPC advisory: recommend, list, audit, decide (no actuator writes), closed-loop sim."""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.v1 import _shared
from app.api.v1.deps import need, principal
from app.control.advisory import rank_scenarios, summarise_moves, validate_decision
from app.control.constraints import MPCSettings
from app.control.mpc import SupervisoryMPC
from app.control.safety_gates import evaluate_gates
from app.core.exceptions import InputValidationError, NotFound
from app.data.database import SessionLocal
from app.data.fixtures import load_json
from app.data.models import Decision, Recommendation
from app.data.repository import audit, new_id
from app.schemas.plant import preset_config
from app.schemas.simulation import ClosedLoopRequest, DecisionRequest, MPCRequest
from app.services import jobs

router = APIRouter(prefix="/api/v1/mpc", tags=["mpc"])


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    return o


@router.post("/recommend")
def recommend(req: MPCRequest, p: dict = Depends(principal)):
    need(p, "simulate")
    if req.mode == "SITE_SUPERVISORY":
        raise InputValidationError("SITE_SUPERVISORY is disabled by design; use ADVISORY")
    sur, dyn = _shared.surrogate(req.preset), _shared.dynamics(req.preset)
    cfg = preset_config(req.preset)
    u = _shared.u_from_current(sur, req.current)
    st = MPCSettings(interval_min=req.interval_min, Np=req.horizon_steps, Nc=req.control_steps, weights=req.weights,
                     scenario=req.scenario)
    main = SupervisoryMPC(sur, dyn, cfg, st).recommend(u, req.measurements or None, req.scenario, req.locked,
                                                     mv_overrides=req.mv_overrides or None)
    gates = evaluate_gates(req.mode, main, req.data_timestamp_utc)
    ranking = []
    if req.rank_all:
        ranking = [{k: v for k, v in r.items() if k != "result"} for r in
                   rank_scenarios(sur, dyn, cfg, u, req.measurements or None, locked=req.locked, mode=req.mode,
                                  data_ts=req.data_timestamp_utc)]
    rid = new_id("rec")
    ver = ""
    if req.verify_with_physics and gates["actionable"]:
        ver = jobs.submit("verify", {"preset": req.preset, "u": [m["recommended"] for m in main["moves"]] +
                                     list(map(float, u[5:])), "surrogate_end_point": main["end_point"]}, p["sub"],
                          "mpc_verify")
    payload = _clean({**main, "ranking": ranking})
    with SessionLocal() as s:
        s.add(Recommendation(id=rid, scenario=req.scenario, status=gates["status"], mode=req.mode,
                             requested_by=p["sub"], payload=payload, gates=_clean(gates), verification_run_id=ver))
        s.commit()
    audit(p["sub"], p["role"], "mpc_recommend", {"id": rid, "scenario": req.scenario, "actionable": gates["actionable"]})
    return {"recommendation_id": rid, "gates": _clean(gates), "verification_run_id": ver or None,
            "apply_label": "Approve recommendation (advisory record only - NO actuator write)",
            "hardware_notice": "On-premises hardware permissions are NOT enabled by any browser button.",
            **payload}


@router.get("/recommendations")
def list_recs(limit: int = 30):
    with SessionLocal() as s:
        rows = s.execute(select(Recommendation).order_by(Recommendation.created_utc.desc()).limit(limit)).scalars().all()
        return [{"id": r.id, "created_utc": r.created_utc.isoformat(), "scenario": r.scenario, "status": r.status,
                 "decision": r.decision, "requested_by": r.requested_by,
                 "moves": summarise_moves(r.payload.get("moves", []))} for r in rows]


@router.get("/recommendations/{rid}")
def get_rec(rid: str):
    with SessionLocal() as s:
        r = s.get(Recommendation, rid)
        if not r:
            raise NotFound(f"recommendation {rid} not found")
        ds = s.execute(select(Decision).where(Decision.recommendation_id == rid)).scalars().all()
        return {"id": r.id, "created_utc": r.created_utc.isoformat(), "scenario": r.scenario, "status": r.status,
                "mode": r.mode, "requested_by": r.requested_by, "payload": r.payload, "gates": r.gates,
                "verification_run_id": r.verification_run_id, "decision": r.decision,
                "decisions": [{"user": d.user, "role": d.role, "decision": d.decision, "note": d.note,
                               "created_utc": d.created_utc.isoformat(), "override_minutes": d.override_minutes}
                              for d in ds]}


@router.post("/recommendations/{rid}/decision")
def decide(rid: str, body: DecisionRequest, p: dict = Depends(principal)):
    need(p, "decide")
    with SessionLocal() as s:
        r = s.get(Recommendation, rid)
        if not r:
            raise NotFound(f"recommendation {rid} not found")
        errs = validate_decision(body.decision, body.note, p["role"], r.status)
        if errs:
            raise InputValidationError("; ".join(errs))
        s.add(Decision(recommendation_id=rid, user=p["sub"], role=p["role"], decision=body.decision, note=body.note,
                       override_minutes=body.override_minutes))
        r.decision = body.decision
        s.commit()
    audit(p["sub"], p["role"], "mpc_decision", {"id": rid, "decision": body.decision})
    return {"recorded": True, "decision": body.decision, "actuator_write": False,
            "message": "Decision recorded in the audit trail. No setpoint was sent to any equipment."}


@router.post("/closed-loop", status_code=202)
def closed(req: ClosedLoopRequest, p: dict = Depends(principal)):
    need(p, "simulate")
    rid = jobs.submit("closed_loop", req.model_dump(), p["sub"], "closed_loop")
    return {"run_id": rid, "status": "queued", "poll": f"/api/v1/simulations/{rid}"}


@router.get("/closed-loop/demo")
def closed_demo():
    r = load_json("closed_loop_RK-100TPD.json")
    if r is None:
        raise NotFound("closed-loop fixture missing")
    return r
