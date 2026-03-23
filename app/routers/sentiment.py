from fastapi import APIRouter
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from db import get_conn

router = APIRouter()

# 展示的指数，左列 + 右列各5个
INDEX_GROUPS = [
    [
        ("000001.SH", "上证指数"),
        ("399001.SZ", "深圳成指"),
        ("399006.SZ", "创业板指"),
        ("000688.SH", "科创50"),
        ("899050.BJ", "北证50"),
    ],
    [
        ("000016.SH", "上证50"),
        ("000300.SH", "沪深300"),
        ("000905.SH", "中证500"),
        ("000852.SH", "中证1000"),
        ("932000.CSI", "中证A500"),
    ],
]


@router.get("/sentiment/index-summary")
def index_summary():
    """返回核心指数最近两个交易日的收盘数据。"""
    codes = [c for grp in INDEX_GROUPS for c, _ in grp]
    name_map = {c: n for grp in INDEX_GROUPS for c, n in grp}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ts_code, trade_date, close, pre_close, pct_chg
                FROM index_daily
                WHERE ts_code = ANY(%s)
                ORDER BY trade_date DESC
                """,
                (codes,),
            )
            rows = cur.fetchall()

    # 按指数取最新两条
    by_code: dict[str, list] = {}
    for ts_code, trade_date, close, pre_close, pct_chg in rows:
        by_code.setdefault(ts_code, [])
        if len(by_code[ts_code]) < 2:
            by_code[ts_code].append({
                "trade_date": str(trade_date),
                "close": float(close) if close is not None else None,
                "pre_close": float(pre_close) if pre_close is not None else None,
                "pct_chg": float(pct_chg) if pct_chg is not None else None,
            })

    result = []
    for grp in INDEX_GROUPS:
        grp_data = []
        for ts_code, _ in grp:
            days = by_code.get(ts_code, [])
            today = days[0] if len(days) >= 1 else {}
            grp_data.append({
                "ts_code": ts_code,
                "name": name_map[ts_code],
                "trade_date": today.get("trade_date"),
                "close": today.get("close"),
                "pre_close": today.get("pre_close"),
                "pct_chg": today.get("pct_chg"),
            })
        result.append(grp_data)

    return result
