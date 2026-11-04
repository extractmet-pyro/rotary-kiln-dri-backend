"""Hybrid quality prediction (physics + bounded ML-B) with physics fallback."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import _shared
from app.data.fixtures import baseline
from app.ml.features import build_features
from app.ml.predict import predict_metallization
from app.schemas.simulation import QualityRequest

router = APIRouter(prefix="/api/v1", tags=["quality"])


@router.post("/quality/predict")
def predict(req: QualityRequest):
    sur = _shared.surrogate(req.preset)
    u = _shared.u_from_current(sur, req.current)
    phys = sur.predict_dict(u)
    b = baseline(req.preset)
    res_h = b["kpi"]["residence_time_h"] if b else 5.0
    df = _shared.public_history()
    from app.schemas.plant import preset_config
    ref = {t.tube_id: t.flow_nm3h for t in preset_config(req.preset).air.secondary_tubes}
    F = build_features(df, df.index[-1:], res_h, sur, ref)
    row = F.iloc[-1].to_dict()
    ml = predict_metallization(row, row.get("physics_met", phys["metallization_pct"]), req.ml_enabled)
    sd = sur.predict_std(u)[0].tolist() if hasattr(sur, "predict_std") else None
    return {"physics_estimate": phys, "physics_sd": dict(zip(phys.keys(), sd)) if sd else None,
            "hybrid_metallization": ml, "features_at": str(F.index[-1]),
            "labels": {"physics": "PHYSICS-ESTIMATED (surrogate)", "ml": "ML-PREDICTED (synthetic-trained)"},
            "note": "No plant accuracy is claimed; ML trained on synthetic data."}
