"""
使用 tushare 获取东财大盘资金流向数据（moneyflow_mkt_dc）。

tushare 接口: moneyflow_mkt_dc
  每日盘后更新，限量: 单次最大 3000 行，可按日期或日期区间循环提取
  所需积分: 6000（120 积分可试用）

输入参数（均可选）:
  trade_date -- 交易日期，格式 YYYYMMDD
  start_date -- 开始日期，格式 YYYYMMDD
  end_date   -- 结束日期，格式 YYYYMMDD

输出字段:
  trade_date,
  close_sh, pct_change_sh, close_sz, pct_change_sz,
  net_amount, net_amount_rate,
  buy_elg_amount, buy_elg_amount_rate,
  buy_lg_amount, buy_lg_amount_rate,
  buy_md_amount, buy_md_amount_rate,
  buy_sm_amount, buy_sm_amount_rate

注意: 金额单位为元。
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
    "trade_date",
    "close_sh", "pct_change_sh", "close_sz", "pct_change_sz",
    "net_amount", "net_amount_rate",
    "buy_elg_amount", "buy_elg_amount_rate",
    "buy_lg_amount", "buy_lg_amount_rate",
    "buy_md_amount", "buy_md_amount_rate",
    "buy_sm_amount", "buy_sm_amount_rate",
]
_PAGE_SIZE = 2000


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


def fetch_moneyflow_mkt_dc(
    trade_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取东财大盘资金流向数据，支持分页。

    参数
    ----
    trade_date : str, optional
        单日，格式 YYYYMMDD
    start_date : str, optional
        开始日期，格式 YYYYMMDD
    end_date : str, optional
        结束日期，格式 YYYYMMDD

    返回
    ----
    pd.DataFrame，每行对应一个交易日

    示例
    ----
    >>> df = fetch_moneyflow_mkt_dc(start_date='20240901', end_date='20240930')
    >>> df = fetch_moneyflow_mkt_dc(trade_date='20240927')
    """
    pro = _get_pro_api()
    frames = []
    offset = 0

    while True:
        _rate_limit_wait()
        df = pro.moneyflow_mkt_dc(
            trade_date=trade_date or "",
            start_date=start_date or "",
            end_date=end_date or "",
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
    cols = [c for c in _COLS if c in result.columns]
    return result[cols].drop_duplicates(subset=["trade_date"]).reset_index(drop=True)
