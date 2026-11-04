"""Deterministic fixture loading (precomputed SYNTHETIC demo results)."""
from __future__ import annotations

import json
from functools import lru_cache

from app.core.settings import settings


@lru_cache(maxsize=32)
def load_json(name: str):
    p = settings.fixtures_dir / name
    if not p.exists():
        return None
    return json.loads(p.read_text())


def baseline(preset: str):
    return load_json(f"baseline_{preset}.json")
