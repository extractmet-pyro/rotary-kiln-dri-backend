"""Persistence helpers (gzip JSON results, retention)."""
from __future__ import annotations

import gzip
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.data.database import SessionLocal
from app.data.models import AuditEvent, Run


def new_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


def pack(obj) -> bytes:
    return gzip.compress(json.dumps(obj, default=float, allow_nan=False if False else True).encode(), 6)


def unpack(b: bytes):
    return json.loads(gzip.decompress(b).decode()) if b else None


def audit(user: str, role: str, action: str, detail: dict | None = None):
    with SessionLocal() as s:
        s.add(AuditEvent(user=user, role=role, action=action, detail=detail or {}))
        s.commit()


def enforce_retention(limit: int):
    with SessionLocal() as s:
        ids = s.execute(select(Run.id).order_by(Run.created_utc.desc()).offset(limit)).scalars().all()
        for i in ids:
            r = s.get(Run, i)
            if r and not r.id.startswith("fixture-"):
                s.delete(r)
        s.commit()
