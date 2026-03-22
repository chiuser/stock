"""
使用 tushare 获取东方财富板块行情数据（dc_daily）。

tushare 接口: dc_daily
描述: 获取东方财富概念板块、行业指数板块、地域板块行情数据，历史数据起始于2020年
限量: 单次最大 2000 条，可根据日期参数循环获取
所需积分: 6000

输入参数（均可选）:
  ts_code    -- 板块代码（格式: xxxxx.DC）
  trade_date -- 交易日期（YYYYMMDD）
  start_date -- 开始日期
  end_date   -- 结束日期
  idx_type   -- 板块类型（概念板块、行业板块、地域板块）

输出字段:
  ts_code, trade_date, close, open, high, low,
  change, pct_change, vol, amount, swing, turnover_rate
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

_PAGE_SIZE = 1900   # 保守低于接口上限 2000

_COLS = [
    "ts_code", "trade_date",
    "open", "high", "low", "close",
    "change", "pct_change",
    "vol", "amount",
    "swing", "turnover_rate",
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
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    return df


def fetch_dc_daily(
    ts_code: Optional[str] = None,
    trade_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    idx_type: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取东方财富板块行情数据，支持分页。

    注意: 单次上限仅 2000 条，按日期拉取时若板块数超过 2000 需分页。
    实际板块数（行业+概念+地域合计）约 500 条，一般不超限。

    参数
    ----
    ts_code    : 板块代码，如 'BK1063.DC'
    trade_date : 单日，格式 YYYYMMDD
    start_date : 开始日期，格式 YYYYMMDD
    end_date   : 结束日期，格式 YYYYMMDD
    idx_type   : 板块类型（概念板块/行业板块/地域板块），None = 不过滤

    返回
    ----
    pd.DataFrame

    示例
    ----
    >>> df = fetch_dc_daily(trade_date='20250513')
    >>> df = fetch_dc_daily(ts_code='BK1063.DC', start_date='20240101')
    """
    pro = _get_pro_api()
    frames = []
    offset = 0

    while True:
        _rate_limit_wait()
        kwargs = dict(limit=_PAGE_SIZE, offset=offset)
        if ts_code:    kwargs["ts_code"] = ts_code
        if trade_date: kwargs["trade_date"] = trade_date
        if start_date: kwargs["start_date"] = start_date
        if end_date:   kwargs["end_date"] = end_date
        if idx_type:   kwargs["idx_type"] = idx_type

        try:
            df = pro.dc_daily(**kwargs)
        except Exception as e:
            print(f"[dc_daily] offset={offset} 出错：{e}")
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
    return result.drop_duplicates(subset=["ts_code", "trade_date"]).reset_index(drop=True)


def fetch_dc_daily_by_date(trade_date: str) -> pd.DataFrame:
    """
    获取指定日期全量板块行情（日常更新推荐）。

    参数
    ----
    trade_date : 交易日期，格式 YYYYMMDD

    返回
    ----
    pd.DataFrame
    """
    return fetch_dc_daily(trade_date=trade_date)


def fetch_dc_daily_by_code(
    ts_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取指定板块的历史行情（历史回填推荐）。

    参数
    ----
    ts_code    : 板块代码，如 'BK1063.DC'
    start_date : 开始日期，格式 YYYYMMDD
    end_date   : 结束日期，格式 YYYYMMDD

    返回
    ----
    pd.DataFrame
    """
    return fetch_dc_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)


def fetch_dc_daily_date_range(
    start_date: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    按日期区间批量拉取板块行情（逐日拉取）。

    参数
    ----
    start_date : 开始日期，格式 YYYYMMDD
    end_date   : 结束日期，格式 YYYYMMDD；不填则使用今日

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
        print(f"[dc_daily] 拉取 {d} ...")
        try:
            df = fetch_dc_daily_by_date(d)
            if not df.empty:
                frames.append(df)
                print(f"[dc_daily] {d} 取得 {len(df)} 行。")
            else:
                print(f"[dc_daily] {d} 返回空数据（非交易日或暂无数据），跳过。")
        except Exception as e:
            print(f"[dc_daily] {d} 出错：{e}")
        cur += delta

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_dc_daily_all_codes(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sleep_sec: float = 0.3,
) -> pd.DataFrame:
    """
    历史回填：从 dc_index 读取板块代码，逐个拉取历史行情。
    适合首次全量历史导入，API 调用次数 = 板块数量。

    参数
    ----
    start_date : 开始日期，格式 YYYYMMDD（历史数据起始于20200101）
    end_date   : 结束日期，格式 YYYYMMDD
    sleep_sec  : 每个板块之间的等待秒数

    返回
    ----
    pd.DataFrame
    """
    # 从数据库读取已知板块代码
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT ts_code FROM dc_index ORDER BY ts_code")
                codes = [r[0] for r in cur.fetchall()]
    except Exception as e:
        print(f"[dc_daily] 读取板块代码失败：{e}")
        return pd.DataFrame()

    if not codes:
        print("[dc_daily] dc_index 表为空，请先拉取 dc_index 数据。")
        return pd.DataFrame()

    print(f"[dc_daily] 共 {len(codes)} 个板块，开始逐个回填历史行情...")
    frames = []
    for i, code in enumerate(codes, 1):
        print(f"[dc_daily] ({i}/{len(codes)}) {code} ...")
        try:
            df = fetch_dc_daily_by_code(code, start_date=start_date, end_date=end_date)
            if not df.empty:
                frames.append(df)
                print(f"[dc_daily] {code} 取得 {len(df)} 行。")
        except Exception as e:
            print(f"[dc_daily] {code} 出错：{e}")
        if sleep_sec > 0:
            time.sleep(sleep_sec)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
