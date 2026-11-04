"""Liveness/readiness and service meta (no secrets)."""
from __future__ import annotations

import platform

from fastapi import APIRouter
from sqlalchemy import text

from app.control.reduced_model import load_surrogate
from app.core.settings import settings
from app.data.database import engine
from app.physics.postprocess import MODEL_VERSION

router = APIRouter()
API_VERSION = "1.0.0"


@router.get("/health/live", tags=["health"])
def live():
    return {"status": "alive"}


@router.get("/health/ready", tags=["health"])
def ready():
    db_ok = True
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    sur = load_surrogate()
    return {"status": "ready" if db_ok else "degraded", "database": "ok" if db_ok else "unavailable",
            "surrogate": "loaded" if sur else "missing", "mode": settings.default_mode, "env": settings.app_env}


@router.get("/api/v1/meta", tags=["meta"])
def meta():
    return {
        "api_version": API_VERSION, "model_version": MODEL_VERSION, "release_label": "SIMULATOR (synthetic demo)",
        "python": platform.python_version(),
        "disclaimer": ("Simulation and advisory software. Demonstration data are SYNTHETIC. This service has NO write "
                       "path to any PLC/DCS; it is not a safety system and does not replace site alarms, SIS or "
                       "burner management. model_not_validated until site acceptance (gate G11)."),
        "capabilities": ["steady_simulation", "transient_simulation", "scenario_compare", "sensitivity", "pareto",
                         "state_estimation_ekf", "ml_soft_sensor", "ml_residual_correction", "ml_anomaly",
                         "mpc_advisory", "closed_loop_simulation", "reports_pdf_xlsx_csv", "websocket_telemetry"],
        "modes": ["DEMO_SYNTHETIC", "OFFLINE_SIMULATION", "HISTORICAL_REPLAY", "SHADOW", "ADVISORY",
                  "SITE_SUPERVISORY (disabled by design)"],
        "company": "Extractmet Private Limited",
    }
