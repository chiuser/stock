"""
使用 tushare 获取东财概念及行业板块资金流向数据（moneyflow_ind_dc）。

tushare 接口: moneyflow_ind_dc
  每日盘后更新，限量: 单次最大 5000 行，可按日期和代码循环提取
  所需积分: 6000
  content_type: 行业 / 概念 / 地域

输入参数（均可选）:
  ts_code      -- DC板块代码
  trade_date   -- 交易日期，格式 YYYYMMDD
  start_date   -- 开始日期，格式 YYYYMMDD
  end_date     -- 结束日期，格式 YYYYMMDD
  content_type -- 资金类型（行业、概念、地域）

输出字段:
  trade_date, content_type, ts_code, name, pct_change, close,
  net_amount, net_amount_rate,
  buy_elg_amount, buy_elg_amount_rate,
  buy_lg_amount, buy_lg_amount_rate,
  buy_md_amount, buy_md_amount_rate,
  buy_sm_amount, buy_sm_amount_rate,
  buy_sm_amount_stock, rank

注意: 金额单位为元（非万元）。
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

_RATE_LIMIT = 100
_WINDOW = 60.0
_rate_lock = threading.Lock()
_call_times: collections.deque = collections.deque()

_COLS = [
    "trade_date", "content_type", "ts_code", "name", "pct_change", "close",
    "net_amount", "net_amount_rate",
    "buy_elg_amount", "buy_elg_amount_rate",
    "buy_lg_amount", "buy_lg_amount_rate",
    "buy_md_amount", "buy_md_amount_rate",
    "buy_sm_amount", "buy_sm_amount_rate",
    "buy_sm_amount_stock", "rank",
]
_PAGE_SIZE = 4000  # 单次拉取行数，保守低于接口上限 5000


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


def fetch_moneyflow_ind_dc(
    ts_code: Optional[str] = None,
    trade_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    content_type: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取东财板块资金流向数据，支持分页。

    参数
    ----
    ts_code : str, optional
        DC板块代码
    trade_date : str, optional
        单日，格式 YYYYMMDD
    start_date : str, optional
        开始日期，格式 YYYYMMDD
    end_date : str, optional
        结束日期，格式 YYYYMMDD
    content_type : str, optional
        资金类型（行业、概念、地域）

    返回
    ----
    pd.DataFrame

    示例
    ----
    >>> df = fetch_moneyflow_ind_dc(trade_date='20240927')
    >>> df = fetch_moneyflow_ind_dc(trade_date='20240927', content_type='行业')
    """
    pro = _get_pro_api()
    frames = []
    offset = 0

    while True:
        _rate_limit_wait()
        kwargs = dict(limit=_PAGE_SIZE, offset=offset)
        if ts_code:      kwargs["ts_code"] = ts_code
        if trade_date:   kwargs["trade_date"] = trade_date
        if start_date:   kwargs["start_date"] = start_date
        if end_date:     kwargs["end_date"] = end_date
        if content_type: kwargs["content_type"] = content_type

        df = pro.moneyflow_ind_dc(**kwargs)
        if df is None or df.empty:
            break
        frames.append(df)
        if len(df) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    cols = [c for c in _COLS if c in result.columns]
    return result[cols].drop_duplicates(subset=["trade_date", "ts_code"]).reset_index(drop=True)


def fetch_moneyflow_ind_dc_date_range(
    start_date: str,
    end_date: Optional[str] = None,
    content_type: Optional[str] = None,
) -> pd.DataFrame:
    """
    按日期区间批量拉取板块资金流向（逐日拉取）。

    参数
    ----
    start_date : str
        开始日期，格式 YYYYMMDD
    end_date : str, optional
        结束日期，格式 YYYYMMDD；不填则使用今日
    content_type : str, optional
        资金类型（行业、概念、地域）

    返回
    ----
    pd.DataFrame
    """
    import datetime

    def _parse(d: str):
        return datetime.date(int(d[:4]), int(d[4:6]), int(d[6:]))

    today = datetime.date.today()
    end = _parse(end_date) if end_date else today
    cur = _parse(start_date)
    delta = datetime.timedelta(days=1)

    frames = []
    while cur <= end:
        d = cur.strftime("%Y%m%d")
        print(f"[moneyflow_ind_dc] 拉取 {d} ...")
        try:
            df = fetch_moneyflow_ind_dc(trade_date=d, content_type=content_type)
            if not df.empty:
                frames.append(df)
                print(f"[moneyflow_ind_dc] {d} 取得 {len(df)} 行。")
            else:
                print(f"[moneyflow_ind_dc] {d} 返回空数据（非交易日或暂无数据），跳过。")
        except Exception as e:
            print(f"[moneyflow_ind_dc] {d} 出错：{e}")
        cur += delta

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
