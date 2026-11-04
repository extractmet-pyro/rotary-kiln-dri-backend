"""ML training (restricted), registry, last training report."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.deps import need, principal
from app.core.exceptions import NotFound
from app.data.fixtures import load_json
from app.ml import registry
from app.schemas.simulation import TrainRequest
from app.services import jobs

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])


@router.post("/train", status_code=202)
def train(req: TrainRequest, p: dict = Depends(principal)):
    need(p, "ml_train")
    rid = jobs.submit("ml_train", req.model_dump(), p["sub"], "ml_train")
    return {"run_id": rid, "status": "queued", "poll": f"/api/v1/simulations/{rid}"}


@router.get("/models")
def models():
    return {"models": registry.list_models(), "store": str(registry.STORE.name)}


@router.get("/report")
def report():
    r = load_json("ml_report_RK-100TPD.json")
    if r is None:
        raise NotFound("no training report fixture; POST /api/v1/ml/train")
    return r


@router.post("/rollback")
def rollback(name: str, version: str, p: dict = Depends(principal)):
    need(p, "ml_train")
    return {"rolled_back": registry.rollback(name, version)}
