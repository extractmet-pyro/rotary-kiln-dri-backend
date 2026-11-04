"""Plant configuration (validated, versioned) and material assay lots."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.v1.deps import need, principal
from app.core.exceptions import InputValidationError, NotFound
from app.data.database import SessionLocal
from app.data.models import MaterialLot, PlantConfigVersion
from app.data.repository import audit
from app.physics.species import coal_from_assay, pellet_assay_to_species
from app.schemas.plant import PRESETS, PlantConfig, preset_config

router = APIRouter(prefix="/api/v1", tags=["config"])


@router.get("/config/presets")
def presets():
    out = []
    for name, p in PRESETS.items():
        c = preset_config(name)
        out.append({"preset": name, "length_m": c.geometry.length_m, "shell_diameter_m": c.geometry.shell_diameter_m,
                    "pellet_feed_tph": c.pellet.feed_tph, "coal_tph": c.coal.feed_coal_tph + c.coal.injection_coal_tph,
                    "air_tubes": len(c.air.secondary_tubes), "n_cells": c.numerics.n_cells,
                    "nominal_capacity_tpd": int(name.split("-")[1].replace("TPD", ""))})
    return {"presets": out, "note": "illustrative capacity classes - not vendor data"}


@router.get("/config/plant")
def get_config(preset: str = "RK-100TPD", version: str | None = None):
    if version:
        with SessionLocal() as s:
            v = s.get(PlantConfigVersion, version)
            if not v:
                raise NotFound(f"config version {version} not found")
            return {"version": v.version, "config": v.config, "author": v.author, "active": v.active}
    if preset not in PRESETS:
        raise NotFound(f"unknown preset {preset}")
    c = preset_config(preset)
    return {"version": c.meta.config_version, "config": c.model_dump(), "schema": PlantConfig.model_json_schema()}


@router.post("/config/validate")
def validate(cfg: dict):
    try:
        c = PlantConfig.model_validate(cfg)
    except Exception as e:
        raise InputValidationError(str(e)) from e
    msgs = []
    sp, gangue, w = pellet_assay_to_species(c.pellet.assay_dry_wt_pct)
    msgs += w
    for nm, ca in (("feed coal", c.coal.feed_coal), ("injection coal", c.coal.injection_coal)):
        cp = coal_from_assay(ca.proximate_ar_wt_pct, ca.ultimate_daf_wt_pct, ca.ncv_MJ_kg_ar, ca.gcv_MJ_kg_ar)
        msgs += [f"{nm}: {m}" for m in cp.warnings]
    return {"valid": True, "warnings": msgs, "pellet_species_dry": sp}


@router.put("/config/plant")
def put_config(body: dict, p: dict = Depends(principal)):
    need(p, "config_write")
    cfg = body.get("config", body)
    try:
        c = PlantConfig.model_validate(cfg)
    except Exception as e:
        raise InputValidationError(str(e)) from e
    ver = body.get("version") or c.meta.config_version
    with SessionLocal() as s:
        if s.get(PlantConfigVersion, ver):
            raise InputValidationError(f"version {ver} exists; configurations are immutable - use a new version id")
        for old in s.execute(select(PlantConfigVersion).where(PlantConfigVersion.active)).scalars():
            old.active = False
        s.add(PlantConfigVersion(version=ver, author=p["sub"], active=True, config=c.model_dump(),
                                 note=body.get("note", "")))
        s.commit()
    audit(p["sub"], p["role"], "config_put", {"version": ver})
    return {"stored": ver, "active": True}


@router.get("/config/plant/versions")
def versions():
    with SessionLocal() as s:
        rows = s.execute(select(PlantConfigVersion).order_by(PlantConfigVersion.created_utc.desc())).scalars().all()
        return [{"version": r.version, "author": r.author, "active": r.active, "created_utc": r.created_utc.isoformat(),
                 "note": r.note} for r in rows]


@router.get("/materials")
def materials():
    with SessionLocal() as s:
        rows = s.execute(select(MaterialLot).order_by(MaterialLot.created_utc.desc()).limit(200)).scalars().all()
        return [{"id": r.id, "kind": r.kind, "lot_id": r.lot_id, "assay": r.assay, "basis": r.basis,
                 "provenance": r.provenance, "created_utc": r.created_utc.isoformat()} for r in rows]


@router.post("/materials")
def add_material(body: dict, p: dict = Depends(principal)):
    need(p, "config_write")
    kind = body.get("kind")
    if kind not in ("pellet", "coal", "flux"):
        raise InputValidationError("kind must be pellet|coal|flux")
    assay = body.get("assay", {})
    if kind == "pellet":
        pellet_assay_to_species(assay)
        basis = "dry wt %"
    elif kind == "coal":
        coal_from_assay(assay["proximate_ar_wt_pct"], assay["ultimate_daf_wt_pct"], assay.get("ncv_MJ_kg_ar"),
                        assay.get("gcv_MJ_kg_ar"))
        basis = "proximate ar / ultimate daf"
    else:
        basis = "wt %"
    with SessionLocal() as s:
        m = MaterialLot(kind=kind, lot_id=body.get("lot_id", "unnamed"), assay=assay, basis=basis,
                        provenance=body.get("provenance", "MEASURED"))
        s.add(m)
        s.commit()
        mid = m.id
    audit(p["sub"], p["role"], "material_add", {"kind": kind, "lot": body.get("lot_id")})
    return {"id": mid, "basis": basis, "validated": True}
