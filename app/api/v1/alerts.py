"""Alerts/events, diagnostics, metrics and reports.

Alert categories distinguish instrumentation fault, data-quality concern,
process anomaly, quality deviation, optimisation warning and safety-related
OBSERVATION.  Analytic hints are never site safety alarms."""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select

from app.api.v1 import _shared
from app.api.v1.deps import need, principal
from app.data.database import SessionLocal
from app.data.fixtures import baseline, load_json
from app.data.models import Alert, AuditEvent, Decision, Recommendation, Run
from app.integration.base import quality_flags
from app.services import metrics as svc_metrics

router = APIRouter(prefix="/api/v1", tags=["alerts & reports"])
CATS = ["instrumentation_fault", "data_quality", "process_anomaly", "quality_deviation", "optimisation_warning",
        "safety_related_observation"]


def derive_alerts(hours: float = 72.0) -> list[dict]:
    df = _shared.history()
    w = df[df.index > df.index.max() - pd.Timedelta(hours=hours)]
    reg = _shared.registry()
    pub = w[[c for c in w.columns if not c.startswith(("_truth_", "label_"))]]
    q = quality_flags(pub, reg)
    out = []
    for c in q.columns:
        vc = q[c].value_counts()
        tag = c[:-3]
        for flag, cat, sev in (("FROZEN", "instrumentation_fault", "high"), ("SPIKE", "data_quality", "low"),
                               ("OUT_OF_RANGE", "data_quality", "medium")):
            if vc.get(flag, 0) > 0 and not tag.startswith("LAB_"):
                first = q.index[q[c] == flag][0]
                out.append({"ts_utc": first.isoformat(), "category": cat, "severity": sev, "source": tag,
                            "message": f"{tag}: {int(vc[flag])} samples flagged {flag}"})
    z4 = w["TEMP_SHELL_Z4_C"] - 0.5 * (w["TEMP_SHELL_Z3_C"] + w["TEMP_SHELL_Z5_C"])
    if (z4.rolling(12).mean() < z4.median() - 25).any():
        t = z4.index[(z4.rolling(12).mean() < z4.median() - 25).values][0]
        out.append({"ts_utc": t.isoformat(), "category": "process_anomaly", "severity": "medium", "source": "SHELL_Z4",
                    "message": "local shell cooling at zone 4 with torque rise - possible accretion precursor (analytic hint)"})
    lab = w["LAB_METALLIZATION_PCT"].dropna()
    if (lab < 88).any():
        out.append({"ts_utc": lab.index[(lab < 88).values][0].isoformat(), "category": "quality_deviation",
                    "severity": "medium", "source": "LAB_METALLIZATION_PCT",
                    "message": f"lab metallization below 88 % in {(lab < 88).sum()} samples"})
    coal = w["COAL_FEED_TPH"].rolling(24).mean()
    o2 = w["EXHAUST_O2_VOLPCT_DRY"].rolling(24).mean()
    ratio = (coal / (o2 + 1)).dropna()
    if len(ratio) and (ratio > ratio.median() * 1.06).any():
        out.append({"ts_utc": ratio.index[(ratio > ratio.median() * 1.06).values][0].isoformat(),
                    "category": "instrumentation_fault", "severity": "medium", "source": "COAL_FEED_TPH",
                    "message": "coal feeder reading inconsistent with exit O2 trend - suspected feeder drift"})
    with SessionLocal() as s:
        for a in s.execute(select(Alert).order_by(Alert.ts_utc.desc()).limit(100)).scalars():
            out.append({"id": a.id, "ts_utc": a.ts_utc.isoformat(), "category": a.category, "severity": a.severity,
                        "source": a.source, "message": a.message, "acknowledged_by": a.acknowledged_by})
    return sorted(out, key=lambda x: x["ts_utc"], reverse=True)


@router.get("/alerts")
def alerts(hours: float = 72.0):
    return {"alerts": derive_alerts(hours), "categories": CATS,
            "disclaimer": "Analytic hints only. Site alarms, SIS and gas detection remain authoritative.",
            "banner": "derived from SYNTHETIC history"}


@router.post("/alerts/{aid}/ack")
def ack(aid: int, p: dict = Depends(principal)):
    need(p, "decide")
    with SessionLocal() as s:
        a = s.get(Alert, aid)
        if a:
            a.acknowledged_by = p["sub"]
            s.commit()
    return {"acknowledged": bool(a)}


@router.get("/metrics")
def metrics():
    return svc_metrics.snapshot()


@router.get("/diagnostics")
def diagnostics(preset: str = "RK-100TPD", hours: float = 96.0):
    df = _shared.history()
    w = df[df.index > df.index.max() - pd.Timedelta(hours=hours)].iloc[::3]
    b = baseline(preset)
    shell = {f"Z{i}": w[f"TEMP_SHELL_Z{i}_C"].round(1).tolist() for i in range(1, 7)}
    anomaly = load_json("ml_report_RK-100TPD.json")
    return {"banner": "SYNTHETIC", "t": [t.isoformat() for t in w.index], "shell_zones": shell,
            "torque": w["KILN_DRIVE_TORQUE"].round(2).tolist(),
            "draft": w["KILN_DRAFT_PA"].round(1).tolist(),
            "accretion_profile": b["accretion"] if b else None,
            "shell_profile_model": {"z_m": b["profiles"]["z_m"], "T_shell_C": b["profiles"]["T_shell_C"],
                                    "flux_kW_m2": b["profiles"]["shell_heat_flux_kW_m2"]} if b else None,
            "anomaly_timeline": anomaly["anomaly"]["timeline"] if anomaly else None,
            "anomaly_metrics": {k: v for k, v in (anomaly["anomaly"] if anomaly else {}).items() if k != "timeline"},
            "air_leak_hint": "compare exit O2 + N2-balance-derived air with metered air; >5 % excess suggests ingress",
            "last_calibration": {"status": "NOT CALIBRATED (synthetic demo)", "date": None}}


@router.get("/reports/shift")
def shift_report(run_id: str | None = None, preset: str = "RK-100TPD"):
    from app.data.repository import unpack
    from app.services.reports import to_pdf
    res = None
    if run_id:
        with SessionLocal() as s:
            r = s.get(Run, run_id)
            res = unpack(r.result_gz) if r and r.result_gz else None
    res = res or baseline(preset)
    return Response(to_pdf(res, "Shift / scenario report - rotary-kiln DRI twin"), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="shift_report.pdf"'})


@router.get("/reports/audit")
def audit_export(format: str = "json", p: dict = Depends(principal)):
    need(p, "read")
    with SessionLocal() as s:
        ev = [{"ts_utc": a.ts_utc.isoformat(), "user": a.user, "role": a.role, "action": a.action, "detail": a.detail}
              for a in s.execute(select(AuditEvent).order_by(AuditEvent.ts_utc.desc()).limit(2000)).scalars()]
        dec = [{"recommendation_id": d.recommendation_id, "user": d.user, "role": d.role, "decision": d.decision,
                "note": d.note, "ts_utc": d.created_utc.isoformat()}
               for d in s.execute(select(Decision).order_by(Decision.created_utc.desc()).limit(1000)).scalars()]
        recs = s.execute(select(Recommendation.id)).scalars().all()
    if format == "csv":
        buf = io.StringIO()
        pd.DataFrame(ev).to_csv(buf, index=False)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="audit.csv"'})
    return {"events": ev, "decisions": dec, "n_recommendations": len(recs)}


@router.get("/reports/baseline/{preset}")
def baseline_result(preset: str):
    b = baseline(preset)
    return b if b else {"error": "no fixture"}


@router.get("/reports/transient-demo")
def transient_demo():
    return load_json("transient_demo_RK-100TPD.json") or {"error": "no fixture"}


@router.get("/docs/{name}")
def docs(name: str):
    from app.core.settings import settings
    allowed = {p.stem: p for p in settings.docs_dir.glob("*.md")}
    if name not in allowed:
        return {"available": sorted(allowed)}
    return Response(allowed[name].read_text(), media_type="text/markdown")


_ = np
