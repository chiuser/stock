"""
使用 tushare 获取A股个股周线/月线行情数据。

tushare 接口文档：
  stk_weekly_monthly  （所需积分：2000）

接口限制：
  单次最大 6000 行，可按交易日期循环提取，总量不限。
  按 ts_code 拉取时，单股历史行数远低于 6000（周线约 1500 行/30年，月线约 360 行），
  因此按股票代码单次拉取全量历史即可。

freq 参数：
  'week'  – 周线（trade_date 为本周最后一个交易日）
  'month' – 月线（trade_date 为本月最后一个交易日）
"""

import time
import collections
import threading
from typing import Optional, Literal

import tushare as ts
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN

# 限速：每分钟最多 200 次（stk_weekly_monthly 积分门槛高，保守些）
_RATE_LIMIT = 200
_WINDOW = 60.0
_rate_lock = threading.Lock()
_call_times: collections.deque = collections.deque()


def _rate_limit_wait():
    with _rate_lock:
        now = time.monotonic()
        while _call_times and _call_times[0] < now - _WINDOW:
            _call_times.popleft()
        if len(_call_times) >= _RATE_LIMIT:
            sleep_for = _WINDOW - (now - _call_times[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
        _call_times.append(time.monotonic())


def _get_pro_api():
    if not TUSHARE_TOKEN:
        raise ValueError(
            "未设置 tushare token。请设置环境变量 TUSHARE_TOKEN，"
            "或在 config.py 中填写 TUSHARE_TOKEN。"
        )
    ts.set_token(TUSHARE_TOKEN)
    return ts.pro_api()


_FIELDS = "ts_code,trade_date,end_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"

_COL_ORDER = [
    "ts_code", "trade_date", "end_date",
    "open", "high", "low", "close", "pre_close", "change", "pct_chg",
    "vol", "amount",
]


def fetch_stk_weekly_monthly(
    freq: Literal["week", "month"],
    ts_code: Optional[str] = None,
    trade_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取个股周线或月线行情。

    参数
    ----
    freq       : 'week' 或 'month'（必填）
    ts_code    : 股票代码，如 '000001.SZ'
    trade_date : 指定某一周/月的最后交易日（YYYYMMDD）
    start_date : 开始日期（YYYYMMDD）
    end_date   : 结束日期（YYYYMMDD）

    返回
    ----
    pd.DataFrame，列同 _COL_ORDER，trade_date / end_date 为 datetime 类型。

    示例
    ----
    >>> df = fetch_stk_weekly_monthly('week', ts_code='000001.SZ')
    >>> df = fetch_stk_weekly_monthly('month', ts_code='000001.SZ', start_date='20200101')
    """
    if freq not in ("week", "month"):
        raise ValueError(f"freq 必须为 'week' 或 'month'，当前值：{freq!r}")

    pro = _get_pro_api()

    params: dict = {"freq": freq, "fields": _FIELDS}
    if ts_code:
        params["ts_code"] = ts_code
    if trade_date:
        params["trade_date"] = trade_date
    else:
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

    _rate_limit_wait()
    df = pro.stk_weekly_monthly(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    if "end_date" in df.columns:
        df["end_date"] = pd.to_datetime(df["end_date"], format="%Y%m%d", errors="coerce")
    df = df[[c for c in _COL_ORDER if c in df.columns]]
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return df
