"""Service metrics (request counters, job statistics)."""
from __future__ import annotations

import threading
import time
from collections import Counter

from sqlalchemy import func, select

from app.data.database import SessionLocal
from app.data.models import Run

_LOCK = threading.Lock()
REQ = Counter()
START = time.time()


def hit(path: str, status: int):
    with _LOCK:
        REQ[f"{status // 100}xx"] += 1
        REQ["total"] += 1


def snapshot() -> dict:
    with SessionLocal() as s:
        by = dict(s.execute(select(Run.status, func.count()).group_by(Run.status)).all())
        kinds = dict(s.execute(select(Run.kind, func.count()).group_by(Run.kind)).all())
    return {"uptime_s": round(time.time() - START), "requests": dict(REQ), "runs_by_status": by, "runs_by_kind": kinds}
