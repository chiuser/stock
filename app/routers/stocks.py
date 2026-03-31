from fastapi import APIRouter, Query
from typing import Optional
import pandas as pd
from datetime import timedelta

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from db import get_gs_conn

from pypinyin import lazy_pinyin, Style

router = APIRouter()

MA_WINDOWS = [5, 10, 15, 20, 30, 60, 120, 250]

# ── goldenshare 表名（schema.table）─────────────────────────
_T_SECURITY      = "core.security"
_T_INDEX_BASIC   = "core.index_basic"
_T_DAILY_BAR     = "core.equity_daily_bar"
_T_DAILY_BASIC   = "core.equity_daily_basic"
_T_ADJ_FACTOR    = "core.equity_adj_factor"
_T_INDEX_BAR     = "core.index_daily_bar"
_T_PERIOD_BAR    = "core.stk_period_bar_adj"

# freq 映射：weekly/monthly → goldenshare freq 值
_FREQ_MAP = {"weekly": "W", "monthly": "M"}

# ── 指数拼音缓存（内存，进程级）──────────────────────────────
_index_cache: list | None = None


def _get_index_cache():
    global _index_cache
    if _index_cache is None:
        with get_gs_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT ts_code, name, market FROM {_T_INDEX_BASIC}")
                rows = cur.fetchall()
        _index_cache = [
            (r[0], r[1], r[2],
             ''.join(lazy_pinyin(r[1], style=Style.FIRST_LETTER)).lower())
            for r in rows
        ]
    return _index_cache


def _sf(v):
    """安全转 float，None/NaN 返回 None。"""
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


@router.get("/stocks/search")
def search_stocks(q: str = Query("", max_length=50)):
    """搜索指数和股票，指数结果在前；支持代码、名称、拼音缩写。"""
    q = q.strip()
    if not q:
        return []

    # 指数：从内存缓存过滤
    ql = q.lower()
    cache = _get_index_cache()
    code_matches, exact_matches, prefix_matches, other_matches = [], [], [], []
    for ts_code, name, market, pinyin in cache:
        if ts_code.lower().startswith(ql):
            code_matches.append((ts_code, name, market))
        elif name == q:
            exact_matches.append((ts_code, name, market))
        elif name.startswith(q):
            prefix_matches.append((ts_code, name, market))
        elif ql in name.lower() or pinyin.startswith(ql):
            other_matches.append((ts_code, name, market))
    index_rows = (code_matches + exact_matches + prefix_matches + other_matches)[:15]

    # 个股：查 core.security（security_type = 'EQUITY'）
    with get_gs_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT ts_code, name, market
                FROM {_T_SECURITY}
                WHERE security_type = 'EQUITY'
                  AND (ts_code ILIKE %s OR name LIKE %s OR cnspell ILIKE %s)
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
    with get_gs_conn() as conn:
        with conn.cursor() as cur:
            # 先查个股
            cur.execute(
                f"SELECT ts_code, name, industry, market, list_date "
                f"FROM {_T_SECURITY} WHERE ts_code = %s AND security_type = 'EQUITY'",
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
                f"SELECT ts_code, name, market, list_date "
                f"FROM {_T_INDEX_BASIC} WHERE ts_code = %s",
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
    freq:    str = "daily",
):
    """
    获取个股 K 线数据（K线 + 均线 + 成交量）。

    freq: daily=日线  weekly=周线  monthly=月线
    adj:  qfq=前复权  hfq=后复权  空/unadj=不复权（周线/月线直接有复权列，忽略此参数不合法）
    """
    # ── 周线 / 月线 ──────────────────────────────────────────
    if freq in ("weekly", "monthly"):
        gs_freq = _FREQ_MAP[freq]
        # stk_period_bar_adj 已内置 qfq/hfq 价格列，直接取
        adj_norm = adj if adj in ("qfq", "hfq") else ""
        o = f"open_{adj_norm}"  if adj_norm else "open"
        h = f"high_{adj_norm}"  if adj_norm else "high"
        l = f"low_{adj_norm}"   if adj_norm else "low"
        c = f"close_{adj_norm}" if adj_norm else "close"

        with get_gs_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT trade_date, {o}, {h}, {l}, {c}, vol, pct_chg, amount "
                    f"FROM {_T_PERIOD_BAR} "
                    f"WHERE ts_code = %s AND freq = %s "
                    f"ORDER BY trade_date ASC",
                    (ts_code, gs_freq),
                )
                rows = cur.fetchall()

        if not rows:
            return {"ts_code": ts_code, "candles": [], "volume": [], "ma": {}, "is_index": False}

        df = pd.DataFrame(rows, columns=[
            "trade_date", "open", "high", "low", "close", "vol", "pct_chg", "amount"
        ])
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.dropna(subset=["open", "close"]).reset_index(drop=True)

        for w in MA_WINDOWS:
            df[f"ma{w}"] = df["close"].rolling(w).mean().round(4)

        candles, volume = [], []
        for row in df.itertuples(index=False):
            d = str(row.trade_date)[:10]
            candles.append({
                "time":          d,
                "open":          float(row.open),
                "high":          float(row.high),
                "low":           float(row.low),
                "close":         float(row.close),
                "pct_chg":       _sf(row.pct_chg),
                "amount":        _sf(row.amount),
                "turnover_rate": None,
            })
            volume.append({
                "time":  d,
                "value": float(row.vol) if row.vol and not pd.isna(row.vol) else 0,
                "color": "#E04040" if row.close >= row.open else "#45AA55",
            })

        ma_out = {}
        for w in MA_WINDOWS:
            col = f"ma{w}"
            ma_out[str(w)] = [
                {"time": str(row.trade_date)[:10], "value": float(getattr(row, col))}
                for row in df.itertuples(index=False)
                if pd.notna(getattr(row, col))
            ]

        return {"ts_code": ts_code, "candles": candles, "volume": volume, "ma": ma_out, "is_index": False}

    # ── 日线 ─────────────────────────────────────────────────
    # 向前多取 ~400 个自然日，确保 MA250 有足够历史
    lookback_start: Optional[str] = None
    if start:
        lookback_start = (
            pd.to_datetime(start, format="%Y%m%d") - timedelta(days=400)
        ).strftime("%Y%m%d")

    conds  = ["d.ts_code = %s"]
    params: list = [ts_code]
    if lookback_start:
        conds.append("d.trade_date >= %s")
        params.append(lookback_start)
    if end:
        conds.append("d.trade_date <= %s")
        params.append(end)
    where = " AND ".join(conds)

    # 取原始价 + 复权因子 + 换手率，复权在 Python 里完成
    sql = f"""
        SELECT d.trade_date, d.open, d.high, d.low, d.close,
               d.vol, d.pct_chg, d.amount,
               af.adj_factor, sdb.turnover_rate
        FROM {_T_DAILY_BAR} d
        LEFT JOIN {_T_ADJ_FACTOR} af
               ON af.ts_code = d.ts_code AND af.trade_date = d.trade_date
        LEFT JOIN {_T_DAILY_BASIC} sdb
               ON sdb.ts_code = d.ts_code AND sdb.trade_date = d.trade_date
        WHERE {where}
        ORDER BY d.trade_date ASC
    """

    is_index = False
    with get_gs_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

            # 个股表无数据时，回退到指数日线（指数无复权因子）
            if not rows:
                idx_conds  = ["ts_code = %s"]
                idx_params: list = [ts_code]
                if lookback_start:
                    idx_conds.append("trade_date >= %s")
                    idx_params.append(lookback_start)
                if end:
                    idx_conds.append("trade_date <= %s")
                    idx_params.append(end)
                idx_where = " AND ".join(idx_conds)
                cur.execute(
                    f"SELECT trade_date, open, high, low, close, vol, "
                    f"pct_chg, amount, NULL::float AS adj_factor, "
                    f"NULL::float AS turnover_rate "
                    f"FROM {_T_INDEX_BAR} WHERE {idx_where} ORDER BY trade_date ASC",
                    idx_params,
                )
                rows = cur.fetchall()
                is_index = True

    if not rows:
        return {"ts_code": ts_code, "candles": [], "volume": [], "ma": {}, "is_index": is_index}

    df = pd.DataFrame(rows, columns=[
        "trade_date", "open", "high", "low", "close",
        "vol", "pct_chg", "amount", "adj_factor", "turnover_rate"
    ])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.dropna(subset=["open", "close"]).reset_index(drop=True)

    # 复权计算：adj_factor 缺失时视为 1.0
    if adj in ("qfq", "hfq") and not is_index:
        af = pd.to_numeric(df["adj_factor"], errors="coerce").fillna(1.0)
        price_cols = ["open", "high", "low", "close"]
        if adj == "qfq":
            latest_af = af.iloc[-1] if len(af) > 0 and af.iloc[-1] != 0 else 1.0
            for col in price_cols:
                df[col] = (pd.to_numeric(df[col], errors="coerce") * af / latest_af).round(4)
        else:  # hfq
            for col in price_cols:
                df[col] = (pd.to_numeric(df[col], errors="coerce") * af).round(4)

    # 先用全量历史计算均线，再截断到用户请求范围
    for w in MA_WINDOWS:
        df[f"ma{w}"] = df["close"].rolling(w).mean().round(4)

    if start:
        start_dt = pd.to_datetime(start, format="%Y%m%d")
        df = df[df["trade_date"] >= start_dt].reset_index(drop=True)

    candles, volume = [], []
    for row in df.itertuples(index=False):
        d = str(row.trade_date)[:10]
        candles.append({
            "time":          d,
            "open":          float(row.open),
            "high":          float(row.high),
            "low":           float(row.low),
            "close":         float(row.close),
            "pct_chg":       _sf(row.pct_chg),
            "amount":        _sf(row.amount),
            "turnover_rate": _sf(row.turnover_rate),
        })
        volume.append({
            "time":  d,
            "value": float(row.vol) if row.vol and not pd.isna(row.vol) else 0,
            "color": "#E04040" if row.close >= row.open else "#45AA55",
        })

    ma_out = {}
    for w in MA_WINDOWS:
        col = f"ma{w}"
        ma_out[str(w)] = [
            {"time": str(row.trade_date)[:10], "value": float(getattr(row, col))}
            for row in df.itertuples(index=False)
            if pd.notna(getattr(row, col))
        ]

    return {"ts_code": ts_code, "candles": candles, "volume": volume, "ma": ma_out, "is_index": is_index}
