import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from db import get_conn
from app.routers.auth import decode_token

router = APIRouter()
_bearer = HTTPBearer()


def get_current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    return decode_token(creds.credentials)


# ── Schema ─────────────────────────────────────────────────
class AddStockRequest(BaseModel):
    ts_code: str


# ── 路由 ──────────────────────────────────────────────────
@router.get("/portfolio")
def list_portfolio(user: dict = Depends(get_current_user)):
    user_id = int(user["sub"])

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    up.ts_code,
                    sb.name,
                    sd.close,
                    sd.pct_chg,
                    sd.vol,
                    sdb.turnover_rate,
                    up.added_at
                FROM user_portfolio up
                LEFT JOIN stock_basic sb ON sb.ts_code = up.ts_code
                LEFT JOIN LATERAL (
                    SELECT close, pct_chg, vol
                    FROM stock_daily
                    WHERE ts_code = up.ts_code
                    ORDER BY trade_date DESC
                    LIMIT 1
                ) sd ON true
                LEFT JOIN LATERAL (
                    SELECT turnover_rate
                    FROM stock_daily_basic
                    WHERE ts_code = up.ts_code
                    ORDER BY trade_date DESC
                    LIMIT 1
                ) sdb ON true
                WHERE up.user_id = %s
                ORDER BY up.added_at
            """, (user_id,))
            rows = cur.fetchall()

    result = []
    for i, row in enumerate(rows, start=1):
        ts_code, name, close, pct_chg, vol, turnover_rate, added_at = row
        result.append({
            "idx":          i,
            "ts_code":      ts_code,
            "name":         name or ts_code,
            "close":        float(close)        if close        is not None else None,
            "pct_chg":      float(pct_chg)      if pct_chg      is not None else None,
            "vol":          float(vol)          if vol          is not None else None,
            "turnover_rate": float(turnover_rate) if turnover_rate is not None else None,
        })
    return result


@router.post("/portfolio", status_code=201)
def add_stock(body: AddStockRequest, user: dict = Depends(get_current_user)):
    user_id = int(user["sub"])
    ts_code = body.ts_code.strip().upper()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # 验证股票存在
            cur.execute("SELECT name FROM stock_basic WHERE ts_code = %s", (ts_code,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"股票代码 {ts_code} 不存在",
                )
            name = row[0]

            try:
                cur.execute(
                    "INSERT INTO user_portfolio (user_id, ts_code) VALUES (%s, %s)",
                    (user_id, ts_code),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"{ts_code} 已在持仓股中",
                )

    return {"ts_code": ts_code, "name": name}


@router.delete("/portfolio/{ts_code}", status_code=204)
def remove_stock(ts_code: str, user: dict = Depends(get_current_user)):
    user_id = int(user["sub"])
    ts_code = ts_code.strip().upper()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_portfolio WHERE user_id = %s AND ts_code = %s",
                (user_id, ts_code),
            )
            conn.commit()
