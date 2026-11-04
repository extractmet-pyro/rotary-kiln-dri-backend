"""Shared API dependencies: principal extraction and permission checks."""
from __future__ import annotations

from fastapi import Header, Request

from app.core.security import principal_from_header, require


def principal(request: Request, authorization: str | None = Header(default=None)) -> dict:
    p = principal_from_header(authorization)
    request.state.user = p["sub"]
    return p


def need(p: dict, perm: str) -> dict:
    require(p, perm)
    return p
