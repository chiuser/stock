"""
使用 tushare 获取东方财富板块成分股数据（dc_member）。

tushare 接口: dc_member
描述: 获取东方财富板块每日成分数据，可根据概念板块代码和交易日期查询历史成分
限量: 单次最大 5000 条，可通过日期和代码循环获取
所需积分: 6000

输入参数（均可选）:
  ts_code    -- 板块指数代码（如 BK1184.DC）
  con_code   -- 成分股票代码
  trade_date -- 交易日期（YYYYMMDD）

输出字段:
  trade_date, ts_code, con_code, name
"""

import time
import collections
import threading
import datetime
from typing import Optional

import tushare as ts
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN

_RATE_LIMIT = 100
_WINDOW = 60.0
_rate_lock = threading.Lock()
_call_times: collections.deque = collections.deque()

_PAGE_SIZE = 4800   # 保守低于接口上限 5000

_COLS = ["trade_date", "ts_code", "con_code", "name"]


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
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    return df


def fetch_dc_member(
    ts_code: Optional[str] = None,
    con_code: Optional[str] = None,
    trade_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取东方财富板块成分股数据，支持分页。

    参数
    ----
    ts_code    : 板块代码，如 'BK1184.DC'
    con_code   : 成分股代码，如 '002117.SZ'
    trade_date : 交易日期，格式 YYYYMMDD

    返回
    ----
    pd.DataFrame

    示例
    ----
    >>> df = fetch_dc_member(trade_date='20250102', ts_code='BK1184.DC')
    >>> df = fetch_dc_member(trade_date='20250102')  # 当日全量成分
    """
    pro = _get_pro_api()
    frames = []
    offset = 0

    while True:
        _rate_limit_wait()
        kwargs = dict(limit=_PAGE_SIZE, offset=offset)
        if ts_code:    kwargs["ts_code"] = ts_code
        if con_code:   kwargs["con_code"] = con_code
        if trade_date: kwargs["trade_date"] = trade_date

        try:
            df = pro.dc_member(**kwargs)
        except Exception as e:
            print(f"[dc_member] offset={offset} 出错：{e}")
            break

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
    return result.drop_duplicates(
        subset=["trade_date", "ts_code", "con_code"]
    ).reset_index(drop=True)


def fetch_dc_member_by_board(
    ts_code: str,
    trade_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取指定板块的成分股列表。

    参数
    ----
    ts_code    : 板块代码，如 'BK1184.DC'
    trade_date : 交易日期，不填则取最新日期

    返回
    ----
    pd.DataFrame
    """
    return fetch_dc_member(ts_code=ts_code, trade_date=trade_date)


def fetch_dc_member_date_range(
    start_date: str,
    end_date: Optional[str] = None,
    ts_code: Optional[str] = None,
    sleep_sec: float = 0.5,
) -> pd.DataFrame:
    """
    按日期区间批量拉取板块成分数据（逐日拉取）。

    注意: dc_member 数据量大（每日数千条），建议仅按需拉取指定板块或特定日期。

    参数
    ----
    start_date : 开始日期，格式 YYYYMMDD
    end_date   : 结束日期，格式 YYYYMMDD；不填则使用今日
    ts_code    : 板块代码，不填则拉全量（数据量极大，慎用）
    sleep_sec  : 每次请求后的等待秒数

    返回
    ----
    pd.DataFrame
    """
    def _parse(d: str):
        return datetime.date(int(d[:4]), int(d[4:6]), int(d[6:]))

    today = datetime.date.today()
    end = _parse(end_date) if end_date else today
    cur = _parse(start_date)
    delta = datetime.timedelta(days=1)

    frames = []
    while cur <= end:
        d = cur.strftime("%Y%m%d")
        print(f"[dc_member] 拉取 {d}{f' ts_code={ts_code}' if ts_code else ''} ...")
        try:
            df = fetch_dc_member(trade_date=d, ts_code=ts_code)
            if not df.empty:
                frames.append(df)
                print(f"[dc_member] {d} 取得 {len(df)} 行。")
            else:
                print(f"[dc_member] {d} 返回空数据（非交易日或暂无数据），跳过。")
        except Exception as e:
            print(f"[dc_member] {d} 出错：{e}")
        if sleep_sec > 0:
            time.sleep(sleep_sec)
        cur += delta

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
