"""
使用 tushare 获取同花顺热榜数据（ths_hot）。

接口：ths_hot
描述：获取同花顺App热榜数据，包括热股、ETF、可转债、行业板块、
      概念板块、期货、港股、热基、美股
限量：单次最大2000条
所需积分：6000

market 可选值
--------------
热股 / ETF / 可转债 / 行业板块 / 概念板块 / 期货 / 港股 / 热基 / 美股

is_new 说明
-----------
Y（默认）：返回最新快照（22:30 更新），适合每15分钟定时拉取当前排名
N：返回指定日期的全部盘中快照（每小时更新），适合补拉历史全量
"""

import time
import collections
import threading
from typing import Optional

import tushare as ts
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN

# 6000 积分接口，保守限速 200 次/分钟
_RATE_LIMIT = 200
_WINDOW = 60.0
_rate_lock = threading.Lock()
_call_times: collections.deque = collections.deque()

_PAGE_SIZE = 2000

ALL_MARKETS = ["热股", "ETF", "可转债", "行业板块", "概念板块", "期货", "港股", "热基", "美股"]

_FIELDS = ",".join([
    "trade_date", "data_type", "ts_code", "ts_name",
    "rank", "pct_change", "current_price",
    "concept", "rank_reason", "hot", "rank_time",
])
_COLS = _FIELDS.split(",")


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
            "未设置 tushare token。请设置环境变量 TUSHARE_TOKEN。"
        )
    ts.set_token(TUSHARE_TOKEN)
    return ts.pro_api()


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    cols = [c for c in _COLS if c in df.columns]
    df = df[cols].copy()
    # trade_date: "20260323" → date
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(
            df["trade_date"], format="%Y%m%d", errors="coerce"
        ).dt.date
    # rank_time: "2026/3/23 21:30:01" → TIMESTAMP
    if "rank_time" in df.columns:
        df["rank_time"] = pd.to_datetime(df["rank_time"], errors="coerce")
    return df


def _fetch_pages(pro, **kwargs) -> pd.DataFrame:
    """通用分页拉取（自动翻页）。"""
    frames = []
    offset = 0
    while True:
        _rate_limit_wait()
        df = pro.ths_hot(
            fields=_FIELDS,
            limit=_PAGE_SIZE,
            offset=offset,
            **kwargs,
        )
        if df is None or df.empty:
            break
        frames.append(df)
        if len(df) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    if not frames:
        return pd.DataFrame()
    return _clean(pd.concat(frames, ignore_index=True))


def fetch_latest(market: str) -> pd.DataFrame:
    """
    拉取指定市场类型的当前最新热榜快照（is_new=Y）。
    适合每15分钟定时调用。

    参数
    ----
    market : 热股 | ETF | 可转债 | 行业板块 | 概念板块 | 期货 | 港股 | 热基 | 美股
    """
    pro = _get_pro_api()
    return _fetch_pages(pro, market=market, is_new="Y")


def fetch_by_date(trade_date: str, market: str) -> pd.DataFrame:
    """
    拉取指定日期、指定市场类型的全部快照（is_new=N）。
    适合补拉历史数据。

    参数
    ----
    trade_date : YYYYMMDD
    market     : 热股 | ETF | 可转债 | ...
    """
    pro = _get_pro_api()
    return _fetch_pages(pro, trade_date=trade_date, market=market, is_new="N")
