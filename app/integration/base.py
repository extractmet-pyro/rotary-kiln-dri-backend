"""Uniform adapter interface: read_recent(), read_range(), subscribe(), health().

All adapters are READ-ONLY.  None implements a write method; the absence of a
write path is deliberate and tested (tests/integration/test_adapters.py)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd


class DataAdapter(ABC):
    name = "base"
    read_only = True

    @abstractmethod
    def read_recent(self, tags: list[str] | None = None, minutes: float = 60) -> pd.DataFrame: ...

    @abstractmethod
    def read_range(self, start: datetime, end: datetime, tags: list[str] | None = None) -> pd.DataFrame: ...

    def subscribe(self, tags: list[str], callback, interval_s: float = 10.0):
        raise NotImplementedError(f"{self.name}: streaming subscription not available; poll read_recent()")

    @abstractmethod
    def health(self) -> dict: ...


def quality_flags(df: pd.DataFrame, registry: dict, freeze_n: int = 12, z_spike: float = 6.0) -> pd.DataFrame:
    """Raw values are retained; quality flags are produced in parallel columns
    (<tag>__q: OK, MISSING, OUT_OF_RANGE, FROZEN, SPIKE, DUPLICATE_TS)."""
    q = pd.DataFrame(index=df.index)
    dup = df.index.duplicated(keep="first")
    for c in df.columns:
        if c.startswith("_") or c.startswith("label_") or c == "timestamp_utc":
            continue
        s = pd.to_numeric(df[c], errors="coerce")
        flag = pd.Series("OK", index=df.index)
        flag[s.isna()] = "MISSING"
        meta = registry.get(c)
        if meta is not None:
            flag[(s < meta.valid_min) | (s > meta.valid_max)] = "OUT_OF_RANGE"
        frozen = s.diff().abs().rolling(freeze_n).sum() == 0
        flag[frozen & s.notna()] = "FROZEN"
        med = s.rolling(25, center=True, min_periods=5).median()
        mad = (s - med).abs().rolling(25, center=True, min_periods=5).median() * 1.4826 + 1e-9
        flag[((s - med).abs() / mad > z_spike) & (flag == "OK")] = "SPIKE"
        flag[dup] = "DUPLICATE_TS"
        q[c + "__q"] = flag
    return q
