from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.v1.deps import principal
from app.core.security import PERMS, authenticate
from app.data.repository import audit

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class Login(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: Login):
    r = authenticate(body.username, body.password)
    audit(r["sub"], r["role"], "login", {})
    return {"access_token": r["token"], "token_type": "bearer", "role": r["role"], "user": r["sub"]}


@router.get("/me")
def me(p: dict = Depends(principal)):
    return {"user": p["sub"], "role": p["role"], "permissions": sorted(PERMS[p["role"]])}
