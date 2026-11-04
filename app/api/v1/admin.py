"""Administration: RBAC overview, secrets STATUS (never values), retention,
model deployment status, and the (disabled) supervisory-enablement request
with two-person approval recording."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.deps import need, principal
from app.control.safety_gates import SUPERVISORY_ENABLED
from app.core.security import PERMS, USERS
from app.core.settings import settings
from app.data.repository import audit
from app.ml import registry

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
_REQUESTS: dict = {}


@router.get("/status")
def status(p: dict = Depends(principal)):
    return {"roles": {r: sorted(v) for r, v in PERMS.items()}, "demo_users": sorted(USERS),
            "secrets_status": settings.secrets_status(), "demo_public": settings.demo_public,
            "env": settings.app_env, "allowed_origins": settings.allowed_origins,
            "retention_runs": settings.result_retention, "job_workers": settings.max_job_workers,
            "models": registry.list_models(), "supervisory_enabled": SUPERVISORY_ENABLED,
            "database": settings.database_url.split(":")[0], "export_controls": "synthetic data only in public demo"}


@router.post("/supervisory-request")
def supervisory_request(reason: str, p: dict = Depends(principal)):
    need(p, "approve_supervisory")
    key = "site_supervisory"
    approvals = _REQUESTS.setdefault(key, set())
    approvals.add(p["sub"])
    audit(p["sub"], p["role"], "supervisory_request", {"reason": reason, "approvals": sorted(approvals)})
    return {"approvals_recorded": sorted(approvals), "two_person_rule_met": len(approvals) >= 2,
            "enabled": False,
            "message": "SITE_SUPERVISORY cannot be enabled from this cloud service. A separately engineered, "
                       "on-premises approval gateway with independent interlocks and MoC sign-off is required."}
