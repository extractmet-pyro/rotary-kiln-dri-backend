"""Historian bulk/replay adapter: replays time-stamped logs with correct causal
ordering (no future rows are released before the replay clock)."""
from __future__ import annotations

import pandas as pd

from app.integration.base import DataAdapter


class ReplayAdapter(DataAdapter):
    name = "historian_replay"

    def __init__(self, df: pd.DataFrame, speed: float = 60.0):
        self.df = df.sort_index(kind="stable")
        self.clock = self.df.index.min()
        self.speed = speed

    def advance(self, minutes: float):
        self.clock = self.clock + pd.Timedelta(minutes=minutes)
        return self.clock

    def read_recent(self, tags=None, minutes=60):
        w = self.df[(self.df.index <= self.clock) & (self.df.index > self.clock - pd.Timedelta(minutes=minutes))]
        return w[tags] if tags else w

    def read_range(self, start, end, tags=None):
        end = min(pd.Timestamp(end), self.clock)
        w = self.df[(self.df.index >= pd.Timestamp(start)) & (self.df.index <= end)]
        return w[tags] if tags else w

    def health(self):
        return {"adapter": self.name, "clock_utc": str(self.clock), "rows_released": int((self.df.index <= self.clock).sum()),
                "read_only": True}
