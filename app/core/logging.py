"""Structured JSON logging (no feedstock/plant secrets in logs)."""
from __future__ import annotations

import json
import logging
import sys
import time


class JsonFormatter(logging.Formatter):
    def format(self, record):
        d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)), "level": record.levelname,
             "logger": record.name, "msg": record.getMessage()}
        for k in ("request_id", "path", "status", "duration_ms", "user", "run_id"):
            if hasattr(record, k):
                d[k] = getattr(record, k)
        return json.dumps(d)


def setup(level="INFO"):
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [h]
    root.setLevel(level)
    return logging.getLogger("rk-twin")
