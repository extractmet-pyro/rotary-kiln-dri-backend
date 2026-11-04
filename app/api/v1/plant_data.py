"""Tag metadata, history (with quality flags) and file ingestion preview."""
from __future__ import annotations

import tempfile
from dataclasses import asdict
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, UploadFile

from app.api.v1 import _shared
from app.api.v1.deps import need, principal
from app.core.exceptions import InputValidationError
from app.integration.base import quality_flags
from app.integration.csv_excel import FileAdapter

router = APIRouter(prefix="/api/v1", tags=["plant data"])


@router.get("/tags")
def tags(preset: str = "RK-100TPD"):
    reg = _shared.registry(preset)
    return {"tags": [asdict(t) for t in reg.values()], "count": len(reg),
            "note": "logical tag identifiers (examples) - map to site tags during commissioning"}


@router.get("/tags/history")
def history(tags: str = "EXHAUST_TEMP_C,TEMP_SHELL_Z4_C,LAB_METALLIZATION_PCT", hours: float = 48.0,
            step: int = 1, end_offset_h: float = 0.0):
    df = _shared.public_history()
    want = [t for t in tags.split(",") if t in df.columns]
    if not want:
        raise InputValidationError("no known tags requested")
    end = df.index.max() - pd.Timedelta(hours=end_offset_h)
    w = df.loc[(df.index > end - pd.Timedelta(hours=min(hours, 24 * 14))) & (df.index <= end), want].iloc[::max(step, 1)]
    q = quality_flags(w, _shared.registry())
    return {"banner": "SYNTHETIC DEMONSTRATION DATA - NOT PLANT MEASUREMENTS", "timestamps_utc": [t.isoformat() for t in w.index],
            "series": {c: [None if pd.isna(v) else round(float(v), 4) for v in w[c]] for c in want},
            "quality": {c: q[c + "__q"].tolist() for c in want if c + "__q" in q},
            "units": {c: _shared.registry()[c].engineering_unit for c in want if c in _shared.registry()}}


@router.post("/ingestion/preview")
async def ingest_preview(file: UploadFile = File(...), timestamp_col: str = "timestamp_utc", site_tz: str = "UTC",
                         p: dict = Depends(principal)):
    need(p, "ingest")
    suffix = Path(file.filename or "x.csv").suffix.lower()
    if suffix not in (".csv", ".xlsx"):
        raise InputValidationError("only .csv and .xlsx are accepted")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise InputValidationError("file too large for preview (8 MB)")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        fa = FileAdapter(tmp.name, timestamp_col=timestamp_col, site_tz=site_tz, registry=_shared.registry())
        fa.load()
        return fa.preview()


@router.get("/ingestion/sources")
def sources():
    return {"sources": [
        {"id": "synthetic", "status": "active", "read_only": True, "note": "deterministic synthetic history"},
        {"id": "csv_excel", "status": "available", "read_only": True},
        {"id": "historian_replay", "status": "available", "read_only": True},
        {"id": "rest_push", "status": "available", "read_only": True},
        {"id": "opcua_reader", "status": "UNIMPLEMENTED (on-prem connector)", "read_only": True},
        {"id": "mqtt_reader", "status": "UNIMPLEMENTED (on-prem connector)", "read_only": True}],
        "clock_offsets_s": {"DCS": 0.0, "ANALYSER": 90.0, "LIMS": 5400.0, "IR-SCANNER": 10.0}}
