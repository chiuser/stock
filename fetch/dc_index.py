"""
使用 tushare 获取东方财富概念板块每日快照数据（dc_index）。

tushare 接口: dc_index
描述: 获取东方财富每个交易日的概念板块数据，支持按日期查询
限量: 单次最大 5000 条，历史数据可根据日期循环获取
所需积分: 6000

输入参数（idx_type 必填）:
  ts_code    -- 指数代码（支持多个代码同时输入，逗号分隔）
  name       -- 板块名称
  trade_date -- 交易日期（YYYYMMDD）
  start_date -- 开始日期
  end_date   -- 结束日期
  idx_type   -- 板块类型（行业板块、概念板块、地域板块）必填

输出字段:
  ts_code, trade_date, name, leading, leading_code,
  pct_change, leading_pct, total_mv, turnover_rate,
  up_num, down_num, idx_type, level
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

# idx_type 三种类型
_IDX_TYPES = ["行业板块", "概念板块", "地域板块"]

_COLS = [
    "ts_code", "trade_date", "name", "leading_name", "leading_code",
    "pct_change", "leading_pct", "total_mv", "turnover_rate",
    "up_num", "down_num", "idx_type", "level",
]

# tushare 接口返回字段名为 leading，落库映射为 leading_name
_RENAME = {"leading": "leading_name"}


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
    # tushare 返回 leading，重命名为 leading_name 避免 PostgreSQL 保留字冲突
    df = df.rename(columns=_RENAME)
    cols = [c for c in _COLS if c in df.columns]
    df = df[cols].copy()
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    return df


def fetch_dc_index(
    ts_code: Optional[str] = None,
    name: Optional[str] = None,
    trade_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    idx_type: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取东方财富概念板块每日快照数据，支持分页。

    参数
    ----
    ts_code    : 指数代码（支持多个，逗号分隔）
    name       : 板块名称
    trade_date : 单日，格式 YYYYMMDD
    start_date : 开始日期，格式 YYYYMMDD
    end_date   : 结束日期，格式 YYYYMMDD
    idx_type   : 板块类型（行业板块/概念板块/地域板块），None = 拉取全部类型

    返回
    ----
    pd.DataFrame

    示例
    ----
    >>> df = fetch_dc_index(trade_date='20250103', idx_type='概念板块')
    >>> df = fetch_dc_index(trade_date='20250103')  # 拉全部类型
    """
    pro = _get_pro_api()
    types_to_fetch = [idx_type] if idx_type else _IDX_TYPES
    all_frames = []

    for itype in types_to_fetch:
        offset = 0
        while True:
            _rate_limit_wait()
            kwargs = dict(idx_type=itype, limit=_PAGE_SIZE, offset=offset)
            if ts_code:    kwargs["ts_code"] = ts_code
            if name:       kwargs["name"] = name
            if trade_date: kwargs["trade_date"] = trade_date
            if start_date: kwargs["start_date"] = start_date
            if end_date:   kwargs["end_date"] = end_date

            try:
                df = pro.dc_index(**kwargs)
            except Exception as e:
                print(f"[dc_index] idx_type={itype} offset={offset} 出错：{e}")
                break

            if df is None or df.empty:
                break
            all_frames.append(df)
            if len(df) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

    if not all_frames:
        return pd.DataFrame()

    result = pd.concat(all_frames, ignore_index=True)
    result = _clean(result)
    return result.drop_duplicates(subset=["ts_code", "trade_date"]).reset_index(drop=True)


def fetch_dc_index_date_range(
    start_date: str,
    end_date: Optional[str] = None,
    idx_type: Optional[str] = None,
) -> pd.DataFrame:
    """
    按日期区间批量拉取东方财富板块快照（逐日拉取）。

    参数
    ----
    start_date : 开始日期，格式 YYYYMMDD
    end_date   : 结束日期，格式 YYYYMMDD；不填则使用今日
    idx_type   : 板块类型（行业板块/概念板块/地域板块），None = 全部

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
        print(f"[dc_index] 拉取 {d} ...")
        try:
            df = fetch_dc_index(trade_date=d, idx_type=idx_type)
            if not df.empty:
                frames.append(df)
                print(f"[dc_index] {d} 取得 {len(df)} 行。")
            else:
                print(f"[dc_index] {d} 返回空数据（非交易日或暂无数据），跳过。")
        except Exception as e:
            print(f"[dc_index] {d} 出错：{e}")
        cur += delta

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
