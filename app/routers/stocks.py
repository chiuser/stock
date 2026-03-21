from fastapi import APIRouter, Query
from typing import Optional
import pandas as pd
from datetime import timedelta

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from db import get_conn

router = APIRouter()

MA_WINDOWS = [5, 10, 15, 20, 30, 60, 120, 250]

# 白名单：避免列名注入
_ADJ_COLS = {
    "qfq":   ("open_qfq",  "high_qfq",  "low_qfq",  "close_qfq"),
    "hfq":   ("open_hfq",  "high_hfq",  "low_hfq",  "close_hfq"),
    "":      ("open",      "high",      "low",      "close"),
    "unadj": ("open",      "high",      "low",      "close"),
}


@router.get("/stocks/search")
def search_stocks(q: str = Query("", max_length=50)):
    """搜索指数和股票，指数结果在前；支持代码、名称、拼音缩写。"""
    q = q.strip()
    if not q:
        return []
    with get_conn() as conn:
        with conn.cursor() as cur:
            # 先查指数（index_basic 无拼音列，按代码和名称匹配）
            cur.execute("""
                SELECT ts_code, name, market
                FROM index_basic
                WHERE ts_code ILIKE %s OR name ILIKE %s
                ORDER BY
                    CASE WHEN ts_code ILIKE %s THEN 0 ELSE 1 END,
                    ts_code
                LIMIT 10
            """, (f"{q}%", f"%{q}%", f"{q}%"))
            index_rows = cur.fetchall()

            # 再查个股（支持拼音缩写）
            cur.execute("""
                SELECT ts_code, name, market
                FROM stock_basic
                WHERE ts_code ILIKE %s
                   OR name LIKE %s
                   OR cnspell ILIKE %s
                ORDER BY
                    CASE WHEN ts_code ILIKE %s THEN 0 ELSE 1 END,
                    ts_code
                LIMIT 20
            """, (f"{q}%", f"%{q}%", f"{q}%", f"{q}%"))
            stock_rows = cur.fetchall()

    results = [{"ts_code": r[0], "name": r[1], "market": r[2], "type": "index"}
               for r in index_rows]
    results += [{"ts_code": r[0], "name": r[1], "market": r[2], "type": "stock"}
                for r in stock_rows]
    return results[:20]


@router.get("/stock/{ts_code}/info")
def get_stock_info(ts_code: str):
    """获取股票或指数基本信息。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            # 先查个股
            cur.execute(
                "SELECT ts_code, name, industry, market, list_date "
                "FROM stock_basic WHERE ts_code = %s",
                (ts_code,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "ts_code":   row[0],
                    "name":      row[1],
                    "industry":  row[2],
                    "market":    row[3],
                    "list_date": str(row[4]) if row[4] else None,
                }
            # 再查指数
            cur.execute(
                "SELECT ts_code, name, market, list_date "
                "FROM index_basic WHERE ts_code = %s",
                (ts_code,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "ts_code":   row[0],
        "name":      row[1],
        "industry":  None,
        "market":    row[2],
        "list_date": str(row[3]) if row[3] else None,
    }


@router.get("/stock/{ts_code}/daily")
def get_stock_daily(
    ts_code: str,
    start:   Optional[str] = None,
    end:     Optional[str] = None,
    adj:     str = "qfq",
):
    """
    获取个股日线数据（K线 + 均线 + 成交量）。

    adj: qfq=前复权  hfq=后复权  空=不复权
    start/end: YYYYMMDD
    """
    cols = _ADJ_COLS.get(adj, _ADJ_COLS["qfq"])
    o, h, l, c = cols

    # 向前多取 ~400 个自然日，确保 MA250 有足够历史
    lookback_start: Optional[str] = None
    if start:
        lookback_start = (
            pd.to_datetime(start, format="%Y%m%d") - timedelta(days=400)
        ).strftime("%Y%m%d")

    conditions = ["ts_code = %s"]
    params: list = [ts_code]
    if lookback_start:
        conditions.append("trade_date >= %s")
        params.append(lookback_start)
    if end:
        conditions.append("trade_date <= %s")
        params.append(end)

    where = " AND ".join(conditions)
    sql = (
        f"SELECT trade_date, {o}, {h}, {l}, {c}, vol "
        f"FROM stock_daily WHERE {where} ORDER BY trade_date ASC"
    )

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

            # 个股表无数据时，回退到指数日线表（指数无复权价，固定用原始 OHLC）
            if not rows:
                idx_sql = (
                    "SELECT trade_date, open, high, low, close, vol "
                    f"FROM index_daily WHERE {where} ORDER BY trade_date ASC"
                )
                cur.execute(idx_sql, params)
                rows = cur.fetchall()

    if not rows:
        return {"ts_code": ts_code, "candles": [], "volume": [], "ma": {}}

    df = pd.DataFrame(rows, columns=["trade_date", "open", "high", "low", "close", "vol"])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.dropna(subset=["open", "close"]).reset_index(drop=True)

    # 先用全部历史计算均线，再按用户请求的 start 截断
    for w in MA_WINDOWS:
        df[f"ma{w}"] = df["close"].rolling(w).mean().round(4)

    if start:
        start_dt = pd.to_datetime(start, format="%Y%m%d")
        df = df[df["trade_date"] >= start_dt].reset_index(drop=True)

    # 序列化
    candles, volume = [], []
    for row in df.itertuples(index=False):
        d = str(row.trade_date)[:10]
        candles.append({
            "time":  d,
            "open":  float(row.open),
            "high":  float(row.high),
            "low":   float(row.low),
            "close": float(row.close),
        })
        volume.append({
            "time":  d,
            "value": float(row.vol) if row.vol and not pd.isna(row.vol) else 0,
            "color": "#ef5350" if row.close >= row.open else "#26a69a",
        })

    ma_out = {}
    for w in MA_WINDOWS:
        col = f"ma{w}"
        ma_out[str(w)] = [
            {"time": str(row.trade_date)[:10], "value": float(getattr(row, col))}
            for row in df.itertuples(index=False)
            if pd.notna(getattr(row, col))
        ]

    return {"ts_code": ts_code, "candles": candles, "volume": volume, "ma": ma_out}
