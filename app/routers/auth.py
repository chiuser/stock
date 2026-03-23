import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from pydantic import BaseModel

from db import get_conn

router = APIRouter()
_bearer = HTTPBearer()


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

# ── JWT 配置 ───────────────────────────────────────────────
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_H  = 8   # token 有效期（小时）


def _get_jwt_secret() -> str:
    # 生产和本地都要求显式提供 JWT_SECRET，避免落回弱默认值。
    secret = os.environ.get("JWT_SECRET", "").strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET 未配置",
        )
    return secret


def create_token(user_id: int, username: str, is_admin: bool) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_H)
    payload = {
        "sub": str(user_id),
        "username": username,
        "is_admin": is_admin,
        "exp": expire,
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """解码 JWT，返回 payload。失败时抛出 HTTPException 401。"""
    try:
        return jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _load_user(user_id: int) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, COALESCE(is_admin, FALSE)
                FROM users
                WHERE id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已失效",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 每次请求都回查一次数据库，避免只信任 token 中的历史权限信息。
    return {"sub": str(row[0]), "username": row[1], "is_admin": bool(row[2])}


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    payload = decode_token(creds.credentials)
    return _load_user(int(payload["sub"]))


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    # 后台调度和配置写入都属于高风险操作，必须显式限制为管理员。
    if not user["is_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return user


# ── 请求/响应 Schema ───────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str
    username: str
    is_admin: bool


# ── 路由 ──────────────────────────────────────────────────
@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, password_hash, COALESCE(is_admin, FALSE)
                FROM users
                WHERE username = %s
                """,
                (body.username.strip(),),
            )
            row = cur.fetchone()

    if not row or not _verify_password(body.password, row[2]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    token = create_token(user_id=row[0], username=row[1], is_admin=bool(row[3]))
    return {"token": token, "username": row[1], "is_admin": bool(row[3])}
