"""CSV / XLSX importer with tag mapping, unit validation and UTC normalisation."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from app.integration.base import DataAdapter, quality_flags


class FileAdapter(DataAdapter):
    name = "csv_excel"

    def __init__(self, path: str | Path, tag_map: dict | None = None, timestamp_col: str = "timestamp_utc",
                 site_tz: str = "UTC", registry: dict | None = None):
        self.path = Path(path)
        self.tag_map = tag_map or {}
        self.ts = timestamp_col
        self.site_tz = site_tz
        self.registry = registry or {}
        self._df = None

    def load(self) -> pd.DataFrame:
        if self.path.suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(self.path)
        else:
            df = pd.read_csv(self.path)
        df = df.rename(columns=self.tag_map)
        t = pd.to_datetime(df[self.ts], utc=False)
        if t.dt.tz is None:
            t = t.dt.tz_localize(self.site_tz)
        df.index = t.dt.tz_convert("UTC")
        df = df.drop(columns=[self.ts])
        df = df[~df.index.isna()]
        self.out_of_order = int((df.index.to_series().diff().dt.total_seconds() < 0).sum())
        df = df.sort_index(kind="stable")  # causal ordering restored; count reported in health()
        self._df = df
        return df

    def preview(self, n: int = 20) -> dict:
        df = self._df if self._df is not None else self.load()
        q = quality_flags(df.head(500), self.registry)
        unknown = [c for c in df.columns if self.registry and c not in self.registry and not c.startswith("_")
                   and not c.startswith("label_")]
        return {"rows": len(df), "columns": list(df.columns), "head": df.head(n).reset_index().astype(str).to_dict("records"),
                "unmapped_columns": unknown, "out_of_order_rows": self.out_of_order,
                "quality_summary": {c: q[c].value_counts().to_dict() for c in q.columns[:40]}}

    def read_recent(self, tags=None, minutes=60):
        df = self._df if self._df is not None else self.load()
        end = df.index.max()
        out = df[df.index >= end - pd.Timedelta(minutes=minutes)]
        return out[tags] if tags else out

    def read_range(self, start: datetime, end: datetime, tags=None):
        df = self._df if self._df is not None else self.load()
        out = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
        return out[tags] if tags else out

    def health(self):
        return {"adapter": self.name, "path": self.path.name, "exists": self.path.exists(), "read_only": True,
                "out_of_order_rows": getattr(self, "out_of_order", None)}
