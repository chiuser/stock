"""Environment-based admin login for the camera console.

A single admin account is configured through environment variables, which keeps
local development and the remote web service aligned without extra state.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

router = APIRouter()
_bearer = HTTPBearer()
TOKEN_EXPIRE_SECONDS = 8 * 60 * 60


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str
    username: str
    is_admin: bool


def _admin_username() -> str:
    return os.environ.get("CAMERA_ADMIN_USERNAME", "admin").strip() or "admin"


def _admin_password() -> str:
    return os.environ.get("CAMERA_ADMIN_PASSWORD", "").strip()


def _constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _token_secret() -> str:
    # Keep JWT_SECRET compatibility because earlier deployments already used it.
    secret = (
        os.environ.get("CAMERA_SESSION_SECRET", "").strip()
        or os.environ.get("JWT_SECRET", "").strip()
    )
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CAMERA_SESSION_SECRET 或 JWT_SECRET 未配置",
        )
    return secret


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload_part: str) -> str:
    digest = hmac.new(
        _token_secret().encode(),
        payload_part.encode(),
        hashlib.sha256,
    ).digest()
    return _b64url_encode(digest)


def create_token(username: str) -> str:
    payload = {
        "sub": "camera-admin",
        "username": username,
        "is_admin": True,
        "exp": int(time.time()) + TOKEN_EXPIRE_SECONDS,
    }
    payload_part = _b64url_encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    )
    return f"{payload_part}.{_sign(payload_part)}"


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload_part, signature = token.split(".", 1)
    except ValueError as exc:
        raise _invalid_token() from exc

    expected_signature = _sign(payload_part)
    if not hmac.compare_digest(signature, expected_signature):
        raise _invalid_token()

    try:
        payload = json.loads(_b64url_decode(payload_part))
    except (ValueError, json.JSONDecodeError) as exc:
        raise _invalid_token() from exc

    if int(payload.get("exp", 0)) < int(time.time()):
        raise _invalid_token()
    if payload.get("sub") != "camera-admin" or not payload.get("is_admin"):
        raise _invalid_token()
    if payload.get("username") != _admin_username():
        raise _invalid_token()
    return payload


def _invalid_token() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token 无效或已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict[str, Any]:
    return decode_token(creds.credentials)


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return user


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest):
    expected_username = _admin_username()
    expected_password = _admin_password()
    if not expected_password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CAMERA_ADMIN_PASSWORD 未配置",
        )

    username = body.username.strip()
    if not (
        _constant_time_equal(username, expected_username)
        and _constant_time_equal(body.password, expected_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    return {
        "token": create_token(expected_username),
        "username": expected_username,
        "is_admin": True,
    }
