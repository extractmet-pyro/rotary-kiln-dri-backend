"""Simulation jobs: submit, poll, results, exports."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select

from app.api.v1.deps import need, principal
from app.core.exceptions import InputValidationError, NotFound
from app.data.database import SessionLocal
from app.data.models import Run
from app.data.repository import audit, unpack
from app.schemas.simulation import CompareRequest, SensitivityRequest, SimulationRequest
from app.services import jobs, reports
from app.services.compute import build_config, input_hash

router = APIRouter(prefix="/api/v1", tags=["simulation"])


def _accepted(rid, cached=False):
    return {"run_id": rid, "status": "succeeded" if cached else "queued", "cached": cached,
            "poll": f"/api/v1/simulations/{rid}"}


@router.post("/simulations", status_code=202)
def submit(req: SimulationRequest, p: dict = Depends(principal)):
    need(p, "simulate")
    if req.mode == "SITE_SUPERVISORY":
        raise InputValidationError("SITE_SUPERVISORY is disabled by design in this service")
    body = req.model_dump()
    cfg = build_config(body)  # validates before queuing
    h = input_hash(body)
    with SessionLocal() as s:
        hit = s.execute(select(Run).where(Run.input_hash == h, Run.status == "succeeded")
                        .order_by(Run.created_utc.desc())).scalars().first()
        if hit:
            return _accepted(hit.id, True)
    rid = jobs.submit("simulation", body, p["sub"], req.scenario_name, h, req.mode, cfg.meta.config_version,
                      req.campaign_id, req.feed_batch_id)
    audit(p["sub"], p["role"], "simulation_submit", {"run_id": rid, "scenario": req.scenario_name})
    return _accepted(rid)


@router.get("/simulations")
def list_runs(limit: int = 50, kind: str | None = None):
    with SessionLocal() as s:
        q = select(Run).order_by(Run.created_utc.desc()).limit(min(limit, 200))
        if kind:
            q = q.where(Run.kind == kind)
        rows = s.execute(q).scalars().all()
        return [{"run_id": r.id, "kind": r.kind, "status": r.status, "scenario_name": r.scenario_name,
                 "created_utc": r.created_utc.isoformat(), "summary": r.summary, "operator": r.operator,
                 "progress": r.progress} for r in rows]


@router.get("/simulations/{rid}")
def status(rid: str):
    with SessionLocal() as s:
        r = s.get(Run, rid)
        if not r:
            raise NotFound(f"run {rid} not found")
        return {"run_id": r.id, "kind": r.kind, "status": r.status, "progress": r.progress, "message": r.message,
                "created_utc": r.created_utc.isoformat(),
                "started_utc": r.started_utc.isoformat() if r.started_utc else None,
                "finished_utc": r.finished_utc.isoformat() if r.finished_utc else None, "summary": r.summary,
                "input_hash": r.input_hash, "mode": r.mode, "plant_config_version": r.plant_config_version,
                "model_version": r.model_version, "operator": r.operator, "request": r.request}


def _result(rid):
    with SessionLocal() as s:
        r = s.get(Run, rid)
        if not r:
            raise NotFound(f"run {rid} not found")
        if r.status != "succeeded":
            raise InputValidationError(f"run {rid} is {r.status}: {r.message}")
        return unpack(r.result_gz)


@router.get("/simulations/{rid}/results")
def results(rid: str):
    res = _result(rid)
    res["run_id"] = rid
    return res


@router.get("/simulations/{rid}/export")
def export(rid: str, format: str = "json"):
    res = _result(rid)
    if format == "csv":
        return Response(reports.to_csv(res), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{rid}_profiles.csv"'})
    if format == "xlsx":
        return Response(reports.to_xlsx(res),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{rid}.xlsx"'})
    if format == "pdf":
        return Response(reports.to_pdf(res), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{rid}_report.pdf"'})
    return res


@router.post("/scenarios/compare", status_code=202)
def compare(req: CompareRequest, p: dict = Depends(principal)):
    need(p, "simulate")
    body = req.model_dump()
    for sc in body["scenarios"]:
        build_config(sc)
    rid = jobs.submit("compare", body, p["sub"], "compare")
    return _accepted(rid)


@router.post("/scenarios/sensitivity")
def sensitivity(req: SensitivityRequest, p: dict = Depends(principal)):
    need(p, "simulate")
    if req.method == "physics":
        rid = jobs.submit("sensitivity", req.model_dump(), p["sub"], "sensitivity")
        return _accepted(rid)
    from app.api.v1 import _shared
    from app.control.reduced_model import INPUTS, OUTPUTS
    sur = _shared.surrogate(req.preset)
    u0 = sur.baseline.copy()
    y0 = sur.predict_dict(u0)
    rows = []
    for j, (name, unit, kind) in enumerate(INPUTS):
        vals = {}
        for sgn in (-1, 1):
            u = u0.copy()
            if name == "pellet_moisture_pct":
                u[j] = u0[j] + sgn * 0.8
            else:
                u[j] = u0[j] * (1 + sgn * req.rel_step)
            vals[sgn] = sur.predict_dict(u)
        rows.append({"factor": name, "unit": unit, "kind": kind, "low": {o: vals[-1][o] for o in req.outputs},
                     "high": {o: vals[1][o] for o in req.outputs}})
    return {"method": "surrogate one-factor-at-a-time (model-projected)", "rel_step": req.rel_step,
            "baseline": {o: y0[o] for o in req.outputs}, "rows": rows,
            "model_error_95": {o: 1.96 * float(sur.loo_rmse[OUTPUTS.index(o)]) for o in req.outputs}}


@router.post("/scenarios/pareto")
def pareto(preset: str = "RK-100TPD", points: int = 12):
    from app.api.v1 import _shared
    from app.control.optimizer import pareto_front
    from app.schemas.plant import preset_config
    sur = _shared.surrogate(preset)
    return pareto_front(sur, preset_config(preset), sur.baseline.copy(), min(points, 20))


@router.get("/scenarios/templates")
def templates():
    from app.services.scenario_manager import TEMPLATES
    return TEMPLATES
