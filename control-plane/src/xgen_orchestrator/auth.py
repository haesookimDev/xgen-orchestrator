"""운영자 인증/RBAC (P0-4, 07-operator-surface.md).

Local admin + JWT, 2-role(viewer/operator), 감사 로그.
- 열림(무인증): /healthz, /v1/login, /v1/enroll(에이전트), /v1/bundles/{id}/blob(에이전트), /ui.
- viewer: 읽기(GET). operator: 변이(POST/PUT: job/bundle/token/node action).
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import os

from fastapi import Header, HTTPException
from jose import jwt

from .config import settings
from .db import models
from .db.session import SessionLocal

_ROLE = {"viewer": 1, "operator": 2}
_TOKEN_TTL = dt.timedelta(hours=12)


def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 100_000)
    return "pbkdf2$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_pw(pw: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(s), 100_000)
        return hmac.compare_digest(dk, base64.b64decode(h))
    except Exception:
        return False


def make_token(username: str, role: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {"sub": username, "role": role, "iat": now, "exp": now + _TOKEN_TTL},
        settings.jwt_secret, algorithm="HS256")


def seed_admin() -> None:
    """운영자가 없으면 env로 초기 admin(operator) 생성."""
    import uuid
    with SessionLocal() as db:
        if db.query(models.Operator).first() is not None:
            return
        db.add(models.Operator(
            id=str(uuid.uuid4()), username=settings.admin_user,
            pw_hash=hash_pw(settings.admin_password), role="operator"))
        db.commit()


def _claims(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return jwt.decode(authorization[7:], settings.jwt_secret, algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=401, detail="invalid or expired token")


def require_viewer(authorization: str = Header(default=None)) -> dict:
    return _claims(authorization)


def require_operator(authorization: str = Header(default=None)) -> dict:
    c = _claims(authorization)
    if _ROLE.get(c.get("role"), 0) < _ROLE["operator"]:
        raise HTTPException(status_code=403, detail="operator role required")
    return c


def make_bundle_token(bundle_id: str) -> str:
    """번들 blob 다운로드용 단기 토큰 (에이전트는 인증 stream으로 URL 수령)."""
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode({"bundle": bundle_id, "exp": now + dt.timedelta(minutes=15)},
                      settings.jwt_secret, algorithm="HS256")


def verify_bundle_token(token: str, bundle_id: str) -> bool:
    try:
        c = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return c.get("bundle") == bundle_id
    except Exception:
        return False


def audit(actor: str, action: str, target: str, detail: dict | None = None) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    with SessionLocal() as db:
        db.add(models.AuditLog(actor=actor, action=action, target=target, detail=detail or {}, at=now))
        db.commit()
