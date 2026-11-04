"""ORM tables (schema version 1; see alembic/versions/0001_initial.py)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.data.database import Base


def now():
    return datetime.now(timezone.utc)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scenario_name: Mapped[str] = mapped_column(String(120), default="")
    mode: Mapped[str] = mapped_column(String(30), default="OFFLINE_SIMULATION")
    plant_config_version: Mapped[str] = mapped_column(String(60), default="")
    model_version: Mapped[str] = mapped_column(String(60), default="")
    input_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    campaign_id: Mapped[str] = mapped_column(String(60), default="")
    feed_batch_id: Mapped[str] = mapped_column(String(60), default="")
    operator: Mapped[str] = mapped_column(String(60), default="")
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    result_gz: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    scenario: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(30))
    requested_by: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON)
    gates: Mapped[dict] = mapped_column(JSON)
    verification_run_id: Mapped[str] = mapped_column(String(40), default="")
    decision: Mapped[str] = mapped_column(String(20), default="pending")


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[str] = mapped_column(String(40), index=True)
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    user: Mapped[str] = mapped_column(String(60))
    role: Mapped[str] = mapped_column(String(30))
    decision: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text)
    override_minutes: Mapped[float] = mapped_column(Float, default=0.0)


class AuditEvent(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    user: Mapped[str] = mapped_column(String(60))
    role: Mapped[str] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class PlantConfigVersion(Base):
    __tablename__ = "plant_configs"
    version: Mapped[str] = mapped_column(String(60), primary_key=True)
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    author: Mapped[str] = mapped_column(String(60))
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(Text, default="")


class MaterialLot(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(20))
    lot_id: Mapped[str] = mapped_column(String(60))
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    assay: Mapped[dict] = mapped_column(JSON)
    basis: Mapped[str] = mapped_column(String(40), default="")
    provenance: Mapped[str] = mapped_column(String(40), default="SYNTHETIC-DEMO")


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    category: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(60))
    acknowledged_by: Mapped[str] = mapped_column(String(60), default="")
