"""Validated REST push/pull adapter (site gateway -> twin).  Pushed batches are
validated against the tag registry; raw values and quality flags are kept
separately.  This adapter only RECEIVES data."""
from __future__ import annotations

import pandas as pd

from app.integration.base import DataAdapter, quality_flags


class RestPushAdapter(DataAdapter):
    name = "rest_push"

    def __init__(self, registry: dict, max_rows: int = 50000):
        self.registry = registry
        self.max_rows = max_rows
        self.df = pd.DataFrame()
        self.rejected = 0

    def push(self, records: list[dict]) -> dict:
        df = pd.DataFrame(records)
        if "timestamp_utc" not in df:
            raise ValueError("records require timestamp_utc")
        df.index = pd.to_datetime(df.pop("timestamp_utc"), utc=True)
        unknown = [c for c in df.columns if c not in self.registry]
        df = df.drop(columns=unknown)
        self.rejected += len(unknown)
        self.df = pd.concat([self.df, df]).sort_index(kind="stable").iloc[-self.max_rows:]
        q = quality_flags(df, self.registry)
        return {"accepted_rows": len(df), "rejected_columns": unknown,
                "quality": {c: q[c].value_counts().to_dict() for c in q.columns}}

    def read_recent(self, tags=None, minutes=60):
        if self.df.empty:
            return self.df
        w = self.df[self.df.index >= self.df.index.max() - pd.Timedelta(minutes=minutes)]
        return w[tags] if tags else w

    def read_range(self, start, end, tags=None):
        w = self.df[(self.df.index >= pd.Timestamp(start)) & (self.df.index <= pd.Timestamp(end))]
        return w[tags] if tags else w

    def health(self):
        return {"adapter": self.name, "rows": len(self.df), "rejected_columns_total": self.rejected, "read_only": True}
