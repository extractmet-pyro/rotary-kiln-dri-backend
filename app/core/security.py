"""Authentication (HMAC-signed bearer tokens), server-enforced RBAC, rate limiting.

Demo users exist only when DEMO_USER_PASSWORD is set (or in APP_ENV=demo with a
documented default that MUST be changed).  For site deployments replace
`authenticate` with the plant SSO/OIDC provider (see DEPLOYMENT_GUIDE.md)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from collections import defaultdict, deque

from app.core.exceptions import AuthError, PermissionDenied
from app.core.settings import settings

ROLES = ["viewer", "operator", "process_engineer", "metallurgist", "data_scientist", "approver", "administrator",
         "auditor"]
PERMS = {
    "viewer": {"read", "simulate"},
    "operator": {"read", "simulate", "recommend", "decide"},
    "process_engineer": {"read", "simulate", "recommend", "decide", "config_write", "calibrate", "ingest"},
    "metallurgist": {"read", "simulate", "recommend", "quality"},
    "data_scientist": {"read", "simulate", "ml_train", "ingest"},
    "approver": {"read", "simulate", "recommend", "decide", "approve_supervisory"},
    "administrator": {"read", "simulate", "recommend", "decide", "config_write", "calibrate", "ml_train", "ingest",
                      "admin", "audit_read", "approve_supervisory"},
    "auditor": {"read", "audit_read"},
}
ANON = {"sub": "anonymous", "role": "viewer"}


def _pw_hash(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()


def _users():
    pw = settings.demo_password or ("demo-change-me" if settings.app_env == "demo" else None)
    if not pw:
        return {}
    users = {}
    for r in ROLES:
        salt = f"rk-{r}"
        users[f"demo_{r}"] = {"role": r, "salt": salt, "hash": _pw_hash(pw, salt)}
    return users


USERS = _users()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(sub: str, role: str, ttl_s: int = 8 * 3600) -> str:
    payload = _b64(json.dumps({"sub": sub, "role": role, "exp": int(time.time()) + ttl_s}).encode())
    sig = _b64(hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(tok: str) -> dict:
    try:
        payload, sig = tok.split(".")
    except ValueError as e:
        raise AuthError("malformed token") from e
    good = _b64(hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(good, sig):
        raise AuthError("invalid token signature")
    d = json.loads(_unb64(payload))
    if d["exp"] < time.time():
        raise AuthError("token expired")
    if d.get("role") not in ROLES:
        raise AuthError("unknown role")
    return d


def authenticate(username: str, password: str) -> dict:
    u = USERS.get(username)
    if not u or not hmac.compare_digest(u["hash"], _pw_hash(password, u["salt"])):
        raise AuthError("invalid credentials")
    return {"sub": username, "role": u["role"], "token": issue_token(username, u["role"])}


def principal_from_header(auth: str | None) -> dict:
    if auth and auth.lower().startswith("bearer "):
        return verify_token(auth.split(" ", 1)[1].strip())
    if settings.demo_public:
        return dict(ANON)
    raise AuthError("authentication required")


def require(principal: dict, perm: str):
    if perm not in PERMS.get(principal.get("role"), set()):
        raise PermissionDenied(f"role '{principal.get('role')}' lacks permission '{perm}'")


class RateLimiter:
    """In-memory sliding window per client (single-instance demo; use a shared
    store such as Redis behind a load balancer)."""

    def __init__(self, per_min: int):
        self.per_min = per_min
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and q[0] < now - 60:
                q.popleft()
            if len(q) >= self.per_min:
                return False
            q.append(now)
            return True


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}
