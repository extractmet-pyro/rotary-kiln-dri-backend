"""FastAPI application: Rotary-Kiln DRI Digital Twin (simulation + advisory)."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.v1 import admin, alerts, auth, config, health, ml, mpc, plant_data, quality, simulation, states
from app.core.exceptions import TwinError
from app.core.logging import setup
from app.core.security import SECURITY_HEADERS, RateLimiter, principal_from_header
from app.core.settings import settings
from app.data.database import init_db
from app.services import jobs
from app.services import metrics as svc_metrics

log = setup(settings.log_level)
limiter = RateLimiter(settings.rate_limit_per_min)


def _seed_fixtures():
    """Register precomputed baseline results as cached runs (deterministic)."""
    from app.data.database import SessionLocal
    from app.data.fixtures import baseline
    from app.data.models import Run
    from app.data.repository import pack
    from app.schemas.plant import PRESETS
    from app.services.compute import input_hash
    for pr in PRESETS:
        b = baseline(pr)
        if not b:
            continue
        rid = f"fixture-baseline-{pr}"
        with SessionLocal() as s:
            if s.get(Run, rid):
                continue
            req = {"scenario_name": "baseline", "mode": "OFFLINE_SIMULATION", "preset": pr, "feed": {},
                   "disturbances": {}, "overrides": {},
                   "simulation": {"type": "steady", "duration_min": 240, "output_interval_min": 10, "schedule": [],
                                  "fast": False}, "campaign_id": "", "feed_batch_id": "", "plant_config": None,
                   "plant_config_version": None}
            s.add(Run(id=rid, kind="simulation", status="succeeded", progress=1.0, message="precomputed fixture",
                      scenario_name="baseline", input_hash=input_hash(req), request=req, result_gz=pack(b),
                      summary={k: b["kpi"].get(k) for k in ("metallization_pct", "dri_t_h", "coal_kg_per_t_dri",
                                                            "peak_bed_T_C", "exit_gas_T_C")},
                      model_version=b.get("model_version", ""), operator="system"))
            s.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    jobs.mark_interrupted()
    try:
        _seed_fixtures()
    except Exception as e:  # pragma: no cover
        log.warning(f"fixture seeding failed: {e}")
    yield
    jobs.shutdown()


app = FastAPI(title="Rotary-Kiln DRI Digital Twin API", version=health.API_VERSION, lifespan=lifespan,
              description="First-principles + ML + advisory MPC for coal-based rotary-kiln DRI. "
                          "SIMULATION / ADVISORY ONLY - no actuator write path. Extractmet Private Limited.")
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT"], allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def guard(request: Request, call_next):
    rid = uuid.uuid4().hex[:10]
    t0 = time.time()
    cl = request.headers.get("content-length")
    if cl and int(cl) > settings.max_request_bytes:
        return JSONResponse({"error": {"code": "PAYLOAD_TOO_LARGE", "message": "request body too large"}}, 413)
    ip = request.client.host if request.client else "unknown"
    if request.url.path.startswith("/api/") and not limiter.allow(ip):
        return JSONResponse({"error": {"code": "RATE_LIMIT", "message": "too many requests"}}, 429)
    resp = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    resp.headers["X-Request-ID"] = rid
    svc_metrics.hit(request.url.path, resp.status_code)
    logging.getLogger("rk-twin.http").info("request", extra={"request_id": rid, "path": request.url.path,
                                                            "status": resp.status_code,
                                                            "duration_ms": round((time.time() - t0) * 1000, 1)})
    return resp


@app.exception_handler(TwinError)
async def twin_err(request: Request, exc: TwinError):
    return JSONResponse({"error": {"code": exc.code, "message": str(exc)}}, status_code=exc.http_status)


@app.exception_handler(ValidationError)
async def val_err(request: Request, exc: ValidationError):
    return JSONResponse({"error": {"code": "INPUT_VALIDATION", "message": str(exc)}}, status_code=422)


for r in (health, auth, config, plant_data, simulation, states, quality, ml, mpc, alerts, admin):
    app.include_router(r.router)


@app.websocket("/ws/v1/telemetry")
async def telemetry(ws: WebSocket):
    """Rate-limited live DEMO telemetry: replays synthetic history at 1 row/s."""
    token = ws.query_params.get("token")
    try:
        principal_from_header(f"Bearer {token}" if token else None)
    except TwinError:
        await ws.close(code=4401)
        return
    await ws.accept()
    from app.api.v1 import _shared
    df = _shared.public_history()
    cols = ["PELLET_FEED_TPH", "COAL_FEED_TPH", "COAL_INJECTION_TPH", "KILN_RPM", "EXHAUST_TEMP_C",
            "EXHAUST_O2_VOLPCT_DRY", "EXHAUST_CO2_VOLPCT_DRY", "TEMP_SHELL_Z4_C", "TEMP_FREEBOARD_Z4_C",
            "DRI_DISCHARGE_TPH", "WHRB_STEAM_TPH", "KILN_DRIVE_TORQUE", "KILN_DRAFT_PA"]
    i = max(len(df) - 2000, 0)
    try:
        while True:
            row = df.iloc[i % len(df)]
            msg = {"banner": "SYNTHETIC", "replay_timestamp_utc": df.index[i % len(df)].isoformat(),
                   "values": {c: (None if (isinstance(row[c], float) and math.isnan(row[c])) else round(float(row[c]), 3))
                              for c in cols if c in df}}
            await ws.send_text(json.dumps(msg))
            i += 1
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
