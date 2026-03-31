import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from db import get_conn, get_gs_conn
from app.routers.auth import get_current_user

router = APIRouter()


class AddStockRequest(BaseModel):
    ts_code: str


def _f(v):
    return float(v) if v is not None else None


@router.get("/portfolio")
def list_portfolio(user: dict = Depends(get_current_user)):
    user_id = int(user["sub"])

    # ── Step 1: 从 stock DB 取持仓列表 ──────────────────────
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ts_code, added_at FROM user_portfolio "
                "WHERE user_id = %s ORDER BY added_at",
                (user_id,),
            )
            portfolio_rows = cur.fetchall()

    if not portfolio_rows:
        return []

    ts_codes = [r[0] for r in portfolio_rows]

    # ── Step 2: 从 goldenshare 取市场数据 ────────────────────
    with get_gs_conn() as conn:
        with conn.cursor() as cur:
            # 证券名称
            cur.execute(
                "SELECT ts_code, name FROM core.security WHERE ts_code = ANY(%s)",
                (ts_codes,),
            )
            name_map = {r[0]: r[1] for r in cur.fetchall()}

            # 最新日线（close / pct_chg / vol）
            cur.execute(
                """
                SELECT DISTINCT ON (ts_code) ts_code, close, pct_chg, vol
                FROM core.equity_daily_bar
                WHERE ts_code = ANY(%s)
                ORDER BY ts_code, trade_date DESC
                """,
                (ts_codes,),
            )
            daily_map = {r[0]: {"close": r[1], "pct_chg": r[2], "vol": r[3]}
                         for r in cur.fetchall()}

            # 最新每日指标
            cur.execute(
                """
                SELECT DISTINCT ON (ts_code) ts_code,
                       turnover_rate, turnover_rate_f, volume_ratio,
                       pe_ttm, dv_ratio, dv_ttm,
                       total_share, float_share, free_share,
                       total_mv, circ_mv
                FROM core.equity_daily_basic
                WHERE ts_code = ANY(%s)
                ORDER BY ts_code, trade_date DESC
                """,
                (ts_codes,),
            )
            _basic_cols = [
                "turnover_rate", "turnover_rate_f", "volume_ratio",
                "pe_ttm", "dv_ratio", "dv_ttm",
                "total_share", "float_share", "free_share",
                "total_mv", "circ_mv",
            ]
            basic_map = {
                r[0]: dict(zip(_basic_cols, r[1:]))
                for r in cur.fetchall()
            }

    # ── Step 3: 按持仓顺序组装结果 ───────────────────────────
    result = []
    for i, ts_code in enumerate(ts_codes, start=1):
        daily = daily_map.get(ts_code, {})
        basic = basic_map.get(ts_code, {})
        result.append({
            "idx":             i,
            "ts_code":         ts_code,
            "name":            name_map.get(ts_code, ts_code),
            "close":           _f(daily.get("close")),
            "pct_chg":         _f(daily.get("pct_chg")),
            "vol":             _f(daily.get("vol")),
            "turnover_rate":   _f(basic.get("turnover_rate")),
            "turnover_rate_f": _f(basic.get("turnover_rate_f")),
            "volume_ratio":    _f(basic.get("volume_ratio")),
            "pe_ttm":          _f(basic.get("pe_ttm")),
            "dv_ratio":        _f(basic.get("dv_ratio")),
            "dv_ttm":          _f(basic.get("dv_ttm")),
            "total_share":     _f(basic.get("total_share")),
            "float_share":     _f(basic.get("float_share")),
            "free_share":      _f(basic.get("free_share")),
            "total_mv":        _f(basic.get("total_mv")),
            "circ_mv":         _f(basic.get("circ_mv")),
        })
    return result


@router.post("/portfolio", status_code=201)
def add_stock(body: AddStockRequest, user: dict = Depends(get_current_user)):
    user_id = int(user["sub"])
    ts_code = body.ts_code.strip().upper()

    # 验证代码是否存在于 goldenshare（个股或指数）
    with get_gs_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name FROM core.security "
                "WHERE ts_code = %s AND security_type = 'EQUITY'",
                (ts_code,),
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    "SELECT name FROM core.index_basic WHERE ts_code = %s",
                    (ts_code,),
                )
                if cur.fetchone():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"{ts_code} 是指数代码，当前持仓列表仅支持个股",
                    )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"股票代码 {ts_code} 不存在",
                )
            name = row[0]

    # 写入持仓到 stock DB
    with get_conn() as conn:
        with conn.cursor() as cur:
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
