"""
使用 tushare 获取同花顺行业/概念板块指数日线行情（ths_daily）。

tushare 接口：ths_daily
描述：获取同花顺行业/概念板块指数每日行情
限量：单次最大 4000 行
所需积分：2000

与申万/中信行业日线的差异
-------------------------
- 有 pre_close, avg_price（均价）
- 有 turnover_rate（换手率）
- 有 total_mv / float_mv（总市值/流通市值）
- 有 up_count / down_count（上涨/下跌家数）
- 无 pe / pb / weight

输出字段
--------
ts_code, trade_date, open, high, low, close, pre_close,
change, pct_chg, avg_price, turnover_rate,
total_mv, float_mv, vol, amount,
up_count, down_count

拉取策略（与申万/中信行业日线相同）
--------------------------------------
1. 按日期：ths_daily(trade_date='YYYYMMDD') → 当日所有板块，1次API
   适合日常更新（日常定时任务）

2. 按代码：ths_daily(ts_code='...', start_date=...) → 分页
   适合历史回填（从 ths_index 取全量板块代码后逐一拉取）
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

_COLS = [
    "ts_code", "trade_date",
    "open", "high", "low", "close", "pre_close",
    "change", "pct_chg",
    "avg_price", "turnover_rate",
    "total_mv", "float_mv",
    "vol", "amount",
    "up_count", "down_count",
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
    if df is None or df.empty:
        return pd.DataFrame()
    cols = [c for c in _COLS if c in df.columns]
    df = df[cols].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    return df


def fetch_ths_daily_by_date(trade_date: str) -> pd.DataFrame:
    """
    按单个交易日拉取所有同花顺板块指数行情（一次 API）。

    参数
    ----
    trade_date : str  格式 YYYYMMDD

    返回
    ----
    pd.DataFrame
    """
    pro = _get_pro_api()
    _rate_limit_wait()
    df = pro.ths_daily(trade_date=trade_date)
    return _clean(df)


def fetch_ths_daily_by_code(
    ts_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    按板块代码拉取完整历史日线，自动分页。

    参数
    ----
    ts_code    : 同花顺板块代码，如 '885650.TI'
    start_date : 开始日期 YYYYMMDD
    end_date   : 结束日期 YYYYMMDD

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
        df = pro.ths_daily(**kwargs)
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


def fetch_ths_daily_all_codes(
    codes: list[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sleep_sec: float = 0.3,
) -> pd.DataFrame:
    """
    批量拉取一组同花顺板块代码的日线历史，适合历史回填。

    参数
    ----
    codes      : 板块代码列表（从 ths_index 取）
    start_date : 开始日期 YYYYMMDD
    end_date   : 结束日期 YYYYMMDD
    sleep_sec  : 两次 API 调用间隔（秒）
    """
    frames = []
    total = len(codes)

    for i, code in enumerate(codes, 1):
        try:
            df = fetch_ths_daily_by_code(code, start_date=start_date, end_date=end_date)
            if not df.empty:
                frames.append(df)
                print(f"[ths_daily] ({i}/{total}) {code} → {len(df)} 行")
            else:
                print(f"[ths_daily] ({i}/{total}) {code} → 空数据")
        except Exception as e:
            print(f"[ths_daily] ({i}/{total}) {code} 出错：{e}")

        if i < total:
            time.sleep(sleep_sec)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    return result.drop_duplicates(subset=["ts_code", "trade_date"]).reset_index(drop=True)
