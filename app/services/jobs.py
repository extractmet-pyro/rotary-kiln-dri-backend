"""Persistence-backed background jobs.

Compute runs in a separate *spawned* worker process (never in API worker
threads).  Job state, progress and results live in the database, so a restart
or a second replica sees the same truth; jobs interrupted by a restart are
marked INTERRUPTED (never silently re-run)."""
from __future__ import annotations

import multiprocessing as mp
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.settings import settings
from app.data.database import SessionLocal
from app.data.models import Run
from app.data.repository import enforce_retention, new_id, pack

_POOL: ProcessPoolExecutor | None = None


def pool() -> ProcessPoolExecutor:
    global _POOL
    if _POOL is None:
        _POOL = ProcessPoolExecutor(max_workers=max(settings.max_job_workers, 1), mp_context=mp.get_context("spawn"))
    return _POOL


def _summary(kind: str, res: dict) -> dict:
    k = res.get("kpi") if isinstance(res, dict) else None
    if k:
        keys = ["metallization_pct", "dri_t_h", "coal_kg_per_t_dri", "peak_bed_T_C", "exit_gas_T_C",
                "coal_energy_GJ_per_t_dri", "accretion_risk_max", "residence_time_h"]
        return {x: k.get(x) for x in keys}
    return {"kind": kind}


def _worker(kind: str, run_id: str, request: dict, db_url: str) -> str:
    """Executed in the child process."""
    from sqlalchemy.orm import sessionmaker

    from app.data.database import make_engine
    eng = make_engine(db_url)
    S = sessionmaker(bind=eng, expire_on_commit=False)
    from app.services.compute import JOBS
    last = [0.0]

    def report(frac, msg=""):
        now = time.time()
        if now - last[0] < 1.0 and frac < 1.0:
            return
        last[0] = now
        with S() as s:
            r = s.get(Run, run_id)
            if r:
                r.progress = float(min(max(frac, 0.0), 1.0))
                r.message = str(msg)[:500]
                s.commit()
    with S() as s:
        r = s.get(Run, run_id)
        r.status, r.started_utc = "running", datetime.now(timezone.utc)
        s.commit()
    try:
        res = JOBS[kind](request, report)
        with S() as s:
            r = s.get(Run, run_id)
            r.status, r.progress, r.message = "succeeded", 1.0, "completed"
            r.result_gz = pack(res)
            r.summary = _summary(kind, res)
            r.model_version = res.get("model_version", "") if isinstance(res, dict) else ""
            r.finished_utc = datetime.now(timezone.utc)
            s.commit()
        return "succeeded"
    except Exception as e:  # recorded, never hidden
        with S() as s:
            r = s.get(Run, run_id)
            r.status = "failed"
            r.message = f"{type(e).__name__}: {e}"[:1000]
            r.summary = {"error": str(e), "trace": traceback.format_exc()[-1500:]}
            r.finished_utc = datetime.now(timezone.utc)
            s.commit()
        return "failed"


def submit(kind: str, request: dict, user: str = "anonymous", scenario_name: str = "", input_hash: str = "",
           mode: str = "OFFLINE_SIMULATION", plant_config_version: str = "", campaign_id: str = "",
           feed_batch_id: str = "") -> str:
    rid = new_id(kind[:4])
    with SessionLocal() as s:
        s.add(Run(id=rid, kind=kind, status="queued", request=request, operator=user, scenario_name=scenario_name,
                  input_hash=input_hash, mode=mode, plant_config_version=plant_config_version, campaign_id=campaign_id,
                  feed_batch_id=feed_batch_id))
        s.commit()
    pool().submit(_worker, kind, rid, request, settings.database_url)
    enforce_retention(settings.result_retention)
    return rid


def mark_interrupted():
    with SessionLocal() as s:
        for r in s.execute(select(Run).where(Run.status.in_(["queued", "running"]))).scalars():
            r.status = "interrupted"
            r.message = "service restarted while job was pending/running; resubmit"
        s.commit()


def shutdown():
    global _POOL
    if _POOL is not None:
        _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = None
