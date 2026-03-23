"""
使用 tushare 获取同花顺每日涨跌停榜单（limit_list_ths）。

tushare 接口：limit_list_ths
描述：获取同花顺每日涨跌停榜单数据，历史数据从 20231101 开始提供
限量：单次最大 4000 条，limit_type 一次只能传入一个值
所需积分：8000

limit_type 可选值
-----------------
涨停池   当日封板的涨停股（默认）
连板池   连续多日涨停
冲刺涨停 接近涨停但未封板
炸板池   曾涨停后开板
跌停池   当日封板的跌停股

输出字段（全部）
--------------
trade_date, ts_code, name, price, pct_chg, open_num, lu_desc,
limit_type, tag, status,
first_lu_time*, last_lu_time*, first_ld_time*, last_ld_time*,
limit_order, limit_amount, turnover_rate, free_float, lu_limit_order,
limit_up_suc_rate, turnover, rise_rate*, sum_float*, market_type

（* 默认不返回，通过 fields 参数强制请求）
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

_RATE_LIMIT = 250
_WINDOW = 60.0
_rate_lock = threading.Lock()
_call_times: collections.deque = collections.deque()

_PAGE_SIZE = 3800   # 保守低于接口上限 4000

# 所有输出字段（含默认不返回的字段）
_ALL_FIELDS = ",".join([
    "trade_date", "ts_code", "name", "price", "pct_chg", "open_num",
    "lu_desc", "limit_type", "tag", "status",
    "first_lu_time", "last_lu_time", "first_ld_time", "last_ld_time",
    "limit_order", "limit_amount", "turnover_rate", "free_float",
    "lu_limit_order", "limit_up_suc_rate", "turnover",
    "rise_rate", "sum_float", "market_type",
])

_COLS = _ALL_FIELDS.split(",")

ALL_LIMIT_TYPES = ["涨停池", "连板池", "冲刺涨停", "炸板池", "跌停池"]


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


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    cols = [c for c in _COLS if c in df.columns]
    df = df[cols].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    return df


def fetch_limit_list_by_date(
    trade_date: str,
    limit_type: str = "涨停池",
) -> pd.DataFrame:
    """
    拉取指定交易日、指定类型的涨跌停榜单（自动翻页）。

    参数
    ----
    trade_date : str  格式 YYYYMMDD
    limit_type : str  涨停池 | 连板池 | 冲刺涨停 | 炸板池 | 跌停池

    返回
    ----
    pd.DataFrame，包含所有输出字段
    """
    pro = _get_pro_api()
    frames = []
    offset = 0

    while True:
        _rate_limit_wait()
        df = pro.limit_list_ths(
            trade_date=trade_date,
            limit_type=limit_type,
            fields=_ALL_FIELDS,
            limit=_PAGE_SIZE,
            offset=offset,
        )
        if df is None or df.empty:
            break
        frames.append(df)
        if len(df) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    return _clean(result)


def fetch_limit_list_range(
    start_date: str,
    end_date: Optional[str] = None,
    limit_type: str = "涨停池",
) -> pd.DataFrame:
    """
    按日期区间、指定类型拉取涨跌停榜单（逐日循环，自动翻页）。

    参数
    ----
    start_date : str  格式 YYYYMMDD
    end_date   : str  格式 YYYYMMDD（默认今日）
    limit_type : str  板单类型

    返回
    ----
    pd.DataFrame
    """
    import datetime

    def _parse(d: str) -> "datetime.date":
        return datetime.date(int(d[:4]), int(d[4:6]), int(d[6:]))

    today = datetime.date.today()
    end = _parse(end_date) if end_date else today
    cur = _parse(start_date)
    delta = datetime.timedelta(days=1)

    frames = []
    while cur <= end:
        d = cur.strftime("%Y%m%d")
        try:
            df = fetch_limit_list_by_date(d, limit_type=limit_type)
            if not df.empty:
                frames.append(df)
                print(f"[limit_list_ths] {d} {limit_type} → {len(df)} 行")
            else:
                print(f"[limit_list_ths] {d} {limit_type} → 空数据")
        except Exception as e:
            print(f"[limit_list_ths] {d} {limit_type} 出错：{e}")
        cur += delta

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)
