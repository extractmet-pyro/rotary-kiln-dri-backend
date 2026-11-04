"""Versioned model registry (joblib artifact + metadata + model card).
Preprocessor and model are stored in the same artifact.  Active pointer per
model name allows promotion and rollback."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import joblib

STORE = Path(os.environ.get("MODEL_STORE_DIR", Path(__file__).resolve().parents[2] / "model_store"))


def _dir(name):
    d = STORE / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(name: str, obj, meta: dict) -> str:
    d = _dir(name)
    version = time.strftime("%Y%m%dT%H%M%S") + "-" + hashlib.sha1(json.dumps(meta, sort_keys=True, default=str)
                                                                  .encode()).hexdigest()[:6]
    vd = d / version
    vd.mkdir()
    joblib.dump(obj, vd / "model.joblib")
    meta = {**meta, "name": name, "version": version, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (vd / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
    (vd / "MODEL_CARD.md").write_text(model_card(meta))
    (d / "ACTIVE").write_text(version)
    return version


def load(name: str, version: str | None = None):
    d = STORE / name
    if not d.exists():
        return None, None
    version = version or (d / "ACTIVE").read_text().strip() if (d / "ACTIVE").exists() else None
    if version is None or not (d / version / "model.joblib").exists():
        return None, None
    meta = json.loads((d / version / "meta.json").read_text())
    return joblib.load(d / version / "model.joblib"), meta


def list_models() -> list[dict]:
    out = []
    if not STORE.exists():
        return out
    for d in sorted(STORE.iterdir()):
        if not d.is_dir():
            continue
        active = (d / "ACTIVE").read_text().strip() if (d / "ACTIVE").exists() else None
        for v in sorted(p.name for p in d.iterdir() if p.is_dir()):
            meta = json.loads((d / v / "meta.json").read_text())
            out.append({"name": d.name, "version": v, "active": v == active, "metrics": meta.get("metrics"),
                        "status": meta.get("status"), "created_utc": meta.get("created_utc")})
    return out


def rollback(name: str, version: str) -> bool:
    d = STORE / name
    if not (d / version / "model.joblib").exists():
        return False
    (d / "ACTIVE").write_text(version)
    return True


def model_card(meta: dict) -> str:
    m = meta.get("metrics", {})
    return f"""# Model card - {meta.get('name')} ({meta.get('version')})

* Purpose: {meta.get('purpose', '')}
* Status: {meta.get('status', 'DEMO - trained on SYNTHETIC data; no plant accuracy claimed')}
* Training data: {meta.get('data', '')}
* Split: {meta.get('split', 'chronological')}
* Features: {len(meta.get('features', []))} (see feature contract)
* Seed: {meta.get('seed')}
* Metrics (test, chronological holdout): {json.dumps(m, default=str)}
* Limitations: synthetic benchmark does not demonstrate real-world performance; retrain and
  validate on site data (blocked/out-of-time) before any advisory use.
"""
