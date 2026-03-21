import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
import bcrypt
from jose import jwt

from db import get_conn

router = APIRouter()


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

# ── JWT 配置 ───────────────────────────────────────────────
# 可通过环境变量 JWT_SECRET 覆盖
JWT_SECRET    = os.environ.get("JWT_SECRET", "change-me-in-production-please-use-env")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_H  = 8   # token 有效期（小时）


def create_token(user_id: int, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_H)
    payload = {"sub": str(user_id), "username": username, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """解码 JWT，返回 payload。失败时抛出 HTTPException 401。"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── 请求/响应 Schema ───────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str
    username: str


# ── 路由 ──────────────────────────────────────────────────
@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, password_hash FROM users WHERE username = %s",
                (body.username.strip(),),
            )
            row = cur.fetchone()

    if not row or not _verify_password(body.password, row[2]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    token = create_token(user_id=row[0], username=row[1])
    return {"token": token, "username": row[1]}
