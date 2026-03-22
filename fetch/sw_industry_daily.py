"""
使用 tushare 获取申万行业日线行情数据（sw_daily）。

tushare 接口：sw_daily
描述：获取申万行业日线行情（默认是申万2021版行情）
限量：单次最大 4000 行，可通过指数代码和日期参数循环提取
所需积分：5000

支持两种拉取模式
-----------------
1. 按日期拉取：一次 API 调用返回该日期所有申万行业指数数据（约 439 条），
   适合日常更新。

2. 按代码拉取：指定 ts_code 和日期区间，分页获取该行业全部历史，
   适合历史回填（约 439 次 API，但每次返回更多行）。

输出字段
--------
ts_code, trade_date, name,
open, low, high, close, change, pct_change,
vol, amount, pe, pb, float_mv, total_mv, weight
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

# 限速：每分钟最多 250 次（保守）
_RATE_LIMIT = 250
_WINDOW = 60.0
_rate_lock = threading.Lock()
_call_times: collections.deque = collections.deque()

_PAGE_SIZE = 3800   # 保守低于接口上限 4000

_COLS = [
    "ts_code", "trade_date", "name",
    "open", "low", "high", "close",
    "change", "pct_change",
    "vol", "amount",
    "pe", "pb", "float_mv", "total_mv", "weight",
]


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
    """统一列类型：trade_date → DATE，只保留 _COLS 中的列。"""
    if df.empty:
        return df
    cols = [c for c in _COLS if c in df.columns]
    df = df[cols].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    return df


def fetch_sw_daily_by_date(trade_date: str) -> pd.DataFrame:
    """
    按单个交易日拉取所有申万行业指数行情（约 439 条，一次 API）。

    参数
    ----
    trade_date : str
        交易日，格式 YYYYMMDD，如 '20230705'

    返回
    ----
    pd.DataFrame
    """
    pro = _get_pro_api()
    _rate_limit_wait()
    df = pro.sw_daily(trade_date=trade_date)
    return _clean(df) if df is not None and not df.empty else pd.DataFrame()


def fetch_sw_daily_by_code(
    ts_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    按行业代码拉取完整历史日线，自动分页（每页最多 _PAGE_SIZE 行）。

    参数
    ----
    ts_code    : 申万行业指数代码，如 '801010.SI'
    start_date : 开始日期 YYYYMMDD（不填则拉全部历史）
    end_date   : 结束日期 YYYYMMDD（不填则到最新日期）

    返回
    ----
    pd.DataFrame，按 trade_date 升序排列
    """
    pro = _get_pro_api()
    frames = []
    offset = 0

    while True:
        kwargs: dict = {"ts_code": ts_code, "limit": _PAGE_SIZE, "offset": offset}
        if start_date: kwargs["start_date"] = start_date
        if end_date:   kwargs["end_date"]   = end_date

        _rate_limit_wait()
        df = pro.sw_daily(**kwargs)
        if df is None or df.empty:
            break
        frames.append(df)
        if len(df) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    result = _clean(result)
    return result.sort_values("trade_date").reset_index(drop=True)


def fetch_sw_daily_all_codes(
    codes: list[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sleep_sec: float = 0.3,
) -> pd.DataFrame:
    """
    批量拉取一组申万行业代码的日线历史，适合历史回填。

    参数
    ----
    codes      : 申万行业指数代码列表（从 sw_industry_class 取）
    start_date : 开始日期 YYYYMMDD
    end_date   : 结束日期 YYYYMMDD
    sleep_sec  : 两次 API 调用间隔（秒）

    返回
    ----
    pd.DataFrame（所有代码合并，去重）
    """
    frames = []
    total = len(codes)

    for i, code in enumerate(codes, 1):
        try:
            df = fetch_sw_daily_by_code(code, start_date=start_date, end_date=end_date)
            if not df.empty:
                frames.append(df)
                print(f"[sw_industry_daily] ({i}/{total}) {code} → {len(df)} 行")
            else:
                print(f"[sw_industry_daily] ({i}/{total}) {code} → 空数据")
        except Exception as e:
            print(f"[sw_industry_daily] ({i}/{total}) {code} 出错：{e}")

        if i < total:
            time.sleep(sleep_sec)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    return result.drop_duplicates(subset=["ts_code", "trade_date"]).reset_index(drop=True)
